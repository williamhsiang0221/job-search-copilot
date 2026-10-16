from datetime import date

import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException

from app.main import app, resolve_range

client = TestClient(app)
TODAY = date(2026, 8, 26)


@pytest.fixture(autouse=True)
def _linkedin_fetch_available(monkeypatch):
    """The fetch-progress tests use "linkedin" as their sample source. The
    public build ships without the LinkedIn module, so treat it as available
    here; a test about its absence patches this back to False."""
    import app.main as main

    monkeypatch.setattr(main, "linkedin_fetch_available", lambda: True)


def test_health():
    assert client.get("/api/health").status_code == 200


def test_costs_returns_a_total_that_is_the_sum_of_its_parts():
    # Hits the real db, not a fresh one, so this asserts shape and internal
    # consistency rather than a specific figure that would drift as the app
    # is used.
    body = client.get("/api/costs").json()
    assert set(body) == {
        "normalize_cost_usd",
        "evaluation_cost_usd",
        "embedding_cost_usd",
        "resume_cost_usd",
        "assembler_cost_usd",
        "bullet_tagger_cost_usd",
        "total_cost_usd",
    }
    expected_total = (
        body["normalize_cost_usd"]
        + body["evaluation_cost_usd"]
        + body["embedding_cost_usd"]
        + body["resume_cost_usd"]
        + body["assembler_cost_usd"]
        + body["bullet_tagger_cost_usd"]
    )
    assert body["total_cost_usd"] == round(expected_total, 6)


def _drain_fetch_progress(source: str = "linkedin", timeout_s: float = 1.0):
    """Waits out any in-flight fetch so it cannot bleed into the next test —
    fetch_progress is a module-level singleton shared across the whole run."""
    import time

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not client.get("/api/jobs/fetch/progress", params={"source": source}).json()["running"]:
            return
        time.sleep(0.02)


def test_fetch_runs_in_the_background_and_reports_progress_until_done(monkeypatch):
    import time

    from app import main as main_module
    from app.jobs_service import FetchReport

    def fake_fetch_and_store(job_ids, source=None, on_progress=None):
        report = FetchReport()
        for job_id in job_ids:
            report.stored.append(job_id)
            report.normalized.append(job_id)
            if on_progress:
                on_progress(job_id)
        return report

    monkeypatch.setattr(main_module, "fetch_and_store", fake_fetch_and_store)

    start = client.post("/api/jobs/fetch", json={"job_ids": ["x", "y"]})
    assert start.status_code == 200
    assert start.json() == {"started": True}

    progress = {"running": True}
    deadline = time.monotonic() + 1.0
    while progress["running"] and time.monotonic() < deadline:
        progress = client.get("/api/jobs/fetch/progress").json()
        time.sleep(0.02)

    assert progress["running"] is False
    assert set(progress["done_ids"]) == {"x", "y"}
    assert progress["report"]["counts"]["normalized"] == 2


def test_a_second_fetch_is_rejected_while_one_is_running(monkeypatch):
    import time

    from app import main as main_module
    from app.jobs_service import FetchReport

    def slow_fetch_and_store(job_ids, source=None, on_progress=None):
        time.sleep(0.3)
        return FetchReport()

    monkeypatch.setattr(main_module, "fetch_and_store", slow_fetch_and_store)

    first = client.post("/api/jobs/fetch", json={"job_ids": ["z"]})
    assert first.status_code == 200

    second = client.post("/api/jobs/fetch", json={"job_ids": ["z"]})
    assert second.status_code == 409

    _drain_fetch_progress()


def test_two_different_sources_fetch_concurrently_without_crosstalk(monkeypatch):
    """The regression this source-scoped tracking exists to prevent: a
    Greenhouse and a Lever batch (different hosts) already fire concurrently
    from the frontend when a selection spans sources, and a global "one fetch
    at a time" tracker would either reject the second or, worse, let it
    overwrite the first's in-flight progress."""
    from app import main as main_module
    from app.jobs_service import FetchReport

    def fake_fetch_and_store(job_ids, source=None, on_progress=None):
        for job_id in job_ids:
            if on_progress:
                on_progress(job_id)
        return FetchReport(stored=list(job_ids), normalized=list(job_ids))

    monkeypatch.setattr(main_module, "fetch_and_store", fake_fetch_and_store)
    monkeypatch.setattr(main_module, "_build_ats_source", lambda *a, **k: object())

    first = client.post("/api/jobs/fetch", json={"job_ids": ["li-1"], "source": "linkedin"})
    second = client.post(
        "/api/jobs/fetch",
        json={"job_ids": ["gh-1"], "source": "greenhouse", "job_companies": {"gh-1": "Acme"}},
    )
    assert first.status_code == 200
    assert second.status_code == 200

    _drain_fetch_progress("linkedin")
    _drain_fetch_progress("greenhouse")

    li_progress = client.get("/api/jobs/fetch/progress", params={"source": "linkedin"}).json()
    gh_progress = client.get("/api/jobs/fetch/progress", params={"source": "greenhouse"}).json()
    assert li_progress["report"]["stored"] == ["li-1"]
    assert gh_progress["report"]["stored"] == ["gh-1"]


