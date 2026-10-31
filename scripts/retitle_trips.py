"""Bring auto-generated trip titles up to date with each trip's full route.

    python scripts/retitle_trips.py --dry-run          # print what would change
    python scripts/retitle_trips.py --log old.json     # apply, saving the old titles
    python scripts/retitle_trips.py --revert old.json  # put the saved titles back
    python scripts/retitle_trips.py --revert /data/title-changes.jsonl  # undo retitles the app made on read

Only trips with title_auto set are touched (… (auto) / (flights) / (email) titles the user never
renamed). The app does the same on every trip read, so this is for a controlled first pass.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models, titles  # noqa: E402
from app.database import SessionLocal  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--log", help="write [{id, old, new}] here before applying")
    ap.add_argument("--revert", help="restore titles from a --log file")
    a = ap.parse_args()
    db = SessionLocal()
    if a.revert:
        text = Path(a.revert).read_text()
        rows = [json.loads(l) for l in text.splitlines() if l.strip()] if a.revert.endswith(".jsonl") else json.loads(text)
        for r in reversed(rows):  # newest first, so chained renames unwind
            t = db.get(models.Trip, r["id"])
            if t is not None and t.title == r["new"]:
                t.title = r["old"]
        db.commit()
        print(f"checked {len(rows)} change(s); titles still matching were restored")
        return
    trips = db.query(models.Trip).filter(models.Trip.title_auto == True).order_by(models.Trip.id).all()  # noqa: E712
    changes = titles.refresh(db, trips, commit=False)
    for tid, old, new in changes:
        print(f"{tid}: {old!r} -> {new!r}")
    if a.dry_run:
        db.rollback()
        print(f"{len(changes)} title(s) would change (dry run)")
        return
    if a.log:
        Path(a.log).write_text(json.dumps([{"id": i, "old": o, "new": n} for i, o, n in changes], indent=1))
    db.commit()
    titles.journal(db, changes)
    print(f"{len(changes)} title(s) changed")


if __name__ == "__main__":
    main()
