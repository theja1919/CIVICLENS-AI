#!/usr/bin/env python
"""
seed_data.py — Insert fictional sample reports for demo purposes.

Rules
-----
- Never deletes or modifies existing user reports.
- Only inserts a sample if a report with that exact description does not
  already exist (idempotent — safe to run multiple times).
- All data is clearly fictional.
- Does NOT claim AI image recognition, external API calls, or government
  notification actually occurred.

Usage
-----
    python seed_data.py                 # insert samples that are missing
    python seed_data.py --status        # show current DB counts and exit
    python seed_data.py --dry-run       # print what would be inserted

Disclaimer
----------
The rule-based classifier assigns categories and priority scores based on
keywords in the description text only. It is NOT AI image recognition and
does NOT automatically notify any government department.
"""

from __future__ import annotations

import argparse
import sys
import os

# Must set DATABASE_URL before importing the ORM
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./civiclens.db")
os.environ.setdefault("DATABASE_URL", DATABASE_URL)

from backend.database import create_tables, SessionLocal, Report  # noqa: E402
from backend.classifier import classify                            # noqa: E402
from backend.priority import compute_priority                     # noqa: E402
import json
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Fictional sample data
# ---------------------------------------------------------------------------

SAMPLES = [
    {
        "category": "pothole",
        "description": (
            "Large pothole approximately 40 cm wide on the corner of Elm Street "
            "and Oak Avenue. Several cyclists have had to swerve dangerously to "
            "avoid it. The road surface is crumbling around the edges."
        ),
        "latitude": 51.5074,
        "longitude": -0.1278,
        "status": "submitted",
    },
    {
        "category": "garbage",
        "description": (
            "Overflowing rubbish bins at the entrance to Riverside Park. "
            "The bins have not been emptied for at least two weeks. Bags of "
            "waste are piling up on the pavement and attracting birds and rodents."
        ),
        "latitude": 51.5080,
        "longitude": -0.1265,
        "status": "assigned",
    },
    {
        "category": "broken_streetlight",
        "description": (
            "Street lamp outside 42 Maple Road has been flickering and going "
            "dark completely every night for the past week. The area is poorly "
            "lit and residents are concerned about pedestrian safety after dark."
        ),
        "latitude": 51.5060,
        "longitude": -0.1290,
        "status": "in_progress",
    },
    {
        "category": "water_leak",
        "description": (
            "Urgent: burst water main on Station Road near the post office. "
            "Water is flooding the pavement and running into the road creating "
            "a hazardous situation for vehicles and pedestrians. Immediate "
            "attention is required as the water level is rising."
        ),
        "latitude": 51.5090,
        "longitude": -0.1250,
        "status": "submitted",
    },
    {
        "category": "pothole",
        "description": (
            "Deep pothole on the northbound lane of High Street just before "
            "the pedestrian crossing. Multiple vehicles have suffered tyre "
            "damage. The pothole is approximately 30 cm deep and is difficult "
            "to see at night or in wet conditions."
        ),
        "latitude": 51.5055,
        "longitude": -0.1302,
        "status": "resolved",
        "resolution_note": (
            "Pothole filled with cold-mix asphalt on 10 Oct 2026. "
            "Area will be inspected again in 30 days for permanent patching."
        ),
    },
    {
        "category": "other",
        "description": (
            "Graffiti covering the entire front wall of the community centre "
            "on Church Lane. The vandalism appeared overnight and the language "
            "used is offensive. The centre director has requested urgent removal."
        ),
        "latitude": 51.5068,
        "longitude": -0.1275,
        "status": "submitted",
    },
    {
        "category": "garbage",
        "description": (
            "Large mattress and several bin bags of household waste dumped on "
            "the pavement outside the car park on Market Street. This is "
            "blocking a dropped kerb used by wheelchair users and pushchairs."
        ),
        "latitude": None,
        "longitude": None,
        "status": "assigned",
    },
    {
        "category": "broken_streetlight",
        "description": (
            "Two consecutive street lamps on the bridge over the canal are "
            "completely dark. Joggers and cyclists use this route regularly "
            "after dark and the lack of lighting is a significant safety risk."
        ),
        "latitude": 51.5100,
        "longitude": -0.1240,
        "status": "submitted",
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_report(sample: dict) -> Report:
    """Classify, score, and build a Report ORM object (not yet committed)."""
    clf = classify(sample["category"], sample["description"])
    priority = compute_priority(
        sample["category"],
        sample["description"],
        latitude=sample.get("latitude"),
        longitude=sample.get("longitude"),
    )
    breakdown = {
        "factors": [
            {"name": f.name, "value": f.value, "description": f.description}
            for f in priority.factors
        ],
        "disclaimer": (
            "This score is a prototype estimate based on report text and "
            "metadata only. It is NOT an official risk assessment and does "
            "not reflect government surveys or accident records."
        ),
    }
    now = datetime.now(timezone.utc)
    r = Report(
        category=sample["category"],
        description=sample["description"],
        latitude=sample.get("latitude"),
        longitude=sample.get("longitude"),
        status=sample.get("status", "submitted"),
        priority_score=priority.total,
        classifier_suggestion=clf.suggestion,
        priority_breakdown=json.dumps(breakdown),
        created_at=now,
        updated_at=now,
    )
    if sample.get("status") == "resolved":
        r.resolved_at = now
        r.resolution_note = sample.get("resolution_note")
    return r


def _description_exists(db, description: str) -> bool:
    return (
        db.query(Report).filter(Report.description == description).first() is not None
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Insert fictional demo reports into CivicLens AI."
    )
    parser.add_argument("--status", action="store_true",
                        help="Show current report counts and exit.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be inserted without writing to DB.")
    args = parser.parse_args()

    create_tables()
    db = SessionLocal()

    try:
        total = db.query(Report).count()
        print(f"CivicLens AI — current report count: {total}")

        if args.status:
            from sqlalchemy import func
            rows = db.query(Report.status, func.count()).group_by(Report.status).all()
            for status, count in rows:
                print(f"  {status:<15} {count}")
            return

        inserted = 0
        skipped = 0

        for sample in SAMPLES:
            desc = sample["description"]
            if _description_exists(db, desc):
                skipped += 1
                print(f"  [skip]   Already exists: \"{desc[:60]}…\"")
                continue

            if args.dry_run:
                inserted += 1
                print(f"  [dry-run] Would insert: {sample['category']} / {sample['status']} — \"{desc[:55]}…\"")
                continue

            report = _build_report(sample)
            db.add(report)
            db.commit()
            db.refresh(report)
            inserted += 1
            print(f"  [insert] #{report.id} {report.category} / {report.status} "
                  f"(priority {report.priority_score}) — \"{desc[:50]}…\"")

        action = "Would insert" if args.dry_run else "Inserted"
        print(f"\n{action} {inserted} sample report(s). Skipped {skipped} duplicate(s).")
        print("\nDISCLAIMER: All reports are entirely fictional and are provided for")
        print("demo purposes only. Rule-based classification is NOT AI image")
        print("recognition. No government department is automatically notified.")

    finally:
        db.close()


if __name__ == "__main__":
    main()