def _drain_evaluate_progress(source: str = "linkedin", timeout_s: float = 1.0):
    import time

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not client.get("/api/evaluate/progress", params={"source": source}).json()["running"]:
            return
        time.sleep(0.02)


def test_evaluate_runs_in_the_background_and_reports_progress_until_done(monkeypatch):
    """Same shape as the fetch endpoint's background start/poll cycle."""
    import time

    from app import main as main_module
    from app.evaluations_service import EvaluationReport

    def fake_evaluate_jobs(job_ids, source=None, rubric_version=None, on_progress=None):
        report = EvaluationReport()
        for job_id in job_ids:
            report.evaluated.append(job_id)
            if on_progress:
                on_progress(job_id)
        return report

    monkeypatch.setattr(main_module, "evaluate_jobs", fake_evaluate_jobs)

    start = client.post("/api/evaluate", json={"job_ids": ["x", "y"]})
    assert start.status_code == 200
    assert start.json() == {"started": True}

    progress = {"running": True}
    deadline = time.monotonic() + 1.0
    while progress["running"] and time.monotonic() < deadline:
        progress = client.get("/api/evaluate/progress").json()
        time.sleep(0.02)

    assert progress["running"] is False
    assert set(progress["done_ids"]) == {"x", "y"}
    assert progress["report"]["evaluated"] == ["x", "y"]


def test_a_second_evaluation_is_rejected_while_the_same_source_is_running(monkeypatch):
    import time

    from app import main as main_module
    from app.evaluations_service import EvaluationReport

    def slow_evaluate_jobs(job_ids, source=None, rubric_version=None, on_progress=None):
        time.sleep(0.3)
        return EvaluationReport()

    monkeypatch.setattr(main_module, "evaluate_jobs", slow_evaluate_jobs)

    first = client.post("/api/evaluate", json={"job_ids": ["z"]})
    assert first.status_code == 200

    second = client.post("/api/evaluate", json={"job_ids": ["z"]})
    assert second.status_code == 409

    _drain_evaluate_progress()


def test_evaluate_and_fetch_progress_are_tracked_independently(monkeypatch):
    """A running fetch must never block a concurrent evaluate (or vice versa)
    — they're different resources even for the same source."""
    import time

    from app import main as main_module
    from app.evaluations_service import EvaluationReport
    from app.jobs_service import FetchReport

    def slow_fetch_and_store(job_ids, source=None, on_progress=None):
        time.sleep(0.3)
        return FetchReport()

    def fast_evaluate_jobs(job_ids, source=None, rubric_version=None, on_progress=None):
        return EvaluationReport(evaluated=list(job_ids))

    monkeypatch.setattr(main_module, "fetch_and_store", slow_fetch_and_store)
    monkeypatch.setattr(main_module, "evaluate_jobs", fast_evaluate_jobs)

    fetch_start = client.post("/api/jobs/fetch", json={"job_ids": ["a"], "source": "linkedin"})
    evaluate_start = client.post("/api/evaluate", json={"job_ids": ["a"], "source": "linkedin"})
    assert fetch_start.status_code == 200
    assert evaluate_start.status_code == 200

    _drain_fetch_progress("linkedin")
    _drain_evaluate_progress("linkedin")


@pytest.mark.parametrize(
    "preset,expected",
    [
        ("today", (date(2026, 8, 26), date(2026, 8, 26))),
        ("yesterday", (date(2026, 8, 25), date(2026, 8, 25))),
        ("past3", (date(2026, 8, 24), date(2026, 8, 26))),
        ("past7", (date(2026, 8, 20), date(2026, 8, 26))),
    ],
)
def test_presets_are_calendar_days(preset, expected):
    assert resolve_range(preset, None, None, today=TODAY) == expected


