"""Turn a job description into structured fields.

This is extraction, not judgement, so it runs on the cheapest capable model —
roughly $0.006 per description. Deciding whether a role is worth applying to
happens later, against the raw description, so a rubric change never means
re-normalizing anything.

Only fields no job board provides structurally are extracted. Compensation is
the clear case: Greenhouse returns pay_input_ranges as null and Lever returns
salaryRange as null even when the figures sit in the description text, and a
regex over that text mis-read three of five sampled postings.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field

from app import config
from app import prompts as _prompts
from app.evaluator import price


def load_prompt(version: str) -> str:
    """Read an extraction prompt version off disk. Cached in app.prompts."""
    try:
        return _prompts.load_prompt("normalizer", version)
    except _prompts.PromptUnavailable as exc:
        raise NormalizerUnavailable(str(exc)) from exc


def available_versions() -> list[str]:
    """Every extraction prompt version on disk, alphabetical."""
    return _prompts.available_versions("normalizer")


class NormalizedJob(BaseModel):
    responsibilities: list[str] = Field(
        default_factory=list,
        description="What the person will do, one entry per stated item.",
    )
    qualifications: list[str] = Field(
        default_factory=list,
        description=(
            "Every stated qualification as one flat list, whether the posting "
            "labelled it required, preferred, or neither."
        ),
    )
    comp_min: int | None = Field(
        default=None, description="Lower bound of a stated base salary range, else null."
    )
    comp_max: int | None = Field(
        default=None, description="Upper bound of a stated base salary range, else null."
    )
    workplace: str | None = Field(
        default=None, description='"remote", "hybrid", "onsite", or null if unstated.'
    )
    role_summary: list[str] = Field(
        default_factory=list,
        description=(
            "1-3 sentences copied word for word from where the posting describes "
            "this role's or team's purpose or mission. Empty if it has none."
        ),
    )


class NormalizerUnavailable(RuntimeError):
    """No usable Anthropic credentials. A fetched description is still kept."""


@dataclass
class NormalizerResult:
    normalized: NormalizedJob
    model: str
    prompt_version: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    # role_summary sentences rejected because they do not appear in the posting.
    role_summary_rejected: list[str] | None = None


def _client():
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover
        raise NormalizerUnavailable("anthropic package is not installed") from exc

    # The client constructs happily without credentials and only fails when a
    # request is actually built, so this cannot be the only guard — see the
    # call site.
    return anthropic.Anthropic()


NO_CREDENTIALS = (
    "no Anthropic credentials found. Set ANTHROPIC_API_KEY, or run "
    "'ant auth login'. Descriptions are still fetched and stored; only the "
    "structured fields are skipped."
)


def normalize(
    description: str,
    *,
    title: str = "",
    company: str = "",
    client=None,
    model: str | None = None,
    prompt_version: str | None = None,
) -> NormalizerResult:
    """Extract structured fields from one description."""
    if not description.strip():
        raise NormalizerUnavailable("description is empty, nothing to normalize")

    model = model or config.NORMALIZER_MODEL
    prompt_version = prompt_version or config.NORMALIZER_PROMPT_VERSION
    prompt = load_prompt(prompt_version)
    client = client or _client()

    heading = f"Job title: {title}\nCompany: {company}\n\n" if title else ""

    try:
        response = client.messages.parse(
            model=model,
            max_tokens=4096,
            system=prompt,
            messages=[
                {
                    "role": "user",
                    "content": f"{heading}Job description:\n\n{description}",
                }
            ],
            output_format=NormalizedJob,
        )
    except TypeError as exc:
        # The SDK raises TypeError, not an auth error, when no credential can
        # be resolved — it fails while building headers.
        if "authentication" in str(exc).lower():
            raise NormalizerUnavailable(NO_CREDENTIALS) from exc
        raise
    except Exception as exc:
        name = type(exc).__name__
        if name in {"AuthenticationError", "PermissionDeniedError"}:
            raise NormalizerUnavailable(NO_CREDENTIALS) from exc
        raise

    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "input_tokens", None)
    output_tokens = getattr(usage, "output_tokens", None)

    parsed = _clean(response.parsed_output)
    kept, rejected = verify_copied(parsed.role_summary, description)
    # The prompt asks for 1-3; the model has returned 6 (Faire), so the limit
    # is enforced here rather than trusted. Posting order is kept.
    parsed.role_summary = kept[:ROLE_SUMMARY_MAX]
    return NormalizerResult(
        normalized=parsed,
        model=model,
        prompt_version=prompt_version,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=price(model, input_tokens, output_tokens),
        role_summary_rejected=rejected,
    )


ROLE_SUMMARY_MAX = 3

# Typographic variants a model tends to straighten when it copies text.
_TYPOGRAPHY = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "})


def _comparable(text: str) -> str:
    return " ".join(text.translate(_TYPOGRAPHY).casefold().split())


def verify_copied(sentences: list[str], description: str) -> tuple[list[str], list[str]]:
    """Split sentences into (found in the posting, not found).

    role_summary is meant to be the posting's own words, and this is the
    check — in code, like the Resume Assembler's hard gate, rather than
    trusted to the prompt. Whitespace, case, curly quotes and dashes are
    evened out on both sides, since a posting's line breaks and typography
    are not part of its wording; anything else that differs is a rewrite.
    """
    haystack = _comparable(description)
    kept, rejected = [], []
    for sentence in sentences:
        (kept if _comparable(sentence) in haystack else rejected).append(sentence)
    return kept, rejected


def _clean(job: NormalizedJob) -> NormalizedJob:
    """Tidy the model's output without second-guessing its content."""
    workplace = (job.workplace or "").strip().lower() or None
    if workplace not in {"remote", "hybrid", "onsite", None}:
        workplace = None

    comp_min, comp_max = job.comp_min, job.comp_max
    # A reversed range is a misread rather than a real posting; ordering it is
    # safe, inventing the missing half would not be.
    if comp_min is not None and comp_max is not None and comp_min > comp_max:
        comp_min, comp_max = comp_max, comp_min

    return NormalizedJob(
        responsibilities=[s.strip() for s in job.responsibilities if s and s.strip()],
        qualifications=[s.strip() for s in job.qualifications if s and s.strip()],
        comp_min=comp_min,
        comp_max=comp_max,
        workplace=workplace,
        role_summary=[s.strip() for s in job.role_summary if s and s.strip()],
    )
