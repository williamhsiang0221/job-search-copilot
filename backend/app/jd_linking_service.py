"""One-time backfill tool: attach a JD PDF to a legacy application.

Most of the 162 imported applications predate this app and have no job_id/
source link at all, so there is no stored posting to normalize, evaluate, or
compare for JD lookalike scoring. For the ones the user still has the
original posting saved as a PDF, this reuses the existing manual-PDF path
(store_manual_pdf) unchanged, then points the application at the result.

Deliberately its own module rather than folded into applications_service.py
or manual_capture_service.py: this is a narrow, occasional task (work through
a backlog of old applications, then rarely touch it again), and keeping it
separate means it can be read, changed, or deleted later without touching
either of those two already-working services.

The worklist this fed (unlinked_applications) has since been merged with
resume_ingest_service.py's applications_without_resume into
attachments_service.applications_needing_attachments — the action here
stays put, only the listing moved.
"""

from __future__ import annotations

from app.db import session_scope
from app.jobs_service import FetchReport
from app.manual_capture_service import SOURCE, store_manual_pdf
from app.models import Application


def attach_pdf_to_application(application_id: int, pdf_bytes: bytes) -> FetchReport:
    """Stores and normalizes the PDF exactly as the standalone PDF Upload
    page does, then links the application to the resulting job — only if
    something was actually stored, so a bad PDF never half-links a row."""
    with session_scope() as session:
        application = session.get(Application, application_id)
        if application is None:
            raise ValueError(f"no application with id {application_id}")
        company, title = application.company, application.title

    report = store_manual_pdf(company, title, pdf_bytes)

    if report.stored:
        job_id = report.stored[0]
        with session_scope() as session:
            application = session.get(Application, application_id)
            application.job_id = job_id
            application.source = SOURCE

    return report
