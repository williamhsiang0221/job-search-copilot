"""Evaluator scoring, gates and verdict logic.

These are pure functions over the model's ten sub-scores, which makes them the
cheapest correctness guarantee in the build — the arithmetic either matches the
rubric or it does not, with no model call needed to find out.
"""

from dataclasses import dataclass

import pytest

from app import config

from app.evaluator import (
    SCORE_1_WEIGHTS,
    SCORE_2_WEIGHTS,
    RoleAssessment,
    ScoredSubScore,
    SubScore,
    available_versions,
    decide,
    fired_gate,
    load_prompt,
    price,
    score,
    weighted,
)
from app.evaluator import _render_job


def sub(code, value, *, abstained=False):
    weights = {**SCORE_1_WEIGHTS, **SCORE_2_WEIGHTS}
    return ScoredSubScore(
        code=code,
        score=value,
        weight=weights[code],
        abstained=abstained,
        rationale="",
    )


def assessment(**overrides) -> RoleAssessment:
    """A fully-scored assessment; override individual dimensions per test."""
    fields = {
        "function_alignment": 10,
        "company_tier": 8,
        "seniority_scope": 10,
        "location": 10,
        "keyword_match": 10,
        "yoe_title": 10,
        "education_reqs": 10,
        "story_depth": 10,
        "gap_exposure": 10,
        "why_company": 10,
    }
    gates = {
        k: overrides.pop(k)
        for k in list(overrides)
        if k
        in {
            "pm_years_required",
            "declining_bu",
            "pure_ic_research",
            "clearance_required",
            "reasoning",
        }
    }
    fields.update(overrides)
    return RoleAssessment(
        **{
            k: v if isinstance(v, SubScore) else SubScore(score=v)
            for k, v in fields.items()
        },
        **gates,
    )


class TestWeighting:
    def test_matches_the_rubric_arithmetic(self):
        # 10*.35 + 8*.30 + 10*.25 + 10*.10 = 9.4
        subs = [sub("4a", 10), sub("4b", 8), sub("4c", 10), sub("4d", 10)]
        assert weighted(subs, SCORE_1_WEIGHTS) == 9.4

    def test_abstention_renormalizes_rather_than_scoring_zero(self):
        # Dropping location must not drag the score down. Over the remaining
        # 0.90 of weight the result is unchanged at 10.
        subs = [sub("4a", 10), sub("4b", 10), sub("4c", 10), sub("4d", None, abstained=True)]
        assert weighted(subs, SCORE_1_WEIGHTS) == 10.0

    def test_all_abstained_is_none_not_zero(self):
        subs = [sub(c, None, abstained=True) for c in SCORE_1_WEIGHTS]
        assert weighted(subs, SCORE_1_WEIGHTS) is None

    def test_score_2_weights_sum_to_one(self):
        assert round(sum(SCORE_2_WEIGHTS.values()), 6) == 1.0
        assert round(sum(SCORE_1_WEIGHTS.values()), 6) == 1.0


class TestGates:
    def test_pm_years_fires_at_the_ceiling(self):
        assert fired_gate(assessment(pm_years_required=7), None) == "pm_years"
        assert fired_gate(assessment(pm_years_required=6), None) is None

    def test_salary_floor_uses_the_upper_bound(self):
        # $120-140K passes; $120-135K fails.
        assert fired_gate(assessment(), 140_000) is None
        assert fired_gate(assessment(), 135_000) == "salary_floor"

    def test_unstated_salary_does_not_fire(self):
        # Silence is not a failure. A posting that omits comp is not a posting
        # that fails the floor.
        assert fired_gate(assessment(), None) is None

    def test_declining_bu_and_ic_research_and_clearance(self):
        assert fired_gate(assessment(declining_bu=True), None) == "declining_bu"
        assert fired_gate(assessment(pure_ic_research=True), None) == "pure_ic_research"
        assert fired_gate(assessment(clearance_required=True), None) == "clearance"

    def test_null_gates_never_fire(self):
        assert fired_gate(assessment(declining_bu=None, pure_ic_research=None), None) is None


class TestVerdict:
    @pytest.mark.parametrize(
        "s1,s2,expected",
        [
            (8.0, 8.0, "APPLY"),   # both >= 7
            (7.5, 6.0, "APPLY"),   # one >= 7, other >= 6
            (6.0, 7.5, "APPLY"),
            (5.5, 5.5, "MAYBE"),   # both 5-6
            (8.0, 4.5, "MAYBE"),   # aspiration fit, weak background
            (4.5, 8.0, "SKIP"),    # good fit, wrong trajectory
            (3.0, 9.0, "SKIP"),    # either below 4
            (9.0, 3.0, "SKIP"),
        ],
    )
    def test_thresholds(self, s1, s2, expected):
        assert decide(s1, s2, uncertain=False) == expected

    def test_unmatched_combination_falls_back_to_maybe(self):
        # 6.5 / 4.5 matches none of the rubric's three rules. An unclassified
        # role must cost a glance, never the role.
        assert decide(6.5, 4.5, uncertain=False) == "MAYBE"

    def test_uncertainty_demotes_skip_to_maybe(self):
        assert decide(3.0, 9.0, uncertain=False) == "SKIP"
        assert decide(3.0, 9.0, uncertain=True) == "MAYBE"

    def test_uncertainty_does_not_promote_anything_else(self):
        assert decide(8.0, 8.0, uncertain=True) == "APPLY"
        assert decide(5.5, 5.5, uncertain=True) == "MAYBE"

    def test_missing_score_is_maybe(self):
        assert decide(None, 8.0, uncertain=False) == "MAYBE"


