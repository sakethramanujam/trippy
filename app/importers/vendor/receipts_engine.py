# Vendored from Rental Car Tracker (tools/import_receipts.py + js/parsers/rules.json,
# the same author's project) at commit 3370820 on 2026-10-30. Do not edit here; update upstream and re-copy.
# Only parse_receipt() is used by Trippy. PDFs are not accepted by the import API.
#!/usr/bin/env python3
"""
Rental Car Tracker - local receipt importer.

Reads a folder (or list) of rental-car receipts (.pdf .eml .txt .html .htm) and writes
a JSON file the web app imports via  ⋯ → Import JSON.

    python3 tools/import_receipts.py ~/Receipts/rentals -o rentals-import.json
    python3 tools/import_receipts.py samples --dump-text      # see what the parser sees

Standard library only. PDFs are converted with `pdftotext -layout` (poppler-utils).

This is a line-for-line port of js/parsers/engine.js and uses the *same* regex rules
file (js/parsers/rules.json). Keep the two in sync; tests/run_tests.sh runs both against
the samples and checks they agree.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import email
import email.policy
import html as _html
import json
import math
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_RULES = os.path.join(HERE, "rental_rules.json")
EXTS = (".pdf", ".eml", ".txt", ".html", ".htm")
FLAGS = re.I | re.M
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]

_cache: dict = {}


def rx(src: str):
    r = _cache.get(src)
    if r is None:
        r = _cache[src] = re.compile(src, FLAGS)
    return r


# ------------------------------------------------------------------ text extraction

def html_to_text(s: str) -> str:
    s = re.sub(r"<!--[\s\S]*?-->", " ", s)
    s = re.sub(r"<(style|script|title|xml)\b[\s\S]*?</\1\s*>", " ", s, flags=re.I)
    s = re.sub(r"[ \t\r\n\f]+", " ", s)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</t[dh]>\s*<t[dh]\b[^>]*>", "\t", s, flags=re.I)
    s = re.sub(r"</(p|h[1-6]|table|blockquote)\s*>", "\n\n", s, flags=re.I)
    s = re.sub(r"</(div|tr|li|ul|ol|section|article|header|footer|center)\s*>", "\n", s, flags=re.I)
    s = re.sub(r"<(p|div|tr|table|h[1-6]|ul|ol|li|section|article|header|footer|center|blockquote)\b[^>]*>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = _html.unescape(s)
    s = "\n".join(re.sub(r" *\t *", "\t", l).strip() for l in s.split("\n"))
    return normalize_text(s)


def normalize_text(s: str) -> str:
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub("[\u00a0\u2007\u202f]", " ", s)
    s = re.sub("[\u200b\u200c\u200d\ufeff]", "", s)
    s = "\n".join(re.sub(r"[ \t]+$", "", l) for l in s.split("\n"))
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def looks_like_html(s: str) -> bool:
    return bool(re.search(r"<(html|body|table|div|p|br|td)\b", s, re.I))


def looks_like_eml(s: str) -> bool:
    s = s.replace("\r\n", "\n")
    return bool(re.match(r"(?:[\w-]+:[^\n]*\n(?:[ \t][^\n]*\n)*){2,}", s)) and bool(
        re.search(r"^(?:content-type|mime-version|subject|from|received|message-id):", s[:4000], re.I | re.M))


def pdf_to_text(path: str) -> str:
    exe = shutil.which("pdftotext")
    if not exe:
        raise RuntimeError("pdftotext not found - install poppler-utils (apt install poppler-utils / brew install poppler)")
    out = subprocess.run([exe, "-layout", "-enc", "UTF-8", path, "-"], capture_output=True, check=True)
    return out.stdout.decode("utf-8", "replace").replace("\f", "\n")


def extract_candidates(data: bytes, filename: str = "") -> list[dict]:
    lower = filename.lower()
    if lower.endswith(".pdf"):
        # Never pass the client-supplied filename to pdftotext as a path: write the bytes to a temp file.
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
            tmp.write(data)
            tmp.flush()
            return [{"kind": "application/pdf", "subject": "", "text": normalize_text(pdf_to_text(tmp.name))}]
    raw = data.decode("utf-8", "replace")
    if lower.endswith(".eml") or (not lower.endswith((".html", ".htm")) and looks_like_eml(raw)):
        msg = email.message_from_bytes(data, policy=email.policy.default)
        subject = str(msg.get("subject", "") or "")
        pre = "From: %s\nSubject: %s" % (str(msg.get("from", "") or ""), subject)
        cands = []
        for part in msg.walk():
            ctype = part.get_content_type()
            if part.is_multipart() or ctype not in ("text/plain", "text/html"):
                continue
            try:
                body = part.get_content()
            except Exception:  # bad charset etc.
                body = (part.get_payload(decode=True) or b"").decode("utf-8", "replace")
            text = html_to_text(body) if ctype == "text/html" else body
            cands.append({"kind": ctype, "subject": subject, "text": normalize_text(pre + "\n\n" + text)})
        if cands:
            return cands
    if lower.endswith((".html", ".htm")) or looks_like_html(raw):
        t = re.search(r"<title[^>]*>([\s\S]*?)</title>", raw, re.I)
        subject = _html.unescape(t.group(1).strip()) if t else ""
        return [{"kind": "text/html", "subject": subject,
                 "text": normalize_text(("Subject: " + subject + "\n\n" if subject else "") + html_to_text(raw))}]
    sm = re.search(r"^[ \t]*Subject:[ \t]*([^\n]+)", raw, re.I | re.M)
    return [{"kind": "text/plain", "subject": sm.group(1).strip() if sm else "", "text": normalize_text(raw)}]


# ------------------------------------------------------------------ helpers

def get_path(o, path):
    for k in path.split("."):
        if o is None:
            return None
        o = o.get(k)
    return o


def set_path(o, path, v):
    ks = path.split(".")
    for k in ks[:-1]:
        o = o.setdefault(k, {})
    o[ks[-1]] = v


def clean(s) -> str:
    s = re.sub(r"[ \t]+", " ", str(s))
    s = re.sub(r"^[\s:#\-–]+|[\s,;:]+$", "", s)
    return s.strip()


def round2(x: float) -> float:
    """Half-up rounding to cents, identical to JS Math.round(x * 100) / 100."""
    return math.floor(x * 100 + 0.5) / 100


def parse_money(s):
    if s is None or s == "":
        return None
    try:
        return round2(float(re.sub(r"[$,\s]", "", str(s))))
    except ValueError:
        return None


def parse_int(s):
    try:
        return int(re.sub(r"[,\s]", "", str(s)))
    except ValueError:
        return None


TYPES = {"mileage.out": "int", "mileage.in": "int", "mileage.driven": "int", "days": "int", "weeks": "int",
         "dailyRate": "money", "weeklyRate": "money", "total": "money", "vehicle.year": "int",
         "pickup.datetime": "datetime", "return.datetime": "datetime"}


def convert(path, v, rules=None):
    t = TYPES.get(path)
    if t == "int":
        return parse_int(v)
    if t == "money":
        return parse_money(v)
    if t == "datetime":
        d = find_datetime(clean(v), rules)
        return d["value"] if d else None
    c = clean(v)
    return c or None


# ------------------------------------------------------------------ dates

def find_datetime(s: str, rules):
    best = None
    for d in rules["dates"]:
        m = rx(d["re"]).search(s)
        if not m or (best and m.start() >= best["index"]):
            continue
        v = {role: m.group(i + 1) for i, role in enumerate(d["roles"])}
        month = MONTHS.index(v["mon"][:3].lower()) + 1 if v.get("mon") else int(v["month"])
        year = int(v["year"])
        if year < 100:
            year += 2000
        day = int(v["day"])
        if not (1 <= month <= 12 and 1 <= day <= 31 and 1990 < year < 2100):
            continue
        best = {"index": m.start(), "end": m.end(), "date": "%04d-%02d-%02d" % (year, month, day)}
    if not best:
        return None
    t = rx(rules["time"]).search(s[best["end"]:])
    if t:
        h, mi, ap = int(t.group(1)), int(t.group(2)), (t.group(3) or "").lower()
        if ap == "p" and h < 12:
            h += 12
        if ap == "a" and h == 12:
            h = 0
        if h < 24 and mi < 60:
            return dict(best, value="%sT%02d:%02d" % (best["date"], h, mi))
    return dict(best, value=best["date"])


# ------------------------------------------------------------------ blocks

LABEL_LINE = re.compile(r"^[A-Za-z][A-Za-z /#&.()-]{0,30}:[ \t]")
CITY_LINE = re.compile(r"^(.+?),[ \t]*([A-Z]{2})[ \t]+(\d{5}(?:-\d{4})?|[A-Z]\d[A-Z][ \t]?\d[A-Z]\d)[ \t]*$")


def first_match(text, patterns, start=0):
    best = None
    for p in patterns:
        m = rx(p).search(text, start)
        if m and (best is None or m.start() < best.start()):
            best = m
    return best


def extract_block(text, spec, rules):
    start = first_match(text, spec["start"])
    if not start:
        return None
    line_end = text.find("\n", start.end())
    head = clean(text[start.end(): len(text) if line_end < 0 else line_end])
    after = [] if line_end < 0 else text[line_end + 1:].split("\n")
    lines = [head] if head else []
    stops = spec["end"] + rules["generic"]["blocks"]["pickup"]["start"] + rules["generic"]["blocks"]["return"]["start"]
    for raw in after:
        line = re.sub(r"\t+", " ", raw).strip()
        if not line:
            if lines:
                break
            continue
        if any(rx(e).search(line) for e in stops):
            break
        lines.append(line)
        if len(lines) >= 8:
            break
    if not lines:
        return None
    block_text = "\n".join(lines)
    out = {}
    dt = find_datetime(block_text, rules)
    if dt:
        out["datetime"] = dt["value"]

    def is_dateish(l):
        d = find_datetime(l, rules)
        return bool(d) and d["index"] < 12

    def strip(l):
        return re.sub(r"^(?:location|branch|office|address)[ \t]*:[ \t]*", "", l, flags=re.I)

    if head and not is_dateish(head):
        loc_idx = 0
    else:
        loc_idx = next((i for i, l in enumerate(lines) if not is_dateish(l) and (not LABEL_LINE.search(l) or strip(l) != l)), -1)
    if loc_idx >= 0:
        out["location"] = clean(strip(lines[loc_idx]))
        addr = []
        for l in lines[loc_idx + 1:]:
            if is_dateish(l) and not addr:
                continue
            if LABEL_LINE.search(l) or is_dateish(l):
                break
            addr.append(l)
            cm = CITY_LINE.search(l)
            if cm:
                out["city"] = "%s, %s" % (cm.group(1).strip(), cm.group(2))
                break
            if len(addr) >= 3:
                break
        if addr:
            out["address"] = ", ".join(addr)
        code = re.search(r"\(([A-Z]{3})\)", out["location"]) or re.search(r",[ \t]*([A-Z]{3})$", out["location"]) or re.search(
            r"\b(?:airport|iata)[ \t]*code[ \t]*:?[ \t]*([A-Z]{3})\b", block_text, re.I)
        if code:
            out["code"] = code.group(1).upper()
    if "city" not in out:
        for l in lines:
            cm = CITY_LINE.search(l)
            if cm:
                out["city"] = "%s, %s" % (cm.group(1).strip(), cm.group(2))
                break
    return out


# ------------------------------------------------------------------ charges

def extract_charges(text, spec):
    start = first_match(text, spec["start"])
    if not start:
        return []
    frm = text.find("\n", start.start())
    if frm < 0:
        return []
    out, misses = [], 0
    for raw in text[frm + 1:].split("\n"):
        line = re.sub(r"\t+", "  ", raw)
        if any(rx(e).search(line) for e in spec["end"]):
            break
        m = rx(spec["line"]).search(line)
        if not m:
            if out and line.strip():
                misses += 1
                if misses >= 3:
                    break
            continue
        misses = 0
        label = re.sub(r"[ .:]+$", "", clean(m.group(1)))
        if not label or any(rx(s).search(label) for s in spec["skip"]):
            continue
        amount = parse_money(m.group(3))
        if amount is None:
            continue
        if m.group(2) == "-" and amount > 0:
            amount = -amount
        kind = "other"
        for k, r in spec["kinds"]:
            if rx(r).search(label):
                kind = k
                break
        if amount < 0:
            kind = "discount"
        out.append({"label": label, "amount": amount, "kind": kind})
        if len(out) > 40:
            break
    return out


# ------------------------------------------------------------------ vehicle

def split_vehicle(desc, rules):
    if not desc:
        return {}
    d = re.sub(r"[ \t]+or[ \t]+similar\b.*$", "", clean(desc), flags=re.I)
    d = re.sub(r"\s*\((?:or similar)\)\s*$", "", d, flags=re.I)
    letters = re.sub(r"[^A-Za-z]", "", d)
    if letters and letters == letters.upper():
        keep = {w.upper() for w in rules["keepUpper"]}

        def tc(w):
            if w.upper() in keep or re.search(r"\d", w) or len(w) <= 2:
                return w
            return re.sub(r"(^|[-'])([a-z])", lambda m: m.group(1) + m.group(2).upper(), w.lower())
        d = " ".join(tc(w) for w in d.split(" "))
    out = {"description": d}
    rest = d
    y = re.match(r"((?:19|20)\d{2})[ \t]+", rest)
    if y:
        out["year"] = int(y.group(1))
        rest = rest[y.end():]
    mk = next((m for m in rules["makes"] if rest.lower().startswith(m.lower() + " ")), None)
    make = rest[:len(mk)] if mk else rest.split(" ")[0]
    rest = rest[len(make):].strip()
    if make:
        out["make"] = make
    if rest:
        mm = next((m for m in rules["multiWordModels"]
                   if rest.lower() == m.lower() or rest.lower().startswith(m.lower() + " ")), None)
        model = rest[:len(mm)] if mm else rest.split(" ")[0]
        out["model"] = model
        trim = rest[len(model):].strip()
        if trim:
            out["trim"] = trim
    return out


def title_case(s) -> str:
    return re.sub(r"(^|[\s-])([a-z])", lambda m: m.group(1) + m.group(2).upper(), str(s).lower())


def expand_vehicle_codes(desc, rules):
    """Expand fleet abbreviations ("CHEV / MALI", "2020 NISN KICK", "ALTIMA") from rules.vehicleCodes."""
    vc = rules.get("vehicleCodes")
    if not desc or not vc:
        return desc
    toks = [t for t in re.sub(r"[ \t]*/[ \t]*", " ", clean(desc)).split(" ") if t]
    if not toks:
        return desc
    out, i = [], 0
    if re.match(r"^(?:19|20)\d{2}$", toks[0]):
        out.append(toks[0])
        i = 1
    tok = toks[i] if i < len(toks) else ""
    make = vc["makes"].get(tok.upper())
    if make:
        out.append(make)
        i += 1
        if i < len(toks):
            mdl = vc["models"].get(toks[i].upper())
            if not mdl and any(rx("^" + b + "$").search(toks[i]) for b in vc.get("bodyStyles", [])):
                return " ".join(out)
            if not mdl and make.upper() == toks[i - 1].upper():
                return desc
            out.append(mdl or toks[i])
            i += 1
    else:
        model = vc["models"].get(tok.upper()) or (title_case(tok) if vc["modelMakes"].get(title_case(tok)) else None)
        if not model:
            return desc
        if vc["modelMakes"].get(model):
            out.append(vc["modelMakes"][model])
        out.append(model)
        i += 1
    return " ".join(out + toks[i:])


BRANDS = [(r"^visa", "Visa"), (r"^(master|mc)", "Mastercard"), (r"^(amex|american)", "Amex"),
          (r"^disc", "Discover"), (r"^diners", "Diners Club")]


# ------------------------------------------------------------------ layout templates
# Each known receipt layout is described in rules.json "templates": a signature ("match") plus
# label-anchored operations. Templates run first; the generic rules above are only a fallback for
# layouts no template recognises. A template only sets a field when its label is present.

def rxc(src: str, cs=False):
    if not cs:
        return rx(src)
    key = "\u0000cs" + src
    r = _cache.get(key)
    if r is None:
        r = _cache[key] = re.compile(src, re.M)
    return r


def city_state(s):
    m = re.match(r"^\s*(.+?),[ \t]*([A-Z]{2})[ \t]+\d{5}(?:-?\d{4})?[ \t]*$", s or "")
    return "%s, %s" % (title_case(m.group(1).strip()), m.group(2)) if m else None


def tpl_value(raw, typ, rules):
    if raw is None:
        return None
    s = raw.strip()
    if typ == "str":
        return re.sub(r"[ \t]+", " ", s) or None
    if typ == "upper":
        return re.sub(r"[ \t]+", " ", s).upper() or None
    if typ == "title":
        return title_case(re.sub(r"[ \t]+", " ", s)) or None
    if typ == "join":
        return re.sub(r"\s+", " ", s) or None
    if typ == "nobreak":
        return re.sub(r"\s*\n\s*", "", s) or None
    if typ == "nospace":
        return re.sub(r"\s+", "", s) or None
    if typ == "int":
        return int(s.replace(",", "")) if re.match(r"^[\d,]+$", s) else None
    if typ == "money":
        return parse_money(s)
    if typ == "pct":
        return s + "%"
    if typ == "city":
        return city_state(s)
    if typ == "brand":
        return next((name for pat, name in BRANDS if re.search(pat, s, re.I)), title_case(s))
    if typ == "dt":
        s = re.sub(r"[ \t]*/[ \t]*", "/", s)
        s = re.sub(r"(\d)[ \t]*:[ \t]*(\d)", r"\1:\2", s)
        tm = re.search(r"\b\d{1,2}:\d\d(?:[ \t]*[AP]M)?\b", s, re.I)
        if tm:  # layout columns can put the time between the date and the year: move it last
            s = s[:tm.start()] + " " + s[tm.end():] + " " + tm.group(0)
        d = find_datetime(s, rules)
        return d["value"] if d and "T" in d["value"] else None
    raise ValueError("unknown template type " + typ)


def tpl_group(m, g):
    for i in (g if isinstance(g, list) else [g]):
        if m.group(i) is not None:
            return m.group(i)
    return None


def tpl_put(r, found, path, v):
    if v is None or v == "" or get_path(r, path) is not None:
        return
    set_path(r, path, v)
    found.add(path)


def tpl_vehicle(r, found, year, make_code, model_code, rules):
    vc = rules["vehicleCodes"]
    if year and re.match(r"^\d{2,4}$", year):
        y = int(year)
        tpl_put(r, found, "vehicle.year", y + 2000 if y < 100 else y)
    mc = (model_code or "").strip()
    model = vc["models"].get(mc.upper()) or (title_case(mc) if mc and vc["modelMakes"].get(title_case(mc)) else None)
    make = vc["makes"].get((make_code or "").strip().upper()) or (vc["modelMakes"].get(model) if model else None)
    tpl_put(r, found, "vehicle.make", make)
    tpl_put(r, found, "vehicle.model", model)


def split_columns(text, spec):
    """Cut a pdftotext -layout page into left / pickup / return / right regions by the header word positions."""
    lines = text.split("\n")
    hi = next((i for i, l in enumerate(lines) if rxc(spec["header"], True).search(l)), None)
    if hi is None:
        return None
    hm = rxc(spec["header"], True).search(lines[hi])
    pc, rc, sl = hm.start(1), hm.start(2), spec.get("slack", 3)
    end = next((i for i, l in enumerate(lines) if rxc(spec["end"], True).search(l)), len(lines))
    cstart = next((i for i, l in enumerate(lines) if rxc(spec["rightStart"], True).search(l)), len(lines))
    left, pick, ret, right = [], [], [], []
    for i, l in enumerate(lines):
        L, P, R, RT = [], [], [], []
        for c in re.finditer(r"\S+(?: \S+)*", l):
            s, x = c.group(0), c.start()
            if i <= hi:
                if x < pc - sl:
                    L.append(s)
                continue
            tm = re.match(r"^(\d{1,2}:\d\d [AP]M) (.+)$", s)
            if i < end and tm and pc - sl <= x < rc - sl:
                P.append(tm.group(1))
                R.append(tm.group(2))
            elif i < end and x >= rc - sl:
                R.append(tm.group(1) if tm else s)
            elif i < end and x >= pc - sl:
                P.append(s)
            elif x >= pc - sl:
                if i >= cstart:
                    RT.append(s)
            else:
                L.append(s)
        if L:
            left.append(" ".join(L))
        if P:
            pick.append(" ".join(P))
        if R:
            ret.append(" ".join(R))
        if RT:
            right.append("\t".join(RT))
    if spec.get("oneWay") and rxc(spec["oneWay"], True).search(hm.group(2)):
        k = next((j for j, l in enumerate(ret) if rxc(spec["actualReturn"], True).search(l)), None)
        ret = ret[k + 1:] if k is not None else []
    return {"left": "\n".join(left), "pickup": "\n".join(pick), "return": "\n".join(ret), "right": "\n".join(right)}


def tpl_stop(lines, spec, rules):
    """A trip column: date lines, optional "Start Charges" + its dates, branch name, street address, City, ST ZIP."""
    out = {}
    dl = rxc(spec["dateLine"], True)

    def ndate(c):
        k = 0
        while k < len(c) and k < 3 and dl.search(c[k]):
            k += 1
        return k
    k = ndate(lines)
    if k:
        v = tpl_value(" ".join(lines[:k]), "dt", rules)
        if v:
            out["datetime"] = v
    rest = lines[k:]
    if rest and spec.get("skip") and rxc(spec["skip"], True).search(rest[0]):
        rest = rest[1 + ndate(rest[1:]):]
    name, addr = [], None
    for l in rest:
        city = city_state(l)
        if city:
            if addr:
                out["address"] = addr
            out["city"] = city
            break
        if re.match(r"^\d", l) and addr is None:
            addr = l
        elif addr is not None:
            addr += " " + l
        else:
            name.append(l)
    if name and "city" in out:
        out["location"] = " ".join(name)
    return out


def tpl_charges(text, op, rules):
    out = []
    if op.get("section"):
        a = rxc(op["section"][0], op.get("cs")).search(text)
        if not a:
            return out
        text = text[a.end():]
        if len(op["section"]) > 1:
            b = rxc(op["section"][1], op.get("cs")).search(text)
            text = text[:b.start()] if b else text
    skip = rxc(op["skip"], op.get("cs")) if op.get("skip") else None
    kind = op["charges"]
    if kind == "lines":
        for m in rxc(op["re"], op.get("cs")).finditer(text):
            label = clean(m.group(op["label"]))
            if op.get("strip"):
                label = rxc(op["strip"], True).sub("", label)
            if skip and skip.search(label):
                continue
            amt = parse_money(m.group(op["amount"]))
            if amt is None:
                continue
            if op.get("neg") and m.group(op["neg"]):
                amt = -amt
            out.append({"label": label, "amount": amt})
    elif kind == "paired":
        labels = [m.group(1) for m in rxc(op["label"], op.get("cs")).finditer(text)]
        vals = [m for m in rxc(op["value"], op.get("cs")).finditer(text)]
        if len(labels) != len(vals) or not labels:
            return []
        for lab, v in zip(labels, vals):
            lab = clean(lab).rstrip("*")
            if skip and skip.search(lab):
                continue
            amt = parse_money(v.group(2))
            out.append({"label": lab, "amount": -amt if v.group(1) else amt})
    elif kind == "rows":  # tab-separated chunks; a row ends with an amount, earlier unpriced rows carry over
        pend = ""
        stop = rxc(op["stop"], True)
        cats = rxc(op["strip"], True) if op.get("strip") else None
        for row in text.split("\n"):
            cells = row.split("\t")
            if stop.search(cells[0]):
                break
            if skip and skip.search(cells[0]):
                continue
            last = cells[-1]
            if len(cells) > 1 and re.match(r"^\(?\$[\d,]+\.\d\d\)?$|^(?:Included|Waived)$", last):
                desc = clean(pend + " " + " ".join(cells[:-1]))
                pend = ""
                if cats:
                    desc = cats.sub("", desc, count=1)
                if re.match(r"^Subtotal", desc) or last[0] not in "($":
                    continue
                amt = parse_money(last.replace("(", "").replace(")", ""))
                out.append({"label": desc, "amount": -amt if last.startswith("(") else amt})
            else:
                pend = clean(pend + " " + " ".join(cells))
    return out


def match_template(text, rules):
    for tpl in rules.get("templates", []):
        if all(rxc(s, tpl.get("cs")).search(text) for s in tpl["match"]) and not any(
                rxc(s, tpl.get("cs")).search(text) for s in tpl.get("notMatch", [])):
            return tpl
    return None


def run_template(text, tpl, rules):
    if tpl.get("collapseBlank"):
        text = re.sub(r"\n[ \t]*(?=\n)", "", text)
    regions = {"all": text}
    if tpl.get("columns"):
        cols = split_columns(text, tpl["columns"])
        if cols:
            regions.update(cols)
    r, found = {}, set()
    for op in tpl["ops"]:
        t = regions.get(op.get("in", "all"), "")
        if not t:
            continue
        if "charges" in op:
            ch = tpl_charges(t, op, rules)
            kinds = (rules["companies"].get(tpl["company"], {}).get("charges") or rules["generic"]["charges"])["kinds"]
            for c in ch:
                c["kind"] = next((k for k, x in kinds if rx(x).search(c["label"])), "other")
                if c["amount"] < 0:
                    c["kind"] = "discount"
            if ch and not r.get("charges"):
                r["charges"] = ch
                found.add("charges")
            continue
        if "stop" in op:
            for k, v in tpl_stop(t.split("\n"), op, rules).items():
                tpl_put(r, found, op["stop"] + "." + k, v)
            continue
        m = rxc(op["re"], op.get("cs")).search(t)
        if not m:
            continue
        if "vehicle" in op:
            g = op["vehicle"]
            tpl_vehicle(r, found, tpl_group(m, g["year"]) if "year" in g else None,
                        tpl_group(m, g["make"]) if "make" in g else None,
                        tpl_group(m, g["model"]) if "model" in g else None, rules)
            continue
        for path, spec in op["set"].items():
            g, typ = (spec, "str") if isinstance(spec, int) else (spec[0], spec[1])
            raw = tpl_group(m, g)
            if raw is None or (op.get("reject") and rxc(op["reject"]).search(raw)):
                continue
            tpl_put(r, found, path, tpl_value(raw, typ, rules))
    r["_template"] = tpl["id"]
    return r, found


# ------------------------------------------------------------------ main

def detect_company(text, rules):
    t = text
    for ig in rules["detectIgnore"]:
        t = rx(ig).sub(" ", t)
    best, best_score = None, 0
    for cid, c in rules["companies"].items():
        score = sum(min(len(rx(d["re"]).findall(t)), 5) * d.get("w", 1) for d in c["detect"])
        if score > best_score:
            best, best_score = cid, score
    return (best or "other"), best_score


_DOLLAR = re.compile(r"\$(\d)")


def apply_preprocess(text, items):
    """Rewrite rules ({re, to} with $1..$9) that normalise odd layouts before matching."""
    for p in items or []:
        to = p["to"]
        text = rx(p["re"]).sub(lambda m, to=to: _DOLLAR.sub(lambda d: m.group(int(d.group(1))) or "", to), text)
    return text


DATE_JOIN = re.compile(r"^((?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day,[ \t]+[A-Za-z]+[ \t]+\d{1,2}),[ \t]*\n([^\n]*)\n(\d{4})[ \t]*$", re.M)
CHUNK = re.compile(r"\S+(?: \S+)*")


def extract_columns(text, specs):
    """Cut multi-column PDF layouts into labelled sections (mirror of engine.js extractColumns)."""
    extra = ""
    for sp in specs or []:
        m = rx(sp["header"]).search(text)
        if not m:
            continue
        ls = text.rfind("\n", 0, m.start()) + 1
        le = text.find("\n", m.start())
        if le < 0:
            le = len(text)
        hline = text[ls:le]
        pos = []
        for c in sp["cols"]:
            mm = rx(c["at"]).search(hline)
            pos.append(mm.start() if mm else -1)
        if any(p < 0 for p in pos):
            continue
        buckets = [[] for _ in sp["cols"]]
        for line in text[le + 1:].split("\n")[:sp.get("take", 12)]:
            row = [[] for _ in sp["cols"]]
            for cm in CHUNK.finditer(line):
                k = -1
                for i, p in enumerate(pos):
                    if cm.start() >= p - 3:
                        k = i
                if k >= 0:
                    row[k].append(cm.group(0))
            for i, r in enumerate(row):
                if r:
                    buckets[i].append(" ".join(r))
        for i, c in enumerate(sp["cols"]):
            body = "\n".join(buckets[i])
            if c.get("after"):
                am = rx(c["after"]).search(body)
                if am:
                    body = body[am.end():]
            body = DATE_JOIN.sub(r"\1, \3 \2", body.strip())
            if body:
                extra += "\n\n" + c["name"] + ":\n" + body + "\n"
    return text + extra if extra else text


def parse_text(text, rules):
    tpl = match_template(text, rules)
    if tpl:
        r, found = run_template(text, tpl, rules)
        return {"rental": finalize(r, tpl["company"], rules), "company": tpl["company"], "score": 100, "found": found,
                "template": tpl["id"]}
    text = apply_preprocess(text, rules.get("preprocess"))
    company, score = detect_company(text, rules)
    crules = rules["companies"].get(company, {"fields": {}})
    text = apply_preprocess(text, crules.get("preprocess"))
    text = extract_columns(text, crules.get("columns"))
    r: dict = {}
    found = set()
    names = list(dict.fromkeys(list(crules.get("fields", {}).keys()) + list(rules["generic"]["fields"].keys())))
    for field in names:
        if get_path(r, field) is not None:
            continue
        pats = crules.get("fields", {}).get(field, []) + rules["generic"]["fields"].get(field, [])
        for p in pats:
            p = {"re": p} if isinstance(p, str) else p
            m = rx(p["re"]).search(text)
            if not m:
                continue
            groups = p.get("groups") or {field: p.get("group", 1)}
            ok = False
            for path, gi in groups.items():
                if m.group(gi) is None or get_path(r, path) is not None:
                    continue
                v = convert(path, m.group(gi), rules)
                if v is None or v == "":
                    continue
                set_path(r, path, v)
                found.add(path)
                ok = True
            if ok:
                for path, v in p.get("set", {}).items():
                    set_path(r, path, v)
                    found.add(path)
                break
    for which in ("pickup", "return"):
        b = extract_block(text, crules.get("blocks", {}).get(which) or rules["generic"]["blocks"][which], rules)
        if b:
            for k, v in b.items():
                if get_path(r, which + "." + k) is None:
                    set_path(r, which + "." + k, v)
                    found.add(which + "." + k)
    charges = extract_charges(text, crules.get("charges") or rules["generic"]["charges"])
    if charges:
        r["charges"] = charges
        found.add("charges")
    return {"rental": finalize(r, company, rules), "company": company, "score": score, "found": found, "template": ""}


def compute_days(a, b):
    def t(s):
        d, _, tm = s.partition("T")
        tm = tm or "12:00"
        y, mo, dd = map(int, d.split("-"))
        h, mi = map(int, tm.split(":"))
        return _dt.datetime(y, mo, dd, h, mi)
    mins = (t(b) - t(a)).total_seconds() / 60
    if not mins > 0:
        return None
    return max(1, math.ceil((mins - 29) / 1440))


def finalize(r, company, rules):
    v = r.get("vehicle", {})
    for k in ("description", "class"):
        if v.get(k) and any(rx(j).search(v[k]) for j in rules.get("vehicleJunk", [])):
            del v[k]
    if r.get("_template"):  # template values are already label-exact; never re-split them
        veh = {k: v[k] for k in ("year", "make", "model") if v.get(k) is not None}
        desc = " ".join(str(veh[k]) for k in ("year", "make", "model") if k in veh)
        if veh.get("make") or veh.get("model"):
            veh["description"] = desc
        v = {k: x for k, x in v.items() if k not in ("year", "make", "model", "description")}
    else:
        veh = split_vehicle(expand_vehicle_codes(v.get("description"), rules), rules)
    if veh.get("year") is None and v.get("year") is not None:
        veh["year"] = v["year"] + 2000 if v["year"] < 100 else v["year"]
    if v.get("classCode"):
        veh["classCode"] = v["classCode"].upper()
    if v.get("color"):
        veh["color"] = title_case(v["color"])
    if v.get("class"):
        cm = re.match(r"^([A-Z]{1,4})[ \t]*[-–:][ \t]*(.+)$", v["class"], re.I)
        if cm:
            veh["classCode"], veh["class"] = cm.group(1).upper(), cm.group(2).strip()
        else:
            veh["class"] = v["class"]
    if v.get("plate"):
        veh["plate"] = v["plate"].upper()
    if v.get("plateState"):
        veh["plateState"] = v["plateState"].upper()
    pay = r.get("payment", {})
    if pay.get("cardBrand"):
        pay["cardBrand"] = next((name for pat, name in BRANDS if re.search(pat, pay["cardBrand"], re.I)), pay["cardBrand"])
    days = r.get("days")
    if days is None and get_path(r, "pickup.datetime") and get_path(r, "return.datetime"):
        days = compute_days(r["pickup"]["datetime"], r["return"]["datetime"])
    daily = r.get("dailyRate")
    if daily is None and r.get("weeklyRate") is not None:
        daily = round2(r["weeklyRate"] / 7)
    mil = r.get("mileage", {})
    mileage = {"out": mil.get("out"), "in": mil.get("in")}
    if mil.get("driven") is not None:
        mileage["driven"] = mil["driven"]
    elif mileage["out"] is not None and mileage["in"] is not None and mileage["in"] >= mileage["out"]:
        mileage["driven"] = mileage["in"] - mileage["out"]
    blank = {"location": "", "address": "", "city": "", "code": "", "datetime": ""}
    return {
        "company": company,
        "template": r.get("_template") or "",
        "renter": r.get("renter") or "",
        "confirmation": r.get("confirmation") or "",
        "agreement": r.get("agreement") or "",
        "pickup": {**blank, **r.get("pickup", {})},
        "return": {**blank, **r.get("return", {})},
        "vehicle": veh,
        "mileage": mileage,
        "fuel": {"out": get_path(r, "fuel.out") or "", "in": get_path(r, "fuel.in") or ""},
        "days": days,
        "dailyRate": daily,
        "currency": (r.get("currency") or "USD").upper(),
        "charges": r.get("charges", []),
        "total": r.get("total"),
        "payment": {"cardBrand": pay.get("cardBrand") or "", "cardLast4": pay.get("cardLast4") or "",
                    "amountCharged": pay.get("amountCharged")},
        "loyalty": {"program": get_path(r, "loyalty.program") or "", "number": get_path(r, "loyalty.number") or ""},
        "notes": "",
    }


def missing_fields(rental, rules):
    miss = [p for p in rules["required"] if get_path(rental, p) in (None, "")]
    if not rental["confirmation"] and not rental["agreement"]:
        miss.insert(0, "confirmation")
    if rental["company"] == "other":
        miss.insert(0, "company")
    return miss


def parse_receipt(data: bytes, rules, filename=""):
    best = None
    for c in extract_candidates(data, filename):
        res = parse_text(c["text"], rules)
        missing = missing_fields(res["rental"], rules)
        quality = len(res["found"]) - len(missing) * 2 + (1000 if res["template"] else 0)
        if best is None or quality > best["quality"]:
            best = dict(res, missing=missing, quality=quality, text=c["text"], subject=c["subject"], kind=c["kind"])
    return {"rental": best["rental"], "company": best["company"], "score": best["score"], "missing": best["missing"],
            "found": sorted(best["found"]), "template": best["template"], "text": best["text"], "subject": best["subject"], "kind": best["kind"],
            "filename": filename, "sample": bool(rx(rules["sampleMarker"]).search(best["text"]))}


def fnv1a(s: str) -> str:
    h = 0x811C9DC5
    for b in s.encode("utf-8"):
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
    return "%08x" % h


def rental_id(r) -> str:
    key = "|".join([r.get("company") or "", (r.get("confirmation") or "").upper(),
                    (r.get("agreement") or "").upper(), get_path(r, "pickup.datetime") or ""])
    return "r_" + fnv1a(key)


# ------------------------------------------------------------------ CLI

def iter_files(paths, recursive):
    for p in paths:
        if os.path.isdir(p):
            if recursive:
                for root, _dirs, files in os.walk(p):
                    for f in sorted(files):
                        if f.lower().endswith(EXTS):
                            yield os.path.join(root, f)
            else:
                for f in sorted(os.listdir(p)):
                    if f.lower().endswith(EXTS) and os.path.isfile(os.path.join(p, f)):
                        yield os.path.join(p, f)
        elif os.path.isfile(p):
            yield p
        else:
            print("skip (not found): %s" % p, file=sys.stderr)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Parse rental-car receipts into Rental Car Tracker JSON.")
    ap.add_argument("inputs", nargs="+", help="receipt files or folders (.pdf .eml .txt .html)")
    ap.add_argument("-o", "--output", default="rentals-import.json", help="output JSON (use - for stdout)")
    ap.add_argument("-r", "--recursive", action="store_true", help="walk sub-folders")
    ap.add_argument("--rules", default=DEFAULT_RULES, help="path to rules.json (default: the app's copy)")
    ap.add_argument("--dump-text", action="store_true", help="print the extracted text of each file and exit")
    ap.add_argument("--skip-samples", action="store_true", help="drop receipts marked as SAMPLE / fictional")
    args = ap.parse_args(argv)

    with open(args.rules, encoding="utf-8") as fh:
        rules = json.load(fh)
    now = _dt.datetime.now().astimezone().isoformat(timespec="seconds")
    rentals, seen, problems = [], set(), 0
    for path in iter_files(args.inputs, args.recursive):
        try:
            with open(path, "rb") as fh:
                data = fh.read()
            res = parse_receipt(data, rules, path)
        except Exception as e:  # keep going on bad files
            problems += 1
            print("ERROR  %s: %s" % (path, e), file=sys.stderr)
            continue
        if args.dump_text:
            print("=" * 20, path, "=" * 20)
            print(res["text"])
            continue
        if args.skip_samples and res["sample"]:
            continue
        r = res["rental"]
        r["id"] = rental_id(r)
        if r["id"] in seen:
            print("dup    %s (same rental as an earlier file)" % path, file=sys.stderr)
            continue
        seen.add(r["id"])
        r["sample"] = res["sample"]
        r["source"] = {"type": "receipt", "parser": res["company"], "file": os.path.basename(path), "subject": res["subject"],
                       "importedAt": now, "importer": "import_receipts.py", "missing": res["missing"]}
        r["createdAt"] = r["updatedAt"] = now
        rentals.append(r)
        flag = "OK    " if not res["missing"] else "REVIEW"
        print("%s %-10s %-14s %s%s" % (flag, res["company"], r["confirmation"] or r["agreement"] or "?", os.path.basename(path),
                                       ("  missing: " + ", ".join(res["missing"])) if res["missing"] else ""), file=sys.stderr)
    if args.dump_text:
        return 0
    doc = {"format": "rental-car-tracker", "version": 1, "exportedAt": now, "rentals": rentals}
    out = json.dumps(doc, indent=2, ensure_ascii=False)
    if args.output == "-":
        print(out)
    else:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(out + "\n")
        print("wrote %d rental(s) to %s" % (len(rentals), args.output), file=sys.stderr)
    return 1 if problems and not rentals else 0


if __name__ == "__main__":
    sys.exit(main())
