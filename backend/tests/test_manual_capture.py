"""Manual PDF capture: no ATS API, so the source is the extracted text itself."""

import pytest

from app import db
from app.manual_capture_service import extract_text, store_manual_pdf
from app.models import Job, JobNormalized
from app.normalizer import NormalizedJob, NormalizerResult


@pytest.fixture
def fresh_db(tmp_path):
    db.reset_for_tests(tmp_path / "test.db")
    yield
    db.reset_for_tests(tmp_path / "unused.db")


class FakePage:
    def __init__(self, text):
        self._text = text

    def extract_text(self):
        return self._text


class FakeReader:
    def __init__(self, pdf_bytes):
        self.pages = [FakePage("Page one"), FakePage(None), FakePage("Page two")]


def test_extract_text_joins_pages_and_skips_ones_with_none(monkeypatch):
    import app.manual_capture_service as svc

    monkeypatch.setattr(svc, "PdfReader", FakeReader)
    assert extract_text(b"whatever") == "Page one\n\nPage two"


def test_empty_pdf_text_raises_without_storing_a_row(fresh_db, monkeypatch):
    import app.manual_capture_service as svc

    monkeypatch.setattr(svc, "extract_text", lambda pdf_bytes: "")

    with pytest.raises(ValueError):
        store_manual_pdf("Acme", "Engineer", b"whatever")

    with db.session_scope() as session:
        assert session.query(Job).count() == 0


def test_successful_upload_stores_as_manual_and_normalizes(fresh_db, monkeypatch):
    import app.jobs_service as jobs_service
    import app.manual_capture_service as svc

    monkeypatch.setattr(svc, "extract_text", lambda pdf_bytes: "Responsibilities: ship things.")
    monkeypatch.setattr(
        jobs_service,
        "normalize",
        lambda *a, **k: NormalizerResult(
            normalized=NormalizedJob(responsibilities=["ship things"]),
            model="fake-model",
            prompt_version="v1",
        ),
    )

    report = store_manual_pdf("Google", "Product Data Scientist", b"whatever", url="https://example.com")

    assert len(report.stored) == 1
    assert len(report.normalized) == 1

    with db.session_scope() as session:
        job = session.query(Job).one()
        assert job.source == "manual"
        assert job.company == "Google"
        assert job.title == "Product Data Scientist"
        assert job.description_raw == "Responsibilities: ship things."
        assert job.url == "https://example.com"

        normalized = session.query(JobNormalized).one()
        assert normalized.source == "manual"
        assert normalized.job_id == job.job_id
        assert normalized.responsibilities == ["ship things"]