class TestScore:
    def test_end_to_end_apply(self):
        result = score(assessment(), comp_max=200_000, model="m", rubric_version="v1")
        assert result.verdict == "APPLY"
        assert result.disqualifier is None
        assert len(result.sub_scores) == 10

    def test_gate_skips_even_when_scores_are_perfect(self):
        result = score(assessment(clearance_required=True), comp_max=200_000)
        assert result.verdict == "SKIP"
        assert result.disqualifier == "clearance"

    def test_gate_skip_survives_an_abstention(self):
        # Gates fire on stated evidence, so uncertainty elsewhere does not
        # soften them.
        result = score(
            assessment(location=SubScore(score=None, abstained=True), declining_bu=True),
            comp_max=200_000,
        )
        assert result.verdict == "SKIP"
        assert result.disqualifier == "declining_bu"

    def test_abstention_blocks_a_score_based_skip(self):
        result = score(
            assessment(
                function_alignment=1,
                company_tier=4,
                seniority_scope=1,
                location=SubScore(score=None, abstained=True),
            ),
            comp_max=200_000,
        )
        assert result.score_1 is not None and result.score_1 < 4
        assert result.verdict == "MAYBE"

    def test_null_score_counts_as_abstention_even_if_unflagged(self):
        result = score(
            assessment(location=SubScore(score=None, abstained=False)),
            comp_max=200_000,
        )
        location = next(s for s in result.sub_scores if s.code == "4d")
        assert location.abstained is True

    def test_weights_are_recorded_as_applied(self):
        # So a later rubric cannot retroactively rewrite this verdict's basis.
        result = score(assessment(), comp_max=200_000)
        by_code = {s.code: s.weight for s in result.sub_scores}
        assert by_code["4a"] == 0.35
        assert by_code["5a"] == 0.30

    def test_scores_are_clamped_to_the_scale(self):
        result = score(assessment(function_alignment=99), comp_max=200_000)
        assert next(s for s in result.sub_scores if s.code == "4a").score == 10.0


class TestPrompt:
    """Structural rules every candidate's rubric follows. Tests run against
    the fictional profile.example/ (see conftest.py), so these check the
    rubric's design, not anyone's background."""

    def test_active_rubric_is_self_contained(self):
        assert config.EVALUATOR_RUBRIC_VERSION in available_versions()
        body = load_prompt(config.EVALUATOR_RUBRIC_VERSION)
        # The background must be inline: there is no second source to read.
        assert "## Background — the candidate" in body
        # Tier lists must be inline too, since there is no search step.
        assert "Anthropic" in body
        assert "Whatnot" in body

    def test_prompt_does_not_ask_the_model_to_do_arithmetic(self):
        body = load_prompt(config.EVALUATOR_RUBRIC_VERSION).lower()
        assert "do not compute weighted totals" in body

    def test_bridge_roles_score_at_da_ba_level_not_pm_level(self):
        # AI Strategist/FDE/Solutions PM/Deployment Strategist once scored
        # level with real PM ownership — the shape of every APPLY verdict in
        # a 30-sample audit that never got applied to. They belong at 4.
        body = load_prompt(config.EVALUATOR_RUBRIC_VERSION)
        assert "Deployment Strategist" in body
        assert "AI Strategist/FDE/Solutions PM at a Tier 2 AI startup = 10" not in body
        assert "B2B AI bridge, no product ownership = 7" not in body

    def test_location_scale_is_ny_only_with_deductions(self):
        body = load_prompt(config.EVALUATOR_RUBRIC_VERSION)
        assert "New Jersey = 6" in body
        assert "Remote US = 6" in body
        assert "Bay Area / Seattle / LA / other US / international = 0" in body


@dataclass
class _FakeNormalized:
    """Duck-types the fields _render_job reads — same shape as
    evaluations_service._Snapshot, without the rest of that module."""

    company: str = "Acme"
    title: str = "PM"
    workplace: str | None = None
    location: str = ""
    comp_min: int | None = None
    comp_max: int | None = None
    responsibilities: list = None
    qualifications: list = None

    def __post_init__(self):
        self.responsibilities = self.responsibilities or []
        self.qualifications = self.qualifications or []


class TestRenderJob:
    def test_includes_the_real_location_not_just_workplace(self):
        # The model previously had only workplace (remote/hybrid/onsite) to
        # score 4d against and was observed guessing a city from company HQ.
        # The rendered job must carry the actual city so it never has to.
        rendered = _render_job(_FakeNormalized(workplace="hybrid", location="New York, NY"))
        assert "Location: New York, NY" in rendered

    def test_missing_location_is_not_stated_not_blank(self):
        rendered = _render_job(_FakeNormalized(location=""))
        assert "Location: not stated" in rendered


class TestPricing:
    def test_haiku_matches_published_rates(self):
        # $1/1M in, $5/1M out.
        assert price("claude-haiku-4-5", 1_000_000, 1_000_000) == 6.0

    def test_a_realistic_call(self):
        # ~2,400 in / ~600 out is the measured shape of one evaluation.
        assert price("claude-haiku-4-5", 2400, 600) == pytest.approx(0.0054)

    def test_opus_is_priced_separately(self):
        assert price("claude-opus-5", 1_000_000, 1_000_000) == 30.0

    def test_unknown_model_records_no_cost_rather_than_a_guess(self):
        assert price("some-future-model", 1000, 1000) is None

    def test_missing_usage_is_not_a_zero_cost(self):
        # A null token count means the API did not report it, not that the
        # call was free.
        assert price("claude-haiku-4-5", None, 500) is None

    def test_cached_tokens_are_billed_not_dropped(self):
        # 1M uncached in at $1, 1M written at $1.25, 1M read at $0.10.
        assert price("claude-haiku-4-5", 1_000_000, 0, 1_000_000, 1_000_000) == pytest.approx(2.35)