def test_custom_requires_both_dates():
    with pytest.raises(HTTPException) as exc:
        resolve_range("custom", date(2026, 8, 1), None, today=TODAY)
    assert exc.value.status_code == 400


def test_custom_rejects_reversed_range():
    with pytest.raises(HTTPException) as exc:
        resolve_range("custom", date(2026, 8, 5), date(2026, 8, 1), today=TODAY)
    assert exc.value.status_code == 400


def test_unknown_preset_rejected():
    with pytest.raises(HTTPException):
        resolve_range("last_century", None, None, today=TODAY)


def test_similar_applications_shape_for_a_real_normalized_job():
    # Hits the real db: asserts response shape, not specific matches, since
    # the actual application history will keep changing.
    from app.db import session_scope
    from app.models import JobNormalized

    with session_scope() as session:
        row = (
            session.query(JobNormalized)
            .filter(JobNormalized.responsibilities_embedding.isnot(None))
            .first()
        )
        source, job_id = (row.source, row.job_id) if row else (None, None)

    if source is None:
        pytest.skip("no embedded job in the live db to test against")

    body = client.get(f"/api/jobs/{source}/{job_id}/similar-applications").json()
    assert set(body) == {"responsibilities", "qualifications", "overall", "thin_categories"}
    for field in ("responsibilities", "qualifications", "overall"):
        for match in body[field]:
            assert set(match) == {"application_id", "company", "title", "role", "status", "highest_round", "score"}


def test_similar_applications_for_an_unknown_job_is_empty_not_an_error():
    body = client.get("/api/jobs/linkedin/does-not-exist/similar-applications").json()
    assert body == {"responsibilities": [], "qualifications": [], "overall": [], "thin_categories": []}


def test_capture_returns_roles_from_fixtures():
    response = client.get("/api/capture", params={"range": "past3"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["roles_found"] == 14  # 6 + 6 + 2, all distinct
    assert payload["meta"]["duplicates_collapsed"] == 0
    assert all(r["match_count"] == 1 for r in payload["roles"])
    assert payload["meta"]["source"] == "fixtures"

    role = payload["roles"][0]
    assert set(role) >= {"title", "company", "location", "url", "job_id"}
    assert role["url"].startswith("https://www.linkedin.com/jobs/view/")


def test_capture_rejects_bad_preset_over_http():
    assert client.get("/api/capture", params={"range": "nope"}).status_code == 400


def test_email_dates_normalize_to_utc_iso():
    """Headers arrive with varying offsets; normalising to UTC ISO makes a
    string compare chronological, which dedupe and the dashboard both rely on."""
    from app.sources import normalize_date

    assert normalize_date("Wed, 26 Aug 2026 17:51:12 +0000") == "2026-08-26T17:51:12+00:00"
    # Same instant, different offset — must produce the same UTC string.
    assert normalize_date("Wed, 26 Aug 2026 13:51:12 -0400") == "2026-08-26T17:51:12+00:00"


def test_unparseable_date_is_empty_not_fatal():
    from app.sources import normalize_date

    assert normalize_date("not a date") == ""
    assert normalize_date("") == ""


def test_normalized_dates_sort_chronologically_as_strings():
    from app.sources import normalize_date

    earlier = normalize_date("Wed, 26 Aug 2026 13:51:12 -0400")
    later = normalize_date("Wed, 26 Aug 2026 19:00:00 +0000")
    assert earlier < later


@pytest.mark.parametrize("kind", ["ats_criteria", "ats_scanner", "recruiter_scanner", "assembler"])
def test_scanner_prompts_are_served_like_every_other_prompt_kind(kind):
    versions = client.get(f"/api/prompts/{kind}").json()
    assert versions["active"] in versions["versions"]
    assert "v1" in versions["versions"]

    body = client.get(f"/api/prompts/{kind}/v1")
    assert body.status_code == 200
    assert body.json()["body"].strip()


def test_evaluation_note_route_404s_for_an_unknown_evaluation():
    response = client.put("/api/evaluations/987654321/note", json={"note": "x"})
    assert response.status_code == 404


def test_linkedin_fetch_is_a_clear_501_when_the_module_is_absent(monkeypatch):
    import app.main as main

    monkeypatch.setattr(main, "linkedin_fetch_available", lambda: False)
    response = client.post("/api/jobs/fetch", json={"source": "linkedin", "job_ids": ["123"]})
    assert response.status_code == 501
    assert "not included in this build" in response.json()["detail"]
