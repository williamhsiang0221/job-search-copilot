"""Running evaluations and reading them back.

Every run appends. A job evaluated under v1 and again under v2 keeps both rows,
because a rubric change makes verdicts incomparable and the only way to tell
which is which is the version stamped on the row.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from sqlalchemy import select

from app import config
from app.db import session_scope
from app.evaluator import EvaluatorUnavailable, evaluate
from app.models import Evaluation, EvaluationScore, Job, JobNormalized, _now

# Between calls, matching the fetch path. Nothing has been tried at volume.
DELAY_SECONDS = 0.5


@dataclass
class EvaluationReport:
    evaluated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failures: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "evaluated": self.evaluated,
            "skipped": self.skipped,
            "failures": self.failures,
        }


def evaluated_job_ids(source: str, job_ids: list[str], rubric_version: str) -> set[str]:
    """Which of these already have an evaluation under this rubric version."""
    if not job_ids:
        return set()
    with session_scope() as session:
        rows = session.execute(
            select(Evaluation.job_id)
            .where(Evaluation.source == source)
            .where(Evaluation.job_id.in_(job_ids))
            .where(Evaluation.rubric_version == rubric_version)
        ).all()
    return {r[0] for r in rows}


def evaluate_jobs(
    job_ids: list[str],
    *,
    source: str = "linkedin",
    rubric_version: str | None = None,
    skip_existing: bool = True,
    delay_seconds: float = DELAY_SECONDS,
    on_progress: Callable[[str], None] | None = None,
) -> EvaluationReport:
    """Evaluate stored jobs one at a time.

    Sequential with a pause, and one failure never aborts the batch — the same
    shape as fetching, for the same reason: a partial run that reports what it
    managed is more useful than an all-or-nothing one.

    on_progress, if given, is called with each job_id right after it resolves
    (skipped, evaluated, or failed) — the hook a caller polls to show live
    "N of M" progress.
    """
    rubric_version = rubric_version or config.EVALUATOR_RUBRIC_VERSION
    report = EvaluationReport()

    wanted = list(dict.fromkeys(job_ids))
    if skip_existing:
        already = evaluated_job_ids(source, wanted, rubric_version)
        report.skipped = [j for j in wanted if j in already]
        wanted = [j for j in wanted if j not in already]

    # Already-skipped ids resolve instantly — count them as done right away
    # rather than leaving a caller's progress bar stuck below 100%.
    if on_progress:
        for job_id in report.skipped:
            on_progress(job_id)

    for index, job_id in enumerate(wanted):
        with session_scope() as session:
            normalized = session.get(JobNormalized, (source, job_id))
            if normalized is None:
                report.failures[job_id] = "not normalized yet"
                if on_progress:
                    on_progress(job_id)
                continue
            job = session.get(Job, (source, job_id))
            # Detach a plain copy so the model call happens outside the session.
            snapshot = _snapshot(normalized, location=job.location if job else "")

        if index:
            time.sleep(delay_seconds)

        try:
            result = evaluate(snapshot, rubric_version=rubric_version)
        except EvaluatorUnavailable as exc:
            report.failures[job_id] = str(exc)
            if on_progress:
                on_progress(job_id)
            continue
        except Exception as exc:
            report.failures[job_id] = f"{type(exc).__name__}: {exc}"
            if on_progress:
                on_progress(job_id)
            continue

        with session_scope() as session:
            row = Evaluation(
                source=source,
                job_id=job_id,
                rubric_version=result.rubric_version,
                score_1=result.score_1,
                score_2=result.score_2,
                verdict=result.verdict,
                disqualifier=result.disqualifier,
                reasoning=result.reasoning,
                model=result.model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                cost_usd=result.cost_usd,
                latency_ms=result.latency_ms,
            )
            row.scores = [
                EvaluationScore(
                    code=s.code,
                    score=s.score,
                    weight=s.weight,
                    abstained=s.abstained,
                    rationale=s.rationale,
                )
                for s in result.sub_scores
            ]
            session.add(row)

        report.evaluated.append(job_id)
        if on_progress:
            on_progress(job_id)

    return report


@dataclass
class _Snapshot:
    """A normalized job detached from its session, for the model call.

    location comes from the raw Job row, not JobNormalized — the normalizer
    never extracts a city, only the coarse workplace (remote/hybrid/onsite),
    so 4d would otherwise have nothing but that to score against.
    """

    source: str
    job_id: str
    title: str
    company: str
    responsibilities: list
    qualifications: list
    comp_min: int | None
    comp_max: int | None
    workplace: str | None
    location: str


def _snapshot(row: JobNormalized, *, location: str) -> _Snapshot:
    return _Snapshot(
        source=row.source,
        job_id=row.job_id,
        title=row.title,
        company=row.company,
        responsibilities=list(row.responsibilities or []),
        qualifications=list(row.qualifications or []),
        comp_min=row.comp_min,
        comp_max=row.comp_max,
        workplace=row.workplace,
        location=location,
    )


def list_evaluations(source: str | None = None) -> list[dict]:
    """Every evaluation, newest first, with its sub-scores.

    Title and company come from job_normalized rather than being copied onto
    the evaluation row: a verdict is about a job, and duplicating the job's
    identity here would create a second place for it to go stale.
    """
    with session_scope() as session:
        query = session.query(Evaluation, JobNormalized).join(
            JobNormalized,
            (Evaluation.source == JobNormalized.source)
            & (Evaluation.job_id == JobNormalized.job_id),
        )
        if source:
            query = query.filter(Evaluation.source == source)

        return [
            {
                "id": row.id,
                "source": row.source,
                "job_id": row.job_id,
                "title": normalized.title,
                "company": normalized.company,
                "rubric_version": row.rubric_version,
                "score_1": row.score_1,
                "score_2": row.score_2,
                "verdict": row.verdict,
                "disqualifier": row.disqualifier,
                "reasoning": row.reasoning,
                "model": row.model,
                "input_tokens": row.input_tokens,
                "output_tokens": row.output_tokens,
                "cost_usd": row.cost_usd,
                "latency_ms": row.latency_ms,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "note": row.note,
                "note_updated_at": row.note_updated_at.isoformat() if row.note_updated_at else None,
                "scores": [
                    {
                        "code": s.code,
                        "score": s.score,
                        "weight": s.weight,
                        "abstained": s.abstained,
                        "rationale": s.rationale,
                    }
                    for s in sorted(row.scores, key=lambda s: s.code)
                ],
            }
            for row, normalized in query.order_by(Evaluation.created_at.desc()).all()
        ]


def set_evaluation_note(evaluation_id: int, note: str | None) -> dict | None:
    """Save (or clear, with blank text) the user's note on one evaluation.
    None if there is no such evaluation."""
    text = (note or "").strip() or None
    with session_scope() as session:
        row = session.get(Evaluation, evaluation_id)
        if row is None:
            return None
        row.note = text
        row.note_updated_at = _now() if text else None
        # Read back what was stored, so this matches what list_evaluations
        # returns (SQLite drops the timezone on the way in).
        session.flush()
        session.refresh(row)
        return {
            "id": row.id,
            "note": row.note,
            "note_updated_at": row.note_updated_at.isoformat() if row.note_updated_at else None,
        }


def total_evaluation_cost() -> float:
    """Sum of every evaluation's cost_usd, treating a null as zero."""
    with session_scope() as session:
        values = session.execute(select(Evaluation.cost_usd)).scalars().all()
        return round(sum(v or 0.0 for v in values), 6)
