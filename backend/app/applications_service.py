"""Applications: importing from Notion, reading, and updating.

The Notion Job Applications database is the historical record; this is a
one-way import, after which the dashboard is the system of record. Two-way sync
is deliberately not attempted — reconciling two writable copies is a class of
bug not worth introducing for a single user.
"""

from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import select

from app.db import session_scope
from app.models import ROLE_CATEGORIES, ROUND_LADDER, Application, JobNormalized

# Notion's Progress values, mapped to a current status.
STATUS_FROM_PROGRESS = {
    "Not Started": "not_started",
    "Applied": "applied",
    "Phone Screen": "applied",
    "Interview": "applied",
    "Offer": "offer",
    "Accepted": "accepted",
    "Rejected": "rejected",
    "Withdrawn": "withdrawn",
}

# What Progress tells us about how far a row actually got.
#
# Rejected and Withdrawn map to None on purpose. Notion's Progress is a
# terminal state, so a rejection that followed a phone screen is
# indistinguishable from one that followed silence. Recording "applied" for
# those would fabricate exactly the undercount this column exists to correct —
# None means unknown, and unknown is the truth until it is backfilled.
ROUND_FROM_PROGRESS = {
    "Not Started": None,
    "Applied": "applied",
    "Phone Screen": "phone_screen",
    "Interview": "interview",
    "Offer": "offer",
    "Accepted": "accepted",
    "Rejected": None,
    "Withdrawn": None,
}


def _parse_date(value: str) -> date | None:
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        return None


def import_from_tsv(path: Path, *, replace: bool = False) -> dict:
    """Load the Notion export. Idempotent on (company, title, applied_at)."""
    rows = list(csv.DictReader(path.open(encoding="utf-8"), delimiter="\t"))

    imported = skipped = 0
    with session_scope() as session:
        if replace:
            session.query(Application).delete()

        for row in rows:
            company = (row.get("company") or "").strip()
            title = (row.get("title") or "").strip()
            applied_at = _parse_date(row.get("applied_at") or "")
            if not company:
                continue

            existing = session.execute(
                select(Application).where(
                    Application.company == company,
                    Application.title == title,
                    Application.applied_at == applied_at,
                )
            ).scalar_one_or_none()
            if existing:
                skipped += 1
                continue

            progress = (row.get("progress") or "").strip()
            session.add(
                Application(
                    company=company,
                    role=(row.get("role") or "").strip() or None,
                    title=title,
                    job_id=(row.get("job_id") or "").strip() or None,
                    applied_at=applied_at,
                    status=STATUS_FROM_PROGRESS.get(progress, "applied"),
                    highest_round=ROUND_FROM_PROGRESS.get(progress),
                    referral=(row.get("referral") or "").strip() or None,
                    salary_range=(row.get("salary_range") or "").strip() or None,
                )
            )
            imported += 1

    return {"imported": imported, "skipped_existing": skipped, "rows_in_file": len(rows)}


def list_applications() -> list[dict]:
    with session_scope() as session:
        rows = session.execute(
            select(Application).order_by(Application.applied_at.desc())
        ).scalars().all()

        return [
            {
                "id": a.id,
                "company": a.company,
                "role": a.role,
                "title": a.title,
                "job_id": a.job_id,
                "applied_at": a.applied_at.isoformat() if a.applied_at else None,
                "status": a.status,
                "highest_round": a.highest_round,
                "referral": a.referral,
                "salary_range": a.salary_range,
            }
            for a in rows
        ]


def update_application(app_id: int, changes: dict) -> dict | None:
    """Update the editable fields of one application."""
    editable = {"status", "highest_round", "referral", "job_id", "role", "applied_at", "company", "title"}

    with session_scope() as session:
        row = session.get(Application, app_id)
        if row is None:
            return None

        for key, value in changes.items():
            if key not in editable:
                continue
            if key == "highest_round" and value not in (None, "", *ROUND_LADDER):
                raise ValueError(f"unknown round: {value}")
            if key == "role" and value not in (None, "", *ROLE_CATEGORIES):
                raise ValueError(f"unknown role: {value}")
            if key == "applied_at":
                parsed = _parse_date(value) if value else None
                if value and parsed is None:
                    raise ValueError(f"unparseable date: {value}")
                setattr(row, key, parsed)
                continue
            if key == "company":
                if not value or not value.strip():
                    raise ValueError("company cannot be blank")
                setattr(row, key, value.strip())
                continue
            if key == "title":
                setattr(row, key, (value or "").strip())
                continue
            setattr(row, key, value or None if key != "status" else value)

        session.flush()
        return {"id": row.id, "status": row.status, "highest_round": row.highest_round}


def apply_from_normalized(job_ids: list[str], source: str) -> dict:
    """Create an application for each normalized job, skipping ones already applied to.

    Role is left unset — it goes through the same manual Needs Backfill flow as
    highest_round, since the 6-bucket category isn't derivable from the posting.
    """
    applied: list[str] = []
    skipped_existing: list[str] = []
    skipped_missing: list[str] = []

    with session_scope() as session:
        for job_id in job_ids:
            existing = session.execute(
                select(Application).where(
                    Application.source == source, Application.job_id == job_id
                )
            ).scalar_one_or_none()
            if existing:
                skipped_existing.append(job_id)
                continue

            normalized = session.get(JobNormalized, (source, job_id))
            if normalized is None:
                skipped_missing.append(job_id)
                continue

            session.add(
                Application(
                    company=normalized.company,
                    title=normalized.title,
                    job_id=job_id,
                    source=source,
                    applied_at=date.today(),
                    status="applied",
                    highest_round="applied",
                )
            )
            applied.append(job_id)

    return {
        "applied": applied,
        "skipped_existing": skipped_existing,
        "skipped_missing": skipped_missing,
    }


def backfill_summary() -> dict:
    """How much of the outcome history is still unknown.

    Every row without a highest_round is one whose real outcome cannot be
    counted, so this is the honest measure of how usable the data is.
    """
    with session_scope() as session:
        rows = session.execute(select(Application)).scalars().all()

        total = len(rows)
        known = sum(1 for a in rows if a.highest_round)
        reached = {
            r: sum(1 for a in rows if a.highest_round == r) for r in ROUND_LADDER
        }
        past_applied = sum(
            1 for a in rows if a.highest_round and a.highest_round != "applied"
        )

        return {
            "total": total,
            "known": known,
            "needs_backfill": total - known,
            "reached_past_applied": past_applied,
            "by_round": reached,
            # Only meaningful once the unknowns are resolved; reported with its
            # own denominator so it is never mistaken for a rate over all rows.
            "response_rate_of_known": round(past_applied / known * 100, 1) if known else None,
        }
