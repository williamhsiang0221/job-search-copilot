"""ICP Resume generation and storage.

Prompt-loading tests mirror normalizer.py's own load_prompt/available_versions
tests. Orchestration tests mirror test_evaluations_service.py's pattern: mock
the model call, exercise the loop/persistence around it.
"""

import pytest

from app import db
from app.models import Job, JobNormalized
from app.resume_service import (
    ExperienceEntry,
    ResumeResult,
    ResumeUnavailable,
    available_versions,
    create_icp_resume,
    list_icp_resumes,
    load_prompt,
    total_resume_cost,
)


def test_v1_exists():
    assert "v1" in available_versions()
    assert "Bullet format" in load_prompt("v1")


def test_unknown_version_raises_resume_unavailable():
    with pytest.raises(ResumeUnavailable):
        load_prompt("v99")


@pytest.fixture
def fresh_db(tmp_path):
    db.reset_for_tests(tmp_path / "test.db")
    yield
    db.reset_for_tests(tmp_path / "unused.db")


def _add_normalized(source: str, job_id: str, company: str = "Acme", title: str = "PM") -> None:
    with db.session_scope() as session:
        session.add(Job(source=source, job_id=job_id, title=title, company=company))
        session.add(JobNormalized(source=source, job_id=job_id, title=title, company=company))


def _fake_result(**overrides) -> ResumeResult:
    defaults = dict(
        experience=[ExperienceEntry(context="Telecom", bullets=["Owned X, lifting Y; via Z"])],
        model="test-model",
        prompt_version="v1",
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.001,
    )
    defaults.update(overrides)
    return ResumeResult(**defaults)


def test_create_icp_resume_persists_a_row(fresh_db, monkeypatch):
    import app.resume_service as service

    _add_normalized("linkedin", "a", company="Notion", title="Senior PM")
    monkeypatch.setattr(service, "generate_icp_resume", lambda *a, **k: _fake_result())

    row = create_icp_resume("linkedin", "a")

    assert row["company"] == "Notion"
    assert row["title"] == "Senior PM"
    assert row["experience"] == [{"context": "Telecom", "bullets": ["Owned X, lifting Y; via Z"]}]
    assert row["cost_usd"] == 0.001
    assert row["id"] is not None


def test_create_icp_resume_raises_when_not_normalized(fresh_db):
    with pytest.raises(ResumeUnavailable, match="not normalized yet"):
        create_icp_resume("linkedin", "does-not-exist")


def test_every_generation_appends_rather_than_replacing(fresh_db, monkeypatch):
    import app.resume_service as service

    _add_normalized("linkedin", "a")
    monkeypatch.setattr(service, "generate_icp_resume", lambda *a, **k: _fake_result())

    create_icp_resume("linkedin", "a")
    create_icp_resume("linkedin", "a")

    assert len(list_icp_resumes()) == 2


def test_list_icp_resumes_is_newest_first(fresh_db, monkeypatch):
    import app.resume_service as service

    _add_normalized("linkedin", "a")
    _add_normalized("linkedin", "b")
    monkeypatch.setattr(service, "generate_icp_resume", lambda *a, **k: _fake_result())

    create_icp_resume("linkedin", "a")
    create_icp_resume("linkedin", "b")

    rows = list_icp_resumes()
    assert [r["job_id"] for r in rows] == ["b", "a"]


def test_total_resume_cost_sums_and_treats_null_as_zero(fresh_db, monkeypatch):
    import app.resume_service as service

    _add_normalized("linkedin", "a")
    _add_normalized("linkedin", "b")

    monkeypatch.setattr(service, "generate_icp_resume", lambda *a, **k: _fake_result(cost_usd=0.002))
    create_icp_resume("linkedin", "a")
    monkeypatch.setattr(service, "generate_icp_resume", lambda *a, **k: _fake_result(cost_usd=None))
    create_icp_resume("linkedin", "b")

    assert total_resume_cost() == 0.002
