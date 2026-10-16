"""Evaluation batch orchestration — evaluate_jobs's skip/failure/progress plumbing.

Scoring itself (the rubric arithmetic) is covered in test_evaluator.py; this
file is about the loop around it, the same way test_job_descriptions.py covers
fetch_and_store's loop rather than parsing.
"""

import pytest

from app import db
from app.evaluator import EvaluationResult
from app.evaluations_service import evaluate_jobs
from app.models import Evaluation, Job, JobNormalized


@pytest.fixture
def fresh_db(tmp_path):
    db.reset_for_tests(tmp_path / "test.db")
    yield
    db.reset_for_tests(tmp_path / "unused.db")


def _add_normalized(source: str, job_id: str) -> None:
    with db.session_scope() as session:
        session.add(Job(source=source, job_id=job_id, title="T", company="C"))
        session.add(JobNormalized(source=source, job_id=job_id, title="T", company="C"))


def _fake_result(**overrides) -> EvaluationResult:
    defaults = dict(
        score_1=3.0,
        score_2=3.0,
        verdict="MAYBE",
        disqualifier=None,
        reasoning="fake",
        model="test-model",
        rubric_version="v1",
    )
    defaults.update(overrides)
    return EvaluationResult(**defaults)


def test_on_progress_fires_for_evaluated_and_failed_ids(fresh_db, monkeypatch):
    import app.evaluations_service as service

    _add_normalized("linkedin", "a")
    _add_normalized("linkedin", "b")  # "b" has no normalized row -> failure below

    with db.session_scope() as session:
        session.query(JobNormalized).filter(JobNormalized.job_id == "b").delete()

    monkeypatch.setattr(service, "evaluate", lambda *a, **k: _fake_result())

    seen = []
    evaluate_jobs(["a", "b"], source="linkedin", rubric_version="v1", delay_seconds=0, on_progress=seen.append)

    assert set(seen) == {"a", "b"}


def test_on_progress_reports_skipped_ids_immediately(fresh_db, monkeypatch):
    """A skipped id resolves without a model call, so it needs its own
    progress signal — otherwise an all-skipped batch would leave a caller's
    progress bar stuck at 0."""
    import app.evaluations_service as service

    _add_normalized("linkedin", "a")
    with db.session_scope() as session:
        session.add(
            Evaluation(
                source="linkedin",
                job_id="a",
                rubric_version="v1",
                verdict="MAYBE",
                reasoning="",
                model="test-model",
            )
        )

    monkeypatch.setattr(
        service, "evaluate", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should be skipped"))
    )

    seen = []
    evaluate_jobs(["a"], source="linkedin", rubric_version="v1", delay_seconds=0, on_progress=seen.append)

    assert seen == ["a"]


def _add_evaluation(job_id: str = "a") -> int:
    _add_normalized("linkedin", job_id)
    with db.session_scope() as session:
        row = Evaluation(source="linkedin", job_id=job_id, rubric_version="v2", verdict="SKIP", reasoning="", model="m")
        session.add(row)
        session.flush()
        return row.id


def test_a_note_is_saved_on_the_evaluation_and_listed_with_it(fresh_db):
    from app.evaluations_service import list_evaluations, set_evaluation_note

    evaluation_id = _add_evaluation()
    saved = set_evaluation_note(evaluation_id, "  Applied anyway: the team is B2C growth.  ")

    assert saved["note"] == "Applied anyway: the team is B2C growth."
    assert saved["note_updated_at"] is not None
    listed = list_evaluations()[0]
    assert listed["note"] == "Applied anyway: the team is B2C growth."
    assert listed["note_updated_at"] == saved["note_updated_at"]


def test_blank_text_clears_a_note(fresh_db):
    from app.evaluations_service import set_evaluation_note

    evaluation_id = _add_evaluation()
    set_evaluation_note(evaluation_id, "first thought")
    cleared = set_evaluation_note(evaluation_id, "   ")

    assert cleared == {"id": evaluation_id, "note": None, "note_updated_at": None}


def test_a_note_on_a_missing_evaluation_is_none(fresh_db):
    from app.evaluations_service import set_evaluation_note

    assert set_evaluation_note(999, "anything") is None
