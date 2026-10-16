"""Linking a legacy application to a JD PDF — the one-time backfill tool."""

import pytest

from app import db
from app.jd_linking_service import attach_pdf_to_application
from app.models import Application, Job
from app.normalizer import NormalizedJob, NormalizerResult


@pytest.fixture
def fresh_db(tmp_path):
    db.reset_for_tests(tmp_path / "test.db")
    yield
    db.reset_for_tests(tmp_path / "unused.db")


def _add_application(company="Acme", title="Engineer", job_id=None, source=None) -> int:
    with db.session_scope() as session:
        app = Application(company=company, title=title, job_id=job_id, source=source)
        session.add(app)
        session.flush()
        return app.id


def test_attach_pdf_links_the_application_to_the_new_job(fresh_db, monkeypatch):
    import app.jobs_service as jobs_service
    import app.manual_capture_service as manual_capture_service

    monkeypatch.setattr(manual_capture_service, "extract_text", lambda pdf_bytes: "Responsibilities: ship things.")
    monkeypatch.setattr(
        jobs_service,
        "normalize",
        lambda *a, **k: NormalizerResult(
            normalized=NormalizedJob(responsibilities=["ship things"]), model="fake-model"
        ),
    )

    app_id = _add_application(company="Google", title="PM")

    report = attach_pdf_to_application(app_id, b"whatever")

    assert len(report.stored) == 1

    with db.session_scope() as session:
        app = session.get(Application, app_id)
        assert app.source == "manual"
        assert app.job_id == report.stored[0]
        job = session.query(Job).one()
        assert job.job_id == app.job_id
        assert job.company == "Google"


def test_missing_application_id_raises_without_storing_anything(fresh_db):
    with pytest.raises(ValueError):
        attach_pdf_to_application(999, b"whatever")

    with db.session_scope() as session:
        assert session.query(Job).count() == 0


def test_a_pdf_with_no_extractable_text_leaves_the_application_unlinked(fresh_db, monkeypatch):
    import app.manual_capture_service as manual_capture_service

    monkeypatch.setattr(manual_capture_service, "extract_text", lambda pdf_bytes: "")

    app_id = _add_application()

    with pytest.raises(ValueError):
        attach_pdf_to_application(app_id, b"whatever")

    with db.session_scope() as session:
        app = session.get(Application, app_id)
        assert app.job_id is None
        assert app.source is None
