"""The demo database's content stays consistent with the app.

backend/demo/seed_demo.py runs the real app code over demo/demo_data.py; a
mismatch there (a tag name that no longer exists, an evaluation for a job
that is gone, a role summary not in its posting) would only surface when
someone rebuilds the demo. These catch it in the normal test run instead.
"""

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND / "demo"))

import demo_data as data  # noqa: E402


def test_every_tag_the_demo_uses_exists_in_the_seed_tags():
    names = {t["name"] for t in json.loads((BACKEND / "data" / "bullet_tags_seed.json").read_text())}
    used = {n for tags in data.TAGGED.values() for n in tags} | {
        t for picks in data.SUGGESTED.values() for t, _ in picks
    }
    assert used <= names, used - names


def test_evaluations_resumes_and_the_assembler_target_point_at_real_entries():
    companies = {j["company"]: j for j in data.JOBS}
    applied = {a[0] for a in data.APPLICATIONS}
    assert all(companies[c]["kind"] == "open" for c in data.EVALUATIONS)
    assert set(data.RESUMES) <= applied
    assert data.ASSEMBLER_JOB in {(j["source"], j["job_id"]) for j in data.JOBS}


def test_every_evaluation_scripts_all_ten_sub_scores():
    from app.evaluator import CODE_BY_FIELD

    for company, spec in data.EVALUATIONS.items():
        assert set(CODE_BY_FIELD) <= set(spec), company


def test_role_summaries_are_one_sentence_each_and_jobs_are_unique():
    ids = [(j["source"], j["job_id"]) for j in data.JOBS]
    assert len(ids) == len(set(ids))
    for job in data.JOBS:
        assert job["summary"] and all(s.endswith(".") for s in job["summary"]), job["company"]
