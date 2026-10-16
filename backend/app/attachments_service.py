"""Combined worklist: applications missing a JD, a resume, or both.

Used to be two separate one-time backfill tabs (Link legacy JDs, Upload
Resumes) with two separate lists. Merged because the two gaps overlap on
many rows — most legacy applications are missing both — and checking the
same application twice across two tabs was pure friction. The two attach
actions themselves (attach_pdf_to_application, attach_resume_to_application)
stay in their own modules unchanged; only the listing is merged.
"""

from __future__ import annotations

from sqlalchemy import select

from app.db import session_scope
from app.models import Application, Resume


def _iso(value):
    return value.isoformat() if value else None


def applications_needing_attachments() -> list[dict]:
    """Applications missing a JD link, a resume, or both. Newest-applied
    first, same ordering as the two worklists this replaces."""
    with session_scope() as session:
        linked_resume_ids = set(
            session.scalars(select(Resume.application_id).where(Resume.application_id.is_not(None)))
        )
        rows = (
            session.query(Application)
            .filter(
                (Application.job_id.is_(None))
                | (Application.source.is_(None))
                | (~Application.id.in_(linked_resume_ids))
            )
            .order_by(Application.applied_at.desc())
            .all()
        )
        return [
            {
                "id": a.id,
                "company": a.company,
                "title": a.title,
                "applied_at": _iso(a.applied_at),
                "needs_jd": a.job_id is None or a.source is None,
                "needs_resume": a.id not in linked_resume_ids,
            }
            for a in rows
        ]
