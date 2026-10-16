"""Score a stored job against the rubric and produce a verdict.

This is an attention router, not a decision maker. Every verdict maps to an
amount of the candidate's attention, and only one of them is expensive to get
wrong:

    SKIP   they do nothing        <- a SKIP they would have applied to is the
                                     one error that costs a real opportunity
    MAYBE  glances at the title      cheap either way
    APPLY  reads the JD             cheap either way

So the rule that outranks every scoring refinement: **when uncertain, never
SKIP.** An evaluation carrying an abstention falls back to MAYBE.

The model assigns the ten sub-scores; every piece of arithmetic — weights, both
weighted sums, the gates, the thresholds — happens here in Python. A model
asked to do weighted arithmetic mid-prose gets it subtly wrong and never says
so, and keeping the weights in code makes a rubric change a diff rather than a
prompt that drifts.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from app import config
from app import prompts as _prompts

# Sub-score weights, from the rubric. These live in code, not in the prompt,
# because they are arithmetic rather than judgement.
SCORE_1_WEIGHTS = {"4a": 0.35, "4b": 0.30, "4c": 0.25, "4d": 0.10}
SCORE_2_WEIGHTS = {"5a": 0.30, "5b": 0.18, "5c": 0.12, "5d": 0.16, "5e": 0.14, "5f": 0.10}
WEIGHTS = {**SCORE_1_WEIGHTS, **SCORE_2_WEIGHTS}

# The upper bound of a stated range must clear this. Applied in code because
# the figure is already stored — asking the model to re-read it from prose
# would add a way to be wrong for no gain.
SALARY_FLOOR = config.SALARY_FLOOR

# Years of PM-title-specific experience at which the role is out of reach.
PM_YEARS_CEILING = 7

# USD per million tokens, (input, output). Only what this project might
# plausibly run on — an unknown model records tokens with a null cost rather
# than a guessed one, on the same principle as everything else here.
PRICES_PER_MTOK = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-fable-5": (10.0, 50.0),
}


# Prompt caching, as multiples of the input rate (5-minute cache): writing a
# prefix into the cache costs a premium, reading it back costs a tenth.
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.1


def price(
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
    cache_write_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float | None:
    """What this call cost, or None if the model's price is unknown.

    With prompt caching on, the API reports cached tokens separately from
    input_tokens (which then counts only the uncached remainder), so callers
    that cache must pass both cache counts or the cost under-counts.
    """
    rates = PRICES_PER_MTOK.get(model)
    if rates is None or input_tokens is None or output_tokens is None:
        return None
    in_rate, out_rate = rates
    return round(
        (
            input_tokens * in_rate
            + cache_write_tokens * in_rate * CACHE_WRITE_MULTIPLIER
            + cache_read_tokens * in_rate * CACHE_READ_MULTIPLIER
            + output_tokens * out_rate
        )
        / 1_000_000,
        6,
    )


class EvaluatorUnavailable(RuntimeError):
    """No usable Anthropic credentials, or nothing to evaluate."""


class SubScore(BaseModel):
    score: float | None = Field(
        default=None,
        description="0-10 on this dimension's scale, or null when abstaining.",
    )
    abstained: bool = Field(
        default=False,
        description=(
            "True only when the posting does not state what this dimension "
            "needs. Never a substitute for a low score."
        ),
    )
    rationale: str = Field(default="", description="One line of justification.")


class RoleAssessment(BaseModel):
    """What the model returns. No totals, no verdict — those are computed."""

    function_alignment: SubScore = Field(description="4a")
    company_tier: SubScore = Field(description="4b")
    seniority_scope: SubScore = Field(description="4c")
    location: SubScore = Field(description="4d")

    keyword_match: SubScore = Field(description="5a")
    yoe_title: SubScore = Field(description="5b")
    education_reqs: SubScore = Field(description="5c")
    story_depth: SubScore = Field(description="5d")
    gap_exposure: SubScore = Field(description="5e")
    why_company: SubScore = Field(description="5f")

    pm_years_required: int | None = Field(
        default=None,
        description=(
            "Years of PM-title-specific experience demanded, not total years. "
            "Null when the posting does not say."
        ),
    )
    declining_bu: bool | None = Field(
        default=None,
        description="Structurally declining business unit, or null if unclear.",
    )
    pure_ic_research: bool | None = Field(
        default=None,
        description="Pure IC research with no PM path, or null if unclear.",
    )
    clearance_required: bool | None = Field(
        default=None, description="Security clearance required, or null if unstated."
    )

    reasoning: str = Field(default="", description="Three to five sentences.")


# Model field name -> rubric sub-score code.
CODE_BY_FIELD = {
    "function_alignment": "4a",
    "company_tier": "4b",
    "seniority_scope": "4c",
    "location": "4d",
    "keyword_match": "5a",
    "yoe_title": "5b",
    "education_reqs": "5c",
    "story_depth": "5d",
    "gap_exposure": "5e",
    "why_company": "5f",
}


@dataclass
class ScoredSubScore:
    code: str
    score: float | None
    weight: float
    abstained: bool
    rationale: str


@dataclass
class EvaluationResult:
    score_1: float | None
    score_2: float | None
    verdict: str
    disqualifier: str | None
    reasoning: str
    model: str
    rubric_version: str
    sub_scores: list[ScoredSubScore] = field(default_factory=list)
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    latency_ms: int | None = None


def load_prompt(version: str) -> str:
    """Read a rubric version off disk. Cached in app.prompts — it does not
    change at runtime."""
    try:
        return _prompts.load_prompt("evaluator", version)
    except _prompts.PromptUnavailable as exc:
        raise EvaluatorUnavailable(str(exc)) from exc


def available_versions() -> list[str]:
    """Every rubric version on disk, alphabetical."""
    return _prompts.available_versions("evaluator")


def weighted(sub_scores: list[ScoredSubScore], codes: dict[str, float]) -> float | None:
    """Weighted mean over the dimensions that were actually scored.

    Abstentions are dropped and the remaining weights renormalized, rather than
    counted as zero. Treating "not stated" as a zero would be the same
    fabrication the abstention exists to avoid, and it would drag every
    under-specified posting toward SKIP.
    """
    scored = [s for s in sub_scores if s.code in codes and not s.abstained and s.score is not None]
    total_weight = sum(s.weight for s in scored)
    if total_weight <= 0:
        return None
    return round(sum(s.score * s.weight for s in scored) / total_weight, 1)


def fired_gate(assessment: RoleAssessment, comp_max: int | None) -> str | None:
    """Which hard disqualifier fired, if any.

    A gate fires only on positive evidence. Silence is not a failure: a posting
    that omits its salary is not a posting that fails the salary floor.
    """
    if assessment.pm_years_required is not None and assessment.pm_years_required >= PM_YEARS_CEILING:
        return "pm_years"
    if comp_max is not None and comp_max < SALARY_FLOOR:
        return "salary_floor"
    if assessment.declining_bu is True:
        return "declining_bu"
    if assessment.pure_ic_research is True:
        return "pure_ic_research"
    if assessment.clearance_required is True:
        return "clearance"
    return None


def decide(score_1: float | None, score_2: float | None, *, uncertain: bool) -> str:
    """Turn two scores into a verdict.

    The rubric's own thresholds leave gaps — a 6.5 against a 4.5 matches none of
    its three rules — so anything unmatched lands on MAYBE. That is the same
    asymmetry the whole design rests on: an unclassified role costs a glance,
    and a wrong SKIP costs the role.
    """
    if score_1 is None or score_2 is None:
        return "MAYBE"

    def skip() -> str:
        # A SKIP reached through incomplete scoring is exactly the expensive
        # error, so uncertainty demotes it. A SKIP from a fired gate never
        # reaches here — gates decide before this function runs.
        return "MAYBE" if uncertain else "SKIP"

    if score_1 < 4 or score_2 < 4:
        return skip()
    if score_2 >= 7 and score_1 < 5:
        return skip()
    if score_1 >= 7 and score_2 >= 7:
        return "APPLY"
    if (score_1 >= 7 and score_2 >= 6) or (score_2 >= 7 and score_1 >= 6):
        return "APPLY"
    return "MAYBE"


def _client():
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover
        raise EvaluatorUnavailable("anthropic package is not installed") from exc

    return anthropic.Anthropic()


NO_CREDENTIALS = (
    "no Anthropic credentials found. Set ANTHROPIC_API_KEY, or run "
    "'ant auth login'. Stored descriptions are unaffected; only the "
    "evaluation is skipped."
)


def _render_job(normalized) -> str:
    """The posting as the rubric needs to see it."""
    lines = [
        f"Company: {normalized.company}",
        f"Title: {normalized.title}",
        f"Workplace: {normalized.workplace or 'not stated'}",
        f"Location: {normalized.location or 'not stated'}",
    ]
    if normalized.comp_min or normalized.comp_max:
        lines.append(f"Compensation: {normalized.comp_min} - {normalized.comp_max}")
    else:
        lines.append("Compensation: not stated")

    lines.append("\nResponsibilities:")
    lines += [f"- {r}" for r in normalized.responsibilities] or ["- none stated"]
    lines.append("\nQualifications:")
    lines += [f"- {q}" for q in normalized.qualifications] or ["- none stated"]
    return "\n".join(lines)


def evaluate(
    normalized,
    *,
    client=None,
    model: str | None = None,
    rubric_version: str | None = None,
) -> EvaluationResult:
    """Score one normalized job and decide a verdict."""
    model = model or config.EVALUATOR_MODEL
    rubric_version = rubric_version or config.EVALUATOR_RUBRIC_VERSION
    prompt = load_prompt(rubric_version)
    client = client or _client()

    started = time.monotonic()
    try:
        response = client.messages.parse(
            model=model,
            max_tokens=4096,
            system=prompt,
            messages=[{"role": "user", "content": _render_job(normalized)}],
            output_format=RoleAssessment,
        )
    except TypeError as exc:
        # The SDK raises TypeError, not an auth error, when no credential can
        # be resolved — it fails while building headers.
        if "authentication" in str(exc).lower():
            raise EvaluatorUnavailable(NO_CREDENTIALS) from exc
        raise
    except Exception as exc:
        name = type(exc).__name__
        if name in {"AuthenticationError", "PermissionDeniedError"}:
            raise EvaluatorUnavailable(NO_CREDENTIALS) from exc
        raise

    latency_ms = int((time.monotonic() - started) * 1000)
    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "input_tokens", None)
    output_tokens = getattr(usage, "output_tokens", None)

    result = score(
        response.parsed_output,
        comp_max=normalized.comp_max,
        model=model,
        rubric_version=rubric_version,
    )
    result.input_tokens = input_tokens
    result.output_tokens = output_tokens
    result.cost_usd = price(model, input_tokens, output_tokens)
    result.latency_ms = latency_ms
    return result


def score(
    assessment: RoleAssessment,
    *,
    comp_max: int | None,
    model: str = "",
    rubric_version: str = "",
) -> EvaluationResult:
    """Turn a model assessment into scores and a verdict. Pure arithmetic."""
    sub_scores: list[ScoredSubScore] = []
    for field_name, code in CODE_BY_FIELD.items():
        raw: SubScore = getattr(assessment, field_name)
        # A null score is an abstention whether or not the model said so.
        abstained = raw.abstained or raw.score is None
        sub_scores.append(
            ScoredSubScore(
                code=code,
                score=None if abstained else _clamp(raw.score),
                weight=WEIGHTS[code],
                abstained=abstained,
                rationale=(raw.rationale or "").strip(),
            )
        )

    score_1 = weighted(sub_scores, SCORE_1_WEIGHTS)
    score_2 = weighted(sub_scores, SCORE_2_WEIGHTS)

    disqualifier = fired_gate(assessment, comp_max)
    if disqualifier:
        # Gates fire on stated evidence, so they are allowed to SKIP outright.
        verdict = "SKIP"
    else:
        verdict = decide(
            score_1,
            score_2,
            uncertain=any(s.abstained for s in sub_scores),
        )

    return EvaluationResult(
        score_1=score_1,
        score_2=score_2,
        verdict=verdict,
        disqualifier=disqualifier,
        reasoning=(assessment.reasoning or "").strip(),
        model=model,
        rubric_version=rubric_version,
        sub_scores=sub_scores,
    )


def _clamp(value: float | None) -> float | None:
    """Keep a score on the 0-10 scale the rubric defines."""
    if value is None:
        return None
    return max(0.0, min(10.0, float(value)))
