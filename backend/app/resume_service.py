"""ICP Resume generation: an illustrative "Relevant Experience" section for a
specific posting, given a fixed, minimal candidate background baked into the
prompt itself (same approach as the evaluator rubric's own Background
section) — not a rewrite of the candidate's real resume.

This is a benchmark to compare a real resume against, not a document to be
used as-is. See the profile's prompts/resume/ for the actual rules (bullet
format, per-experience bullet allocation, plausibility gates).
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field

from app import config
from app import prompts as _prompts
from app.db import session_scope
from app.evaluator import price
from app.models import IcpResume, JobNormalized


class ResumeUnavailable(RuntimeError):
    """No prompt file at the requested version, or no usable credentials."""


def load_prompt(version: str) -> str:
    """Read an ICP Resume prompt version off disk. Cached in app.prompts."""
    try:
        return _prompts.load_prompt("resume", version)
    except _prompts.PromptUnavailable as exc:
        raise ResumeUnavailable(str(exc)) from exc


def available_versions() -> list[str]:
    """Every ICP Resume prompt version on disk, alphabetical."""
    return _prompts.available_versions("resume")


class ExperienceEntry(BaseModel):
    context: str = Field(description='Short label, e.g. "Telecom — Consumer Retention & Analytics".')
    bullets: list[str] = Field(default_factory=list)


class IcpResumeDraft(BaseModel):
    """What the model returns — one entry per included experience, already
    ordered most-recent-first per the prompt's Resume format rules."""

    experience: list[ExperienceEntry] = Field(default_factory=list)


@dataclass
class ResumeResult:
    experience: list[ExperienceEntry]
    model: str
    prompt_version: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None


def _client():
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover
        raise ResumeUnavailable("anthropic package is not installed") from exc

    return anthropic.Anthropic()


NO_CREDENTIALS = (
    "no Anthropic credentials found. Set ANTHROPIC_API_KEY, or run "
    "'ant auth login'."
)


def _render_job(normalized) -> str:
    """The posting as the prompt needs to see it — same shape as the
    evaluator's and normalizer's own job rendering."""
    lines = [f"Company: {normalized.company}", f"Title: {normalized.title}"]
    summary = getattr(normalized, "role_summary", None)
    if summary:
        lines.append("\nAbout the role (the posting's own words):")
        lines += [f"- {s}" for s in summary]
    lines.append("\nResponsibilities:")
    lines += [f"- {r}" for r in normalized.responsibilities] or ["- none stated"]
    lines.append("\nQualifications:")
    lines += [f"- {q}" for q in normalized.qualifications] or ["- none stated"]
    return "\n".join(lines)


def generate_icp_resume(
    normalized,
    *,
    client=None,
    model: str | None = None,
    prompt_version: str | None = None,
) -> ResumeResult:
    """Generate an ICP resume for one posting."""
    model = model or config.RESUME_MODEL
    prompt_version = prompt_version or config.RESUME_PROMPT_VERSION
    prompt = load_prompt(prompt_version)
    client = client or _client()

    try:
        response = client.messages.parse(
            model=model,
            max_tokens=4096,
            system=prompt,
            messages=[{"role": "user", "content": _render_job(normalized)}],
            output_format=IcpResumeDraft,
            # Confirmed live against claude-sonnet-5: with thinking left on
            # its default, it spent the entire max_tokens budget on an
            # extended-thinking block and returned no parsed output at all,
            # even at 8192. This task doesn't need visible reasoning — same
            # as the evaluator's and normalizer's calls, neither of which use
            # thinking either.
            thinking={"type": "disabled"},
        )
    except TypeError as exc:
        if "authentication" in str(exc).lower():
            raise ResumeUnavailable(NO_CREDENTIALS) from exc
        raise
    except Exception as exc:
        name = type(exc).__name__
        if name in {"AuthenticationError", "PermissionDeniedError"}:
            raise ResumeUnavailable(NO_CREDENTIALS) from exc
        raise

    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "input_tokens", None)
    output_tokens = getattr(usage, "output_tokens", None)

    parsed = response.parsed_output
    return ResumeResult(
        experience=parsed.experience,
        model=model,
        prompt_version=prompt_version,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=price(model, input_tokens, output_tokens),
    )


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def create_icp_resume(source: str, job_id: str) -> dict:
    """Generate and store one ICP resume for a normalized job.

    Every call appends a new row rather than replacing a prior one for the
    same job — same reasoning as Evaluation: a prompt-version change makes
    runs incomparable, and re-generating on purpose (to compare against a
    prior run) is the expected way this gets used while the prompt is still
    being iterated on.
    """
    with session_scope() as session:
        normalized = session.get(JobNormalized, (source, job_id))
        if normalized is None:
            raise ResumeUnavailable("not normalized yet")
        # Detach a plain snapshot so the model call happens outside the session.
        snapshot = type(
            "_Snapshot",
            (),
            {
                "company": normalized.company,
                "title": normalized.title,
                "responsibilities": list(normalized.responsibilities or []),
                "qualifications": list(normalized.qualifications or []),
                "role_summary": list(normalized.role_summary or []),
            },
        )()

    result = generate_icp_resume(snapshot)

    with session_scope() as session:
        row = IcpResume(
            source=source,
            job_id=job_id,
            company=snapshot.company,
            title=snapshot.title,
            experience=[e.model_dump() for e in result.experience],
            model=result.model,
            prompt_version=result.prompt_version,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cost_usd=result.cost_usd,
        )
        session.add(row)
        session.flush()
        return _as_dict(row)


def _as_dict(row: IcpResume) -> dict:
    return {
        "id": row.id,
        "source": row.source,
        "job_id": row.job_id,
        "company": row.company,
        "title": row.title,
        "experience": row.experience,
        "model": row.model,
        "prompt_version": row.prompt_version,
        "input_tokens": row.input_tokens,
        "output_tokens": row.output_tokens,
        "cost_usd": row.cost_usd,
        "generated_at": _iso(row.generated_at),
    }


def list_icp_resumes() -> list[dict]:
    """Every ICP resume ever generated, newest first."""
    with session_scope() as session:
        rows = session.query(IcpResume).order_by(IcpResume.generated_at.desc()).all()
        return [_as_dict(r) for r in rows]


def total_resume_cost() -> float:
    """Sum of every recorded generation's cost. Null rows count as zero —
    same convention as total_normalize_cost/total_evaluation_cost."""
    with session_scope() as session:
        rows = session.query(IcpResume.cost_usd).all()
        return round(sum(c or 0.0 for (c,) in rows), 6)
