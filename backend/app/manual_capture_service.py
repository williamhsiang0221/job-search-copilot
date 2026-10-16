"""Manual capture: a posting found off-platform (a company's own careers
site) with no ATS API to fetch from, saved locally as a PDF instead.

There is no id to resolve here — the user supplies title/company by hand and
the description comes from the PDF's text, rather than a source's `fetch(id)`
looking it up. Once that's assembled into a FetchedJob, it goes through the
exact same store-then-normalize path as every other source, via a one-off
JobDescriptionSource that just hands back what is already in hand.
"""

from __future__ import annotations

import uuid
from io import BytesIO

from pypdf import PdfReader

from app.jd_sources import FetchedJob
from app.jobs_service import FetchReport, fetch_and_store

SOURCE = "manual"


class _AlreadyFetched:
    name = SOURCE

    def __init__(self, fetched: FetchedJob):
        self._fetched = fetched

    def fetch(self, job_id: str) -> FetchedJob:
        return self._fetched


def extract_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages).strip()


def store_manual_pdf(company: str, title: str, pdf_bytes: bytes, url: str = "") -> FetchReport:
    description = extract_text(pdf_bytes)
    if not description:
        raise ValueError("could not extract any text from this PDF")

    job_id = uuid.uuid4().hex[:16]
    fetched = FetchedJob(
        source=SOURCE,
        job_id=job_id,
        title=title,
        company=company,
        url=url,
        description_raw=description,
    )
    return fetch_and_store(
        [job_id], source=_AlreadyFetched(fetched), skip_existing=False, delay_seconds=0
    )
