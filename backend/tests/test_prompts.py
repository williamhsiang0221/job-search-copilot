"""The shared versioned-prompt loader behind both the evaluator and the
normalizer — kind dispatch and the missing-version error, in isolation from
either workflow's own reasoning about what its prompt says."""

import pytest

from app.prompts import PromptUnavailable, available_versions, load_prompt


def test_loads_a_real_version_of_each_kind():
    assert "You extract structured fields" in load_prompt("normalizer", "v1")
    assert "Company tier" in load_prompt("evaluator", "v1")


def test_missing_version_raises_prompt_unavailable():
    with pytest.raises(PromptUnavailable):
        load_prompt("normalizer", "v99")


def test_missing_kind_raises_prompt_unavailable():
    with pytest.raises(PromptUnavailable):
        load_prompt("does-not-exist", "v1")


def test_available_versions_lists_every_file_for_that_kind_only():
    normalizer_versions = available_versions("normalizer")
    evaluator_versions = available_versions("evaluator")
    assert {"v1", "v2"} <= set(normalizer_versions)
    assert {"v1"} <= set(evaluator_versions)
    # Same version numbers exist on both sides, but each kind's directory is
    # read independently — same name, unrelated content.
    assert load_prompt("normalizer", "v1") != load_prompt("evaluator", "v1")


def test_unknown_kind_directory_returns_empty_not_an_error():
    assert available_versions("does-not-exist") == []


def test_normalizer_v2_exists_and_is_self_contained():
    assert "v2" in available_versions("normalizer")
    body = load_prompt("normalizer", "v2")
    assert "You extract structured fields" in body


def test_normalizer_v2_extracts_prose_not_just_bullets():
    # The bug this version fixes: a real posting (Google, 4426133638) stated
    # real duties in an "About The Job" paragraph as well as a bulleted
    # Responsibilities list, and only the bullets got extracted under v1.
    body = load_prompt("normalizer", "v2")
    assert "does not have to be bulleted to count" in body


def test_normalizer_v2_excludes_boilerplate_by_name():
    # The counterweight to the rule above — without this, more aggressive
    # prose extraction risks pulling in EEO/benefits/interview-process text
    # that is genuinely shared across postings and would make unrelated jobs
    # look similar to the similarity feature for the wrong reason.
    body = load_prompt("normalizer", "v2")
    assert "legal/EEO" in body
    assert "interview-process" in body


def test_normalizer_v1_is_untouched_by_the_v2_rewrite():
    # v1 already has 266 real normalized rows stamped against it — it must
    # keep meaning exactly what it meant when those rows were produced.
    body = load_prompt("normalizer", "v1")
    assert "does not have to be bulleted to count" not in body
    assert "legal/EEO" not in body
