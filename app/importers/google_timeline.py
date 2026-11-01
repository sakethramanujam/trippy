"""Google Maps Timeline → drives.

Two export shapes are understood:

* The newer on-device export (Timeline.json from Settings → Location → Timeline → Export, on
  Android; the iPhone app writes the same data as a top-level list). Top-level
  ``semanticSegments`` holding ``activity`` (``topCandidate.type`` IN_PASSENGER_VEHICLE /
  driving, ``distanceMeters``), ``visit`` (``topCandidate.placeLocation`` / ``semanticType``) and
  ``timelinePath`` points.
* The older Takeout "Semantic Location History" monthly files: ``timelineObjects`` with
  ``activitySegment`` / ``placeVisit``.

Only driving segments become drives. Consecutive drives with a short stop between them (fuel,
coffee) are merged and the stop is kept. Paths are downsampled so a drive stays small.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from .. import airports
from .common import ImportError_, item

SOURCE = "google_timeline"
DRIVING = {"IN_PASSENGER_VEHICLE", "IN_VEHICLE", "IN_CAR", "DRIVING", "IN_TAXI", "MOTORCYCLING"}
MAX_PATH_POINTS = 120
MERGE_GAP = timedelta(minutes=30)     # drives this close together become one, with a stop
PLACE_SLACK = timedelta(minutes=45)   # how far a visit can be from a drive's start/end
MIN_MILES = 0.3
METERS_PER_MILE = 1609.344

_NUM = r"(-?\d+(?:\.\d+)?)"
_LATLNG = re.compile(rf"^\s*(?:geo:)?\s*{_NUM}\s*°?\s*,\s*{_NUM}\s*°?\s*$")


# --- small parsers -----------------------------------------------------------------------------

def parse_latlng(v: Any) -> Optional[tuple[float, float]]:
    """"37.42°, -122.08°", "geo:37.42,-122.08", {"latLng": …}, {"latitudeE7": …} → (lat, lng)."""
    if v is None:
        return None
    if isinstance(v, dict):
        for a, b, scale in (("latitudeE7", "longitudeE7", 1e7), ("latE7", "lngE7", 1e7),
                            ("lat", "lng", 1), ("latitude", "longitude", 1)):
            if v.get(a) is not None and v.get(b) is not None:
                try:
                    return _valid(float(v[a]) / scale, float(v[b]) / scale)
                except (TypeError, ValueError):
                    return None
        for k in ("latLng", "point", "placeLocation", "location"):
            if k in v:
                return parse_latlng(v[k])
        return None
    if isinstance(v, str):
        m = _LATLNG.match(v)
        if m:
            return _valid(float(m.group(1)), float(m.group(2)))
    return None


def _valid(lat: float, lng: float) -> Optional[tuple[float, float]]:
    if -90 <= lat <= 90 and -180 <= lng <= 180 and not (lat == 0 and lng == 0):
        return (lat, lng)
    return None


def parse_time(v: Any) -> Optional[datetime]:
    """ISO 8601 with a zone ("…Z", "…-07:00") or epoch milliseconds → aware datetime."""
    if v is None:
        return None
    if isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit()):
        try:
            return datetime.fromtimestamp(int(v) / 1000, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(v, str):
        return None
    t = v.strip().replace("Z", "+00:00")
    m = re.match(r"^(.*T\d\d:\d\d:\d\d)\.(\d+)(.*)$", t)  # Python < 3.11 wants ≤ 6 fraction digits
    if m:
        t = f"{m.group(1)}.{m.group(2)[:6].ljust(6, '0')}{m.group(3)}"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _miles(a: tuple[float, float], b: tuple[float, float]) -> float:
    return airports.haversine_miles(a[0], a[1], b[0], b[1])


def downsample(points: list[tuple[float, float]], limit: int = MAX_PATH_POINTS) -> list[list[float]]:
    """Evenly thin a polyline to at most `limit` points, keeping both ends; drop repeats."""
    pts: list[tuple[float, float]] = []
    for p in points:
        if not pts or (round(p[0], 5), round(p[1], 5)) != (round(pts[-1][0], 5), round(pts[-1][1], 5)):
            pts.append(p)
    if len(pts) > limit:
        step = (len(pts) - 1) / (limit - 1)
        pts = [pts[round(i * step)] for i in range(limit)]
    return [[round(p[0], 5), round(p[1], 5)] for p in pts]


def _pretty(semantic: Optional[str]) -> Optional[str]:
    if not semantic:
        return None
    s = semantic.upper().removeprefix("TYPE_")
    if s in ("UNKNOWN", "SEARCHED_ADDRESS", "ALIASED_LOCATION", "NONE"):
        return None
    return s.replace("_", " ").capitalize()


def place_name(name: Optional[str], semantic: Optional[str], ll: Optional[tuple[float, float]]) -> Optional[str]:
    if name and name.strip():
        return name.strip()[:120]
    label = _pretty(semantic)
    if label:
        return label
    if ll:
        code = airports.nearest(ll[0], ll[1], max_miles=40)
        hit = airports.lookup(code) if code else None
        if hit:
            return f"Near {hit[0]}"
    return None


# --- normalised events -------------------------------------------------------------------------

class _Zone:
    """Turns aware datetimes into Trippy's local wall-clock time plus a UTC offset."""

    def __init__(self, tz_name: Optional[str]):
        self.tz = None
        self.name = tz_name or "UTC"
        try:
            from zoneinfo import ZoneInfo
            self.tz = ZoneInfo(self.name)
        except Exception:  # unknown zone or no tzdata: fall back to UTC
            self.tz = timezone.utc
            self.name = "UTC"

    def local(self, dt: datetime, offset_minutes: Optional[int], trust_iso: bool) -> tuple[datetime, int]:
        if offset_minutes is not None:
            off = int(offset_minutes)
        elif trust_iso and dt.utcoffset() is not None and dt.utcoffset() != timedelta(0):
            off = int(dt.utcoffset().total_seconds() // 60)
        else:
            off = int((dt.astimezone(self.tz).utcoffset() or timedelta(0)).total_seconds() // 60)
        local = dt.astimezone(timezone(timedelta(minutes=off)))
        return local.replace(tzinfo=None, microsecond=0), off


def _type_of(activity: dict) -> str:
    cand = activity.get("topCandidate") or {}
    t = cand.get("type") if isinstance(cand, dict) else None
    t = t or activity.get("activityType") or ""
    return str(t).strip().upper().replace(" ", "_")


def _is_driving(t: str) -> bool:
    return t in DRIVING


def _segments_new(segments: Iterable[dict]) -> tuple[list[dict], list[dict], list[tuple[datetime, float, float]], int]:
    drives, visits, path = [], [], []
    count = 0
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        count += 1
        start, end = parse_time(seg.get("startTime")), parse_time(seg.get("endTime"))
        so, eo = seg.get("startTimeTimezoneUtcOffsetMinutes"), seg.get("endTimeTimezoneUtcOffsetMinutes")
        if isinstance(seg.get("activity"), dict) and start and end:
            a = seg["activity"]
            t = _type_of(a)
            if _is_driving(t):
                try:
                    dist = float(a.get("distanceMeters")) if a.get("distanceMeters") is not None else None
                except (TypeError, ValueError):
                    dist = None
                drives.append({"start": start, "end": end, "so": so, "eo": eo, "meters": dist,
                               "a": parse_latlng(a.get("start")), "b": parse_latlng(a.get("end")), "path": []})
        elif isinstance(seg.get("visit"), dict) and start and end:
            cand = seg["visit"].get("topCandidate") or {}
            ll = parse_latlng(cand.get("placeLocation"))
            visits.append({"start": start, "end": end, "ll": ll, "name": None,
                           "semantic": cand.get("semanticType")})
        if isinstance(seg.get("timelinePath"), list) and start:
            for p in seg["timelinePath"]:
                if not isinstance(p, dict):
                    continue
                ll = parse_latlng(p.get("point"))
                when = parse_time(p.get("time"))
                if when is None and p.get("durationMinutesOffsetFromStartTime") is not None:
                    try:
                        when = start + timedelta(minutes=float(p["durationMinutesOffsetFromStartTime"]))
                    except (TypeError, ValueError):
                        when = None
                if ll and when:
                    path.append((when, ll[0], ll[1]))
    return drives, visits, path, count


def _segments_old(objects: Iterable[dict]) -> tuple[list[dict], list[dict], int]:
    drives, visits = [], []
    count = 0
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        count += 1
        if isinstance(obj.get("activitySegment"), dict):
            s = obj["activitySegment"]
            dur = s.get("duration") or {}
            start = parse_time(dur.get("startTimestamp") or dur.get("startTimestampMs"))
            end = parse_time(dur.get("endTimestamp") or dur.get("endTimestampMs"))
            if not (start and end) or not _is_driving(_type_of(s)):
                continue
            pts: list[tuple[datetime, float, float]] = []
            for p in (s.get("simplifiedRawPath") or {}).get("points") or []:
                ll, when = parse_latlng(p), parse_time(p.get("timestamp") or p.get("timestampMs"))
                if ll:
                    pts.append((when or start, ll[0], ll[1]))
            if not pts:
                for p in (s.get("waypointPath") or {}).get("waypoints") or []:
                    ll = parse_latlng(p)
                    if ll:
                        pts.append((start, ll[0], ll[1]))
            meters = s.get("distance")
            if meters is None:
                meters = (s.get("waypointPath") or {}).get("distanceMeters")
            try:
                meters = float(meters) if meters is not None else None
            except (TypeError, ValueError):
                meters = None
            drives.append({"start": start, "end": end, "so": None, "eo": None, "meters": meters,
                           "a": parse_latlng(s.get("startLocation")), "b": parse_latlng(s.get("endLocation")),
                           "path": pts})
        elif isinstance(obj.get("placeVisit"), dict):
            v = obj["placeVisit"]
            dur = v.get("duration") or {}
            start = parse_time(dur.get("startTimestamp") or dur.get("startTimestampMs"))
            end = parse_time(dur.get("endTimestamp") or dur.get("endTimestampMs"))
            loc = v.get("location") or {}
            if start and end:
                visits.append({"start": start, "end": end, "ll": parse_latlng(loc), "name": loc.get("name"),
                               "semantic": loc.get("semanticType")})
    return drives, visits, count


def _load(data: bytes) -> Any:
    if data[:2] == b"PK":
        raise ImportError_("That's a zip file. Unzip the Takeout export and pick one Semantic Location History "
                           "JSON file (or the Timeline.json from your phone).")
    try:
        return json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ImportError_("That doesn't look like a Google Maps Timeline JSON file")


# --- main entry --------------------------------------------------------------------------------

def parse_timeline(data: bytes, tz_name: Optional[str] = None) -> tuple[list[dict], dict]:
    doc = _load(data)
    path: list[tuple[datetime, float, float]] = []
    if isinstance(doc, dict) and isinstance(doc.get("semanticSegments"), list):
        fmt = "on_device"
        drives, visits, path, count = _segments_new(doc["semanticSegments"])
    elif isinstance(doc, list) and any(isinstance(s, dict) and "startTime" in s for s in doc[:50]):
        fmt = "on_device"
        drives, visits, path, count = _segments_new(doc)
    elif isinstance(doc, dict) and isinstance(doc.get("timelineObjects"), list):
        fmt = "takeout"
        drives, visits, count = _segments_old(doc["timelineObjects"])
    elif isinstance(doc, dict) and isinstance(doc.get("locations"), list):
        raise ImportError_("That's raw location history (Records.json). Pick a Semantic Location History file "
                           "or the Timeline.json export instead.")
    else:
        raise ImportError_("That doesn't look like a Google Maps Timeline export")

    zone = _Zone(tz_name)
    warnings: list[str] = []
    if fmt == "takeout":
        warnings.append(f"Takeout files are in UTC; times are shown in {zone.name}")

    drives.sort(key=lambda d: d["start"])
    visits.sort(key=lambda v: v["start"])
    path.sort(key=lambda p: p[0])

    # Attach timelinePath points (on-device export keeps them in their own segments).
    if path:
        times = [p[0] for p in path]
        import bisect
        for d in drives:
            lo = bisect.bisect_left(times, d["start"] - timedelta(minutes=1))
            hi = bisect.bisect_right(times, d["end"] + timedelta(minutes=1))
            d["path"] = path[lo:hi]

    # Merge drives split by a short stop.
    merged: list[dict] = []
    for d in drives:
        d.setdefault("stops", [])
        if merged and timedelta(0) <= d["start"] - merged[-1]["end"] <= MERGE_GAP:
            prev = merged[-1]
            stop_ll = prev["b"] or d["a"]
            stop_visit = next((v for v in visits if v["start"] >= prev["end"] - timedelta(minutes=2)
                               and v["end"] <= d["start"] + timedelta(minutes=2)), None)
            if stop_visit and stop_visit["ll"]:
                stop_ll = stop_visit["ll"]
            if stop_ll:
                prev["stops"].append({
                    "name": place_name(stop_visit and stop_visit["name"], stop_visit and stop_visit["semantic"], stop_ll),
                    "lat": round(stop_ll[0], 5), "lng": round(stop_ll[1], 5),
                    "minutes": int((d["start"] - prev["end"]).total_seconds() // 60),
                })
            prev["end"], prev["eo"], prev["b"] = d["end"], d["eo"], d["b"] or prev["b"]
            prev["meters"] = (prev["meters"] or 0) + (d["meters"] or 0) if (prev["meters"] or d["meters"]) else None
            prev["path"] = prev["path"] + d["path"]
            continue
        merged.append(d)

    items: list[dict] = []
    short = 0
    for d in merged:
        pts = [(p[1], p[2]) for p in d["path"]]
        a = d["a"] or (pts[0] if pts else None)
        b = d["b"] or (pts[-1] if pts else None)
        line = ([a] if a else []) + pts + ([b] if b else [])
        if d["meters"] is not None:
            miles = d["meters"] / METERS_PER_MILE
        else:
            miles = sum(_miles(line[i], line[i + 1]) for i in range(len(line) - 1)) if len(line) > 1 else 0.0
        if miles < MIN_MILES:
            short += 1
            continue
        before = [v for v in visits if v["end"] <= d["start"] + timedelta(minutes=5)
                  and d["start"] - v["end"] <= PLACE_SLACK]
        after = [v for v in visits if v["start"] >= d["end"] - timedelta(minutes=5)
                 and v["start"] - d["end"] <= PLACE_SLACK]
        sv = before[-1] if before else None
        ev = after[0] if after else None
        s_ll = (sv and sv["ll"]) or a
        e_ll = (ev and ev["ll"]) or b
        start_local, so = zone.local(d["start"], d["so"], trust_iso=fmt == "on_device")
        end_local, eo = zone.local(d["end"], d["eo"], trust_iso=fmt == "on_device")
        start_place = {"name": place_name(sv and sv["name"], sv and sv["semantic"], s_ll),
                       "lat": round(s_ll[0], 5) if s_ll else None, "lng": round(s_ll[1], 5) if s_ll else None}
        end_place = {"name": place_name(ev and ev["name"], ev and ev["semantic"], e_ll),
                     "lat": round(e_ll[0], 5) if e_ll else None, "lng": round(e_ll[1], 5) if e_ll else None}
        key = f"{d['start'].astimezone(timezone.utc).isoformat()}|{d['end'].astimezone(timezone.utc).isoformat()}"
        ext = "gt:" + hashlib.sha1(key.encode()).hexdigest()[:20]
        minutes = int((d["end"] - d["start"]).total_seconds() // 60)
        fields = {
            "start_time": start_local, "end_time": end_local,
            "start_utc_offset": so, "end_utc_offset": eo,
            "distance_miles": round(miles, 1), "duration_minutes": minutes,
            "start_place": start_place, "end_place": end_place,
            "stops": d["stops"][:50], "path": downsample(line),
            "external_id": ext,
        }
        route = f"{start_place['name'] or 'Start'} → {end_place['name'] or 'End'}"
        stops = f" · {len(d['stops'])} stop{'s' if len(d['stops']) != 1 else ''}" if d["stops"] else ""
        summary = (f"{start_local.strftime('%b %-d, %Y')} · {start_local.strftime('%H:%M')}–{end_local.strftime('%H:%M')}"
                   f" · {miles:,.1f} mi · {route}{stops}")
        items.append(item("drive", fields, source=SOURCE, summary=summary,
                          confidence="high" if d["meters"] is not None else "medium",
                          warnings=list(warnings), ref=ext))
    stats = {"format": fmt, "segments": count, "drives": len(items), "skipped_short": short,
             "timezone": zone.name if fmt == "takeout" else None}
    return items, stats
