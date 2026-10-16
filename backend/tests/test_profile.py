"""The profile a checkout actually runs with.

Every other test is pinned to the fictional profile.example/ (conftest.py).
This one checks the real backend/profile/ when there is one — that it loads
and that every prompt it names exists — without asserting anything about its
contents. A public checkout has no profile/, so it is skipped there.
"""

import json
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
PROFILES = [p for p in (BACKEND / "profile", BACKEND / "profile.example") if p.is_dir()]


@pytest.mark.parametrize("profile", PROFILES, ids=lambda p: p.name)
def test_profile_settings_load_and_name_existing_prompts(profile):
    settings = json.loads((profile / "settings.json").read_text(encoding="utf-8"))
    assert isinstance(settings["salary_floor"], int)
    assert settings["locations"] and all(isinstance(l, str) for l in settings["locations"])
    for kind, key in (("evaluator", "evaluator_rubric_version"), ("resume", "resume_prompt_version")):
        assert (profile / "prompts" / kind / f"{settings[key]}.md").is_file(), (profile.name, kind)


def test_the_example_profile_is_always_present():
    assert (BACKEND / "profile.example" / "settings.json").is_file()
