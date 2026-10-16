"""JD lookalike scoring: centering, ranking, and the edge cases around thin
history and missing embeddings."""

import pytest

from app import db
from app.models import Application, Job, JobNormalized
from app.similarity_service import THIN_CATEGORY_THRESHOLD, find_similar_applications


@pytest.fixture
def fresh_db(tmp_path):
    db.reset_for_tests(tmp_path / "similarity.db")
    yield
    db.reset_for_tests(tmp_path / "unused.db")


def _add_job(
    source: str, job_id: str, role: str, resp_vec: list[float], qual_vec: list[float], company: str = "C", **kwargs
) -> None:
    """A stored, normalized job plus the application linking to it."""
    with db.session_scope() as session:
        session.add(Job(source=source, job_id=job_id, title="T", company=company))
        session.add(
            JobNormalized(
                source=source,
                job_id=job_id,
                title="T",
                company=company,
                responsibilities_embedding=resp_vec,
                qualifications_embedding=qual_vec,
            )
        )
        session.add(
            Application(
                company=company,
                title="T",
                role=role,
                job_id=job_id,
                source=source,
                status=kwargs.get("status", "applied"),
                highest_round=kwargs.get("highest_round"),
            )
        )


def test_no_embedding_on_the_query_job_returns_empty(fresh_db):
    with db.session_scope() as session:
        session.add(Job(source="linkedin", job_id="a", title="T", company="C"))
        session.add(JobNormalized(source="linkedin", job_id="a", title="T", company="C"))

    result = find_similar_applications("linkedin", "a")

    assert result == {"responsibilities": [], "qualifications": [], "overall": [], "thin_categories": []}


def test_no_comparable_history_returns_empty(fresh_db):
    with db.session_scope() as session:
        session.add(Job(source="linkedin", job_id="a", title="T", company="C"))
        session.add(
            JobNormalized(
                source="linkedin",
                job_id="a",
                title="T",
                company="C",
                responsibilities_embedding=[1.0, 0.0],
                qualifications_embedding=[1.0, 0.0],
            )
        )

    result = find_similar_applications("linkedin", "a")

    assert result["responsibilities"] == []
    assert result["qualifications"] == []


def test_every_match_carries_its_application_id(fresh_db):
    _add_job("linkedin", "query", "Product Manager", [1.0, 0.0], [1.0, 0.0])
    _add_job("linkedin", "past", "Product Manager", [0.9, 0.1], [0.9, 0.1], company="Past Co")
    with db.session_scope() as session:
        past_id = session.query(Application).filter_by(job_id="past").one().id

    result = find_similar_applications("linkedin", "query")

    assert [m["application_id"] for m in result["overall"]] == [past_id]


def test_query_job_excludes_itself_from_its_own_results(fresh_db):
    _add_job("linkedin", "a", "Product Manager", [1.0, 0.0], [1.0, 0.0])
    _add_job("linkedin", "b", "Product Manager", [0.9, 0.1], [0.9, 0.1])

    result = find_similar_applications("linkedin", "a")

    # Two applications exist ("a" and "b"); querying "a" must not rank itself.
    assert len(result["responsibilities"]) == 1


def test_same_category_ranks_above_different_category(fresh_db):
    # A shared "genre" direction (x) plus a role-distinguishing direction (y),
    # same shape as the manual pilot that validated this approach.
    _add_job("linkedin", "query", "Product Manager", [10.0, 1.0], [10.0, 1.0])
    _add_job("linkedin", "pm2", "Product Manager", [10.0, 1.1], [10.0, 1.1])
    _add_job("linkedin", "mkt1", "Marketing", [10.0, -1.0], [10.0, -1.0])
    # Pad out categories so neither trips the thin-category threshold, which
    # would otherwise mix concerns with this test's actual assertion.
    for i in range(THIN_CATEGORY_THRESHOLD):
        _add_job("linkedin", f"pm-pad-{i}", "Product Manager", [10.0, 1.0 + i * 0.01], [10.0, 1.0])
        _add_job("linkedin", f"mkt-pad-{i}", "Marketing", [10.0, -1.0 - i * 0.01], [10.0, -1.0])

    result = find_similar_applications("linkedin", "query")

    top = result["responsibilities"][0]
    assert top["role"] == "Product Manager"


def test_thin_categories_are_flagged(fresh_db):
    _add_job("linkedin", "query", "Product Manager", [1.0, 0.0], [1.0, 0.0])
    for i in range(THIN_CATEGORY_THRESHOLD):  # enough to clear the threshold
        _add_job("linkedin", f"pm-{i}", "Product Manager", [1.0, 0.1 * i], [1.0, 0.1 * i])
    _add_job("linkedin", "da1", "Data Analyst", [0.0, 1.0], [0.0, 1.0])  # below threshold

    result = find_similar_applications("linkedin", "query")

    assert result["thin_categories"] == ["Data Analyst"]


def test_scores_are_standardized_not_raw_cosine(fresh_db):
    # Three candidates at clearly different similarity levels. Raw cosine
    # similarity here would be all-positive (these vectors are all fairly
    # close to the query) — standardized scores must include something on
    # both sides of 0, since they are defined relative to their own mean.
    _add_job("linkedin", "query", "Product Manager", [1.0, 0.0], [1.0, 0.0])
    _add_job("linkedin", "close", "Product Manager", [0.99, 0.05], [0.99, 0.05])
    _add_job("linkedin", "mid", "Product Manager", [0.9, 0.2], [0.9, 0.2])
    _add_job("linkedin", "far", "Product Manager", [0.7, 0.4], [0.7, 0.4])

    result = find_similar_applications("linkedin", "query", top_n=3)

    scores = [m["score"] for m in result["responsibilities"]]
    assert any(s > 0 for s in scores)
    assert any(s < 0 for s in scores)


def test_overall_combines_both_fields_not_just_one(fresh_db):
    # "resp_only" matches the query almost perfectly on responsibilities but
    # points the opposite way on qualifications; "agree" is a solid (if
    # imperfect) match on both. Overall must reward being decent on both
    # over being extreme on one, and so must rank "agree" above "resp_only"
    # even though "resp_only" tops the responsibilities-only ranking.
    _add_job("linkedin", "query", "Product Manager", [1.0, 0.0], [1.0, 0.0])
    _add_job("linkedin", "agree", "Product Manager", [0.9, 0.1], [0.9, 0.1], company="Agree")
    _add_job("linkedin", "resp_only", "Product Manager", [1.0, 0.0], [-1.0, 0.0], company="RespOnly")
    for i in range(THIN_CATEGORY_THRESHOLD):
        _add_job(
            "linkedin", f"pad-{i}", "Product Manager", [0.5, 0.5 + i * 0.01], [0.5, 0.5 + i * 0.01],
            company=f"Pad{i}",
        )

    result = find_similar_applications("linkedin", "query", top_n=1)

    assert result["responsibilities"][0]["company"] == "RespOnly"
    assert result["overall"][0]["company"] == "Agree"


def test_outcome_fields_ride_along_with_each_match(fresh_db):
    _add_job(
        "linkedin", "query", "Product Manager", [1.0, 0.0], [1.0, 0.0],
    )
    _add_job(
        "linkedin", "match", "Product Manager", [0.9, 0.1], [0.9, 0.1],
        status="rejected", highest_round="phone_screen",
    )

    result = find_similar_applications("linkedin", "query")

    match = result["responsibilities"][0]
    assert match["status"] == "rejected"
    assert match["highest_round"] == "phone_screen"
