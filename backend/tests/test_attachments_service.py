"""The merged worklist: applications missing a JD, a resume, or both."""

import pytest

from app import db
from app.attachments_service import applications_needing_attachments
from app.models import Application, Resume


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


def test_excludes_applications_with_both_a_jd_and_a_resume(fresh_db):
    complete = _add_application(job_id="123", source="linkedin")
    with db.session_scope() as session:
        session.add(Resume(id="r1", filename="r1.pdf", company="Acme", title="Engineer", application_id=complete))

    ids = {a["id"] for a in applications_needing_attachments()}
    assert complete not in ids


def test_flags_missing_jd_and_missing_resume_independently(fresh_db):
    missing_both = _add_application(company="Globex")
    # Has a JD but no resume yet.
    missing_resume_only = _add_application(company="Initech", job_id="1", source="linkedin")
    # Has a resume but no JD.
    missing_jd_only = _add_application(company="Hooli")
    with db.session_scope() as session:
        session.add(
            Resume(id="r2", filename="r2.pdf", company="Hooli", title="Engineer", application_id=missing_jd_only)
        )

    by_id = {a["id"]: a for a in applications_needing_attachments()}

    assert by_id[missing_both]["needs_jd"] is True
    assert by_id[missing_both]["needs_resume"] is True

    assert by_id[missing_resume_only]["needs_jd"] is False
    assert by_id[missing_resume_only]["needs_resume"] is True

    assert by_id[missing_jd_only]["needs_jd"] is True
    assert by_id[missing_jd_only]["needs_resume"] is False


def test_missing_only_source_still_counts_as_needing_a_jd(fresh_db):
    missing_source = _add_application(job_id="123", source=None)
    by_id = {a["id"]: a for a in applications_needing_attachments()}
    assert by_id[missing_source]["needs_jd"] is True
