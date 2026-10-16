"""Resume Assembler scanners: the judges an assembled draft has to get past.

Phase 2 of the assembler. Three single structured calls, each with its own
versioned prompt under data/prompts/{kind}/, plus a hard gate in plain code:

- build_ats_criteria: a screening checklist derived from the posting. Built
  once per run and shared by both pairwise scanners, so every round is judged
  against the same yardstick — rebuilding it each round would move the target
  between iterations.
- run_ats_scan / run_recruiter_scan: pairwise, candidate draft vs. anchor. The
  two go in as "A"/"B" in random order and the model is never told which is
  the anchor, because LLM judges lean toward whichever option comes first.
  Identical drafts short-circuit to a tie without a call.
- run_hard_gate_scan: no model at all. Checks every header and bullet in
  the draft against the stored line it claims to come from — same text, same
  section slot — so nothing the Assembler hands back was invented or moved
  across sections. Deliberately that and nothing else for now: an LLM
  proofreading gate was piloted first and failed the user's own real
  resumes on style calls, and since the Assembler can only swap lines, never
  reword them, a gate on wording it can't change is one it can never pass.

The recruiter's six-second view is cut in Python before the model sees
anything, so "only looks at the top" is enforced, not requested.

Nothing here writes to the database. The agent loop logs every call into
the run's trace.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from app import config
from app import prompts as _prompts
from app import resume_layout
from app.db import session_scope
from app.evaluator import price
from app.models import Bullet, Section
from app.resume_service import _render_job

# The prompted scanners. The hard gate has no prompt — see module docstring.
SCANNER_KINDS = ("ats_criteria", "ats_scanner", "recruiter_scanner")

# Sections that aren't a job — skipped when picking a recruiter's "top two
# roles". Anything else counts as experience, including slots added later.
# From the profile's resume layout (each slot's "experience" flag).
NON_EXPERIENCE_SLOTS = resume_layout.NON_EXPERIENCE_SLOTS

# Employer context for each slot, identical for every version of the resume
# (these lines are constant and not stored), so it gives the judges context
# without favoring either side. From the profile's resume layout.
SLOT_LABELS = resume_layout.SLOT_CONTEXT


class ScannerUnavailable(RuntimeError):
    """No prompt file at the requested version, or no usable credentials."""


NO_CREDENTIALS = "no Anthropic credentials found. Set ANTHROPIC_API_KEY, or run 'ant auth login'."


def load_prompt(kind: str, version: str) -> str:
    try:
        return _prompts.load_prompt(kind, version)
    except _prompts.PromptUnavailable as exc:
        raise ScannerUnavailable(str(exc)) from exc


def available_versions(kind: str) -> list[str]:
    return _prompts.available_versions(kind)


def active_version(kind: str) -> str:
    return {
        "ats_criteria": config.ATS_CRITERIA_PROMPT_VERSION,
        "ats_scanner": config.ATS_SCANNER_PROMPT_VERSION,
        "recruiter_scanner": config.RECRUITER_SCANNER_PROMPT_VERSION,
    }[kind]


# --- structured outputs -----------------------------------------------------


class AtsCriterion(BaseModel):
    criterion: str
    category: Literal["skill", "tool", "domain", "responsibility", "qualification"]
    required: bool
    keywords: list[str] = Field(default_factory=list)


class AtsCriteria(BaseModel):
    criteria: list[AtsCriterion] = Field(default_factory=list)


class Coverage(BaseModel):
    a: bool
    b: bool


class AtsVerdict(BaseModel):
    coverage: list[Coverage] = Field(default_factory=list)
    winner: Literal["A", "B", "tie"]
    reasons: str


class RecruiterVerdict(BaseModel):
    winner: Literal["A", "B", "tie"]
    reasons: str


@dataclass
class ScanResult:
    output: dict
    model: str
    prompt_version: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    # True when no model call was made (identical drafts).
    skipped: bool = False


# --- rendering --------------------------------------------------------------


def render_draft(draft: dict, *, refs: bool = False) -> str:
    """A draft as plain text for a judge. With refs, every header and bullet
    is labeled ([fet_am.header], [fet_am.2]) so the hard gate can point at
    specific lines."""
    lines = [f"Headline: {draft.get('headline') or '(none)'}", ""]
    for section in draft.get("sections", []):
        slot = section["slot"]
        lines.append(f"## {SLOT_LABELS.get(slot, slot)}")
        header = section.get("header")
        if header:
            prefix = f"[{slot}.header] " if refs else ""
            lines.append(f"{prefix}Role: {header['text']}")
        for i, bullet in enumerate(section.get("bullets", []), start=1):
            prefix = f"[{slot}.{i}] " if refs else ""
            lines.append(f"- {prefix}{bullet['text']}")
        lines.append("")
    return "\n".join(lines).rstrip()


def recruiter_view(draft: dict) -> dict:
    """What a six-second skim sees: the headline, and the first two
    experience sections with their role header and first two bullets."""
    experience = [s for s in draft.get("sections", []) if s["slot"] not in NON_EXPERIENCE_SLOTS]
    return {
        "headline": draft.get("headline"),
        "sections": [
            {"slot": s["slot"], "header": s.get("header"), "bullets": s.get("bullets", [])[:2]} for s in experience[:2]
        ],
    }


def recruiter_positions(draft: dict) -> list[str]:
    """The swappable positions inside recruiter_view, as the assembler's own
    references ("acme.header", "acme.1"). The headline is left out:
    the assembler has no tool that changes it."""
    positions = []
    for section in recruiter_view(draft)["sections"]:
        if section.get("header"):
            positions.append(f"{section['slot']}.header")
        positions += [f"{section['slot']}.{i}" for i in range(1, len(section["bullets"]) + 1)]
    return positions


def _render_criteria(criteria: list[dict]) -> str:
    lines = []
    for i, c in enumerate(criteria, start=1):
        kind = "REQUIRED" if c["required"] else "preferred"
        keywords = ", ".join(c.get("keywords") or [])
        lines.append(f"{i}. [{kind}] {c['criterion']} (keywords: {keywords})")
    return "\n".join(lines)


# --- the model call ---------------------------------------------------------


def _client():
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover
        raise ScannerUnavailable("anthropic package is not installed") from exc
    return anthropic.Anthropic()


def _call(kind: str, user_content: str, output_format, *, client, model: str | None, max_tokens: int):
    model = model or config.SCANNER_MODEL
    version = active_version(kind)
    system = load_prompt(kind, version)
    client = client or _client()
    try:
        response = client.messages.parse(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_content}],
            output_format=output_format,
            thinking={"type": "disabled"},
        )
    except TypeError as exc:
        if "authentication" in str(exc).lower():
            raise ScannerUnavailable(NO_CREDENTIALS) from exc
        raise
    except Exception as exc:
        if type(exc).__name__ in {"AuthenticationError", "PermissionDeniedError"}:
            raise ScannerUnavailable(NO_CREDENTIALS) from exc
        raise

    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "input_tokens", None)
    output_tokens = getattr(usage, "output_tokens", None)
    return response.parsed_output, model, version, input_tokens, output_tokens, price(model, input_tokens, output_tokens)


# --- the four scanners ------------------------------------------------------


def build_ats_criteria(normalized, *, client=None, model: str | None = None) -> ScanResult:
    parsed, model, version, tin, tout, cost = _call(
        "ats_criteria", _render_job(normalized), AtsCriteria, client=client, model=model, max_tokens=2048
    )
    return ScanResult(
        output={"criteria": [c.model_dump() for c in parsed.criteria]},
        model=model,
        prompt_version=version,
        input_tokens=tin,
        output_tokens=tout,
        cost_usd=cost,
    )


def _pairwise(
    kind: str,
    criteria: list[dict],
    anchor_text: str,
    candidate_text: str,
    output_format,
    *,
    client,
    model: str | None,
    rng: random.Random | None,
    role_summary: list[str] | None = None,
) -> tuple[ScanResult, dict]:
    """Shared A/B handling. Returns the result plus the raw parsed verdict and
    which side was A, for the caller to map scanner-specific fields back."""
    if anchor_text == candidate_text:
        return (
            ScanResult(
                output={
                    "winner": "tie",
                    "passed": False,
                    # Precise on purpose: for the recruiter, only the top of
                    # the resume is compared, so "identical" means that slice.
                    "reasons": "Everything this scanner reads is identical in both versions — nothing to compare. "
                    + (
                        "It only reads the headline and the first two bullets of the two most recent roles."
                        if kind == "recruiter_scanner"
                        else ""
                    ),
                },
                model=model or config.SCANNER_MODEL,
                prompt_version=active_version(kind),
                input_tokens=0,
                output_tokens=0,
                cost_usd=0.0,
                skipped=True,
            ),
            {},
        )

    candidate_is_a = (rng or random).random() < 0.5
    a_text, b_text = (candidate_text, anchor_text) if candidate_is_a else (anchor_text, candidate_text)
    about = (
        "About the role (the posting's own words):\n" + "\n".join(f"- {s}" for s in role_summary) + "\n\n"
        if role_summary
        else ""
    )
    user = (
        f"{about}Screening criteria:\n{_render_criteria(criteria)}\n\n"
        f"=== Resume A ===\n{a_text}\n\n=== Resume B ===\n{b_text}"
    )
    parsed, model, version, tin, tout, cost = _call(
        kind, user, output_format, client=client, model=model, max_tokens=2048
    )

    side = {"A": "candidate" if candidate_is_a else "anchor", "B": "anchor" if candidate_is_a else "candidate"}
    winner = "tie" if parsed.winner == "tie" else side[parsed.winner]
    result = ScanResult(
        output={
            "winner": winner,
            "passed": winner == "candidate",
            "reasons": parsed.reasons,
            # The reasons text refers to A and B — this says which was which.
            "labels": side,
        },
        model=model,
        prompt_version=version,
        input_tokens=tin,
        output_tokens=tout,
        cost_usd=cost,
    )
    return result, {"parsed": parsed, "candidate_is_a": candidate_is_a}


def run_ats_scan(
    criteria: list[dict],
    anchor: dict,
    candidate: dict,
    *,
    client=None,
    model: str | None = None,
    rng: random.Random | None = None,
) -> ScanResult:
    result, raw = _pairwise(
        "ats_scanner",
        criteria,
        render_draft(anchor),
        render_draft(candidate),
        AtsVerdict,
        client=client,
        model=model,
        rng=rng,
    )
    if raw:
        candidate_is_a = raw["candidate_is_a"]
        result.output["coverage"] = [
            {
                "criterion": c["criterion"],
                "required": c["required"],
                "candidate": (cov.a if candidate_is_a else cov.b),
                "anchor": (cov.b if candidate_is_a else cov.a),
            }
            for c, cov in zip(criteria, raw["parsed"].coverage)
        ]
    return result


def run_recruiter_scan(
    criteria: list[dict],
    anchor: dict,
    candidate: dict,
    *,
    role_summary: list[str] | None = None,
    client=None,
    model: str | None = None,
    rng: random.Random | None = None,
) -> ScanResult:
    result, _ = _pairwise(
        "recruiter_scanner",
        criteria,
        render_draft(recruiter_view(anchor)),
        render_draft(recruiter_view(candidate)),
        RecruiterVerdict,
        client=client,
        model=model,
        rng=rng,
        role_summary=role_summary,
    )
    # Named positions, not a description of them: on a Lime run Haiku made 13
    # swaps, all below these lines, and every recruiter scan came back an
    # identical tie that could never pass.
    positions = recruiter_positions(candidate)
    result.output["reads"] = positions
    if result.skipped:
        result.output["reasons"] += (
            " Every swap so far is outside what it reads, so this verdict cannot change until you swap into "
            f"one of: {', '.join(positions)}."
        )
    return result


def run_hard_gate_scan(draft: dict) -> ScanResult:
    """Every line in the draft must be a stored line, verbatim, from the same
    section slot it now sits in. Defects are `unknown_origin` (the source line
    doesn't exist), `altered` (text differs from its source), or
    `wrong_section` (taken from a different slot)."""
    defects = []
    with session_scope() as session:
        for section in draft.get("sections", []):
            slot = section["slot"]

            header = section.get("header")
            if header:
                source = session.get(Section, f"{header['source_resume_id']}/{slot}")
                ref = f"{slot}.header"
                if source is None:
                    defects.append(
                        {"kind": "unknown_origin", "refs": [ref],
                         "detail": f"{header['source_resume_id']} has no {slot} section to take this header from."}
                    )
                elif source.header != header["text"]:
                    defects.append(
                        {"kind": "altered", "refs": [ref],
                         "detail": f"Header text differs from {header['source_resume_id']}'s {slot} header."}
                    )

            for i, bullet in enumerate(section.get("bullets", []), start=1):
                ref = f"{slot}.{i}"
                source = session.get(Bullet, bullet["source_bullet_id"])
                if source is None:
                    defects.append(
                        {"kind": "unknown_origin", "refs": [ref],
                         "detail": f"No stored bullet {bullet['source_bullet_id']}."}
                    )
                elif source.text != bullet["text"]:
                    defects.append(
                        {"kind": "altered", "refs": [ref],
                         "detail": f"Text differs from its source bullet {bullet['source_bullet_id']}."}
                    )
                elif source.section_id != f"{bullet['source_resume_id']}/{slot}":
                    defects.append(
                        {"kind": "wrong_section", "refs": [ref],
                         "detail": f"Taken from {source.section_id}, placed under {slot}."}
                    )

    return ScanResult(
        output={"passed": not defects, "defects": defects},
        model="code",
        prompt_version="none",
        input_tokens=0,
        output_tokens=0,
        cost_usd=0.0,
    )
