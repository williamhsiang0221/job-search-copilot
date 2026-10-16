"""Fetch job descriptions, store them, and normalize them.

Fetching and normalizing are separate failures. A description that downloads
but cannot be normalized is still worth keeping — refetching costs a request
against an undocumented endpoint, whereas re-normalizing is a cheap local
retry. So the description is committed first, and normalization runs against
the stored copy.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Callable

from sqlalchemy import select

from app.db import session_scope
from app.embeddings_service import EmbeddingUnavailable, embed_normalized_job
from app.jd_sources import FetchedJob, JobDescriptionError, JobDescriptionSource, fetch_many
from app.models import Job, JobNormalized, _now
from app.normalizer import NormalizerUnavailable, normalize


@dataclass
class FetchReport:
    stored: list[str] = field(default_factory=list)
    normalized: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failures: dict[str, str] = field(default_factory=dict)
    normalize_failures: dict[str, str] = field(default_factory=dict)
    # Best-effort, same as normalize_failures: an embedding failure never
    # blocks storing or normalizing a job, since it is purely additive on top.
    embedding_failures: dict[str, str] = field(default_factory=dict)
    # role_summary sentences dropped because they were not in the posting.
    role_summary_rejected: dict[str, list[str]] = field(default_factory=dict)
    cost_usd: float = 0.0

    def as_dict(self) -> dict:
        return {
            "stored": self.stored,
            "normalized": self.normalized,
            "skipped": self.skipped,
            "failures": self.failures,
            "normalize_failures": self.normalize_failures,
            "embedding_failures": self.embedding_failures,
            "counts": {
                "stored": len(self.stored),
                "normalized": len(self.normalized),
                "skipped": len(self.skipped),
                "failed": len(self.failures),
                "normalize_failed": len(self.normalize_failures),
                "embedding_failed": len(self.embedding_failures),
            },
        }


def ready_job_ids(source: str, job_ids: list[str]) -> set[str]:
    """Which of these already have normalized fields.

    Readiness is measured against job_normalized rather than jobs: a posting
    whose download succeeded but whose normalization failed is not finished,
    and should stay selectable so it can be retried.
    """
    if not job_ids:
        return set()

    with session_scope() as session:
        rows = session.execute(
            select(JobNormalized.job_id).where(
                JobNormalized.source == source, JobNormalized.job_id.in_(job_ids)
            )
        ).scalars()
        return set(rows)


def _store(session, fetched: FetchedJob) -> None:
    session.merge(
        Job(
            source=fetched.source,
            job_id=fetched.job_id,
            title=fetched.title,
            company=fetched.company,
            location=fetched.location,
            url=fetched.url,
            apply_url=fetched.apply_url,
            posted_at=fetched.posted_at,
            posted_at_is_approximate=fetched.posted_at_is_approximate,
            description_raw=fetched.description_raw,
            level_raw=fetched.level_raw,
            employment_type_raw=fetched.employment_type_raw,
            workplace_raw=fetched.workplace_raw,
            department=fetched.department,
            team=fetched.team,
            job_function=fetched.job_function,
            industries=fetched.industries,
            salary_text=fetched.salary_text,
        )
    )


def linkedin_fetch_available() -> bool:
    """Whether this build includes the LinkedIn guest-endpoint source
    (app/linkedin_guest.py) — the public build does not."""
    return importlib.util.find_spec("app.linkedin_guest") is not None


def _linkedin_source() -> JobDescriptionSource:
    if not linkedin_fetch_available():
        raise JobDescriptionError("LinkedIn description fetch is not included in this build")
    from app.linkedin_guest import LinkedInSource

    return LinkedInSource()


def fetch_and_store(
    job_ids: list[str],
    source: JobDescriptionSource | None = None,
    *,
    delay_seconds: float = 1.0,
    skip_existing: bool = True,
    on_progress: Callable[[str], None] | None = None,
) -> FetchReport:
    source = source or _linkedin_source()
    report = FetchReport()

    wanted = list(dict.fromkeys(job_ids))  # de-duplicate, keep order
    if skip_existing:
        already = ready_job_ids(source.name, wanted)
        report.skipped = [j for j in wanted if j in already]
        wanted = [j for j in wanted if j not in already]

    # Already-skipped ids resolve instantly — count them as done right away
    # rather than leaving a caller's progress bar stuck below 100%.
    if on_progress:
        for job_id in report.skipped:
            on_progress(job_id)

    if not wanted:
        return report

    fetched, failures = fetch_many(
        source, wanted, delay_seconds=delay_seconds, on_progress=on_progress
    )
    report.failures.update(failures)

    # Commit descriptions before normalizing, so a normalizer outage never
    # costs a request against the source.
    with session_scope() as session:
        for job in fetched:
            _store(session, job)
            report.stored.append(job.job_id)

    for job in fetched:
        _normalize_and_store(job, report)

    return report


def _normalize_and_store(job, report: FetchReport) -> None:
    """Normalize one stored posting and write its job_normalized row.

    `job` is anything with the stored posting's fields — a fresh FetchedJob,
    or a snapshot of a Job row when re-normalizing. Failures are recorded on
    the report, never raised, so one bad posting never stops a batch.
    """
    try:
        result = normalize(job.description_raw, title=job.title, company=job.company)
    except NormalizerUnavailable as exc:
        report.normalize_failures[job.job_id] = str(exc)
        return
    except Exception as exc:
        report.normalize_failures[job.job_id] = f"{type(exc).__name__}: {exc}"
        return
    rejected = getattr(result, "role_summary_rejected", None)
    if rejected:
        report.role_summary_rejected[job.job_id] = rejected
    report.cost_usd += getattr(result, "cost_usd", None) or 0

    embedding = None
    try:
        embedding = embed_normalized_job(
            result.normalized.responsibilities, result.normalized.qualifications
        )
    except EmbeddingUnavailable as exc:
        report.embedding_failures[job.job_id] = str(exc)
    except Exception as exc:
        report.embedding_failures[job.job_id] = f"{type(exc).__name__}: {exc}"

    with session_scope() as session:
        session.merge(
            JobNormalized(
                source=job.source,
                job_id=job.job_id,
                # Copied from Job on purpose: the evaluator reads this
                # table on its own.
                title=job.title,
                company=job.company,
                posted_at=job.posted_at,
                responsibilities=result.normalized.responsibilities,
                qualifications=result.normalized.qualifications,
                comp_min=result.normalized.comp_min,
                comp_max=result.normalized.comp_max,
                # Prefer what the board stated over anything inferred.
                workplace=job.workplace_raw or result.normalized.workplace,
                role_summary=result.normalized.role_summary,
                # Set explicitly: a merge onto an existing row would otherwise
                # keep the first normalization's timestamp.
                normalized_at=_now(),
                model=result.model,
                normalizer_version=result.prompt_version,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                cost_usd=result.cost_usd,
                responsibilities_embedding=embedding.responsibilities_embedding if embedding else None,
                qualifications_embedding=embedding.qualifications_embedding if embedding else None,
                embedding_input_tokens=embedding.input_tokens if embedding else None,
                embedding_cost_usd=embedding.cost_usd if embedding else None,
            )
        )
    report.normalized.append(job.job_id)


def renormalize(keys: list[tuple[str, str]]) -> FetchReport:
    """Re-run the current normalizer over already-stored postings.

    No request to any job board: the raw description is always kept, so a
    normalizer change never needs a refetch. Overwrites each job_normalized
    row, stamping the new normalizer_version.
    """
    report = FetchReport()
    for source, job_id in dict.fromkeys(keys):
        with session_scope() as session:
            row = session.get(Job, (source, job_id))
            if row is None or not (row.description_raw or "").strip():
                report.failures[job_id] = "no stored description"
                continue
            snapshot = SimpleNamespace(
                source=row.source,
                job_id=row.job_id,
                title=row.title,
                company=row.company,
                posted_at=row.posted_at,
                workplace_raw=row.workplace_raw,
                description_raw=row.description_raw,
            )
        _normalize_and_store(snapshot, report)
    return report


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def list_jobs(source: str | None = None) -> list[dict]:
    """Every stored job, exactly as the source published it.

    The full description is included rather than a preview. This view exists to
    show what the database actually holds — when a normalization looks wrong,
    the raw text is what settles it.
    """
    with session_scope() as session:
        query = session.query(Job)
        if source:
            query = query.filter(Job.source == source)

        return [
            {
                "source": job.source,
                "job_id": job.job_id,
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "url": job.url,
                "apply_url": job.apply_url,
                "posted_at": _iso(job.posted_at),
                "posted_at_is_approximate": job.posted_at_is_approximate,
                "description_raw": job.description_raw,
                "description_chars": len(job.description_raw or ""),
                "level_raw": job.level_raw,
                "employment_type_raw": job.employment_type_raw,
                "workplace_raw": job.workplace_raw,
                "department": job.department,
                "team": job.team,
                "job_function": job.job_function,
                "industries": job.industries,
                "salary_text": job.salary_text,
                "fetched_at": _iso(job.fetched_at),
            }
            for job in query.order_by(Job.fetched_at.desc()).all()
        ]


def list_normalized(source: str | None = None) -> list[dict]:
    """Every normalized row — what the model extracted.

    normalizer_version is included deliberately: it is the only way to tell
    which rows came from which prompt wording once that wording changes.
    """
    with session_scope() as session:
        query = session.query(JobNormalized)
        if source:
            query = query.filter(JobNormalized.source == source)

        return [
            {
                "source": row.source,
                "job_id": row.job_id,
                "title": row.title,
                "company": row.company,
                "posted_at": _iso(row.posted_at),
                "responsibilities": row.responsibilities or [],
                "qualifications": row.qualifications or [],
                "comp_min": row.comp_min,
                "comp_max": row.comp_max,
                "workplace": row.workplace,
                "role_summary": row.role_summary,
                "model": row.model,
                "normalizer_version": row.normalizer_version,
                "normalized_at": _iso(row.normalized_at),
            }
            for row in query.order_by(JobNormalized.normalized_at.desc()).all()
        ]


def total_normalize_cost() -> float:
    """Sum of every normalize call's cost_usd, treating a null (rows
    normalized before cost tracking was added) as zero."""
    with session_scope() as session:
        values = session.execute(select(JobNormalized.cost_usd)).scalars().all()
        return round(sum(v or 0.0 for v in values), 6)


def total_embedding_cost() -> float:
    """Sum of every embedding call's cost_usd, treating a null (rows
    normalized before embeddings existed, or where the call failed) as zero."""
    with session_scope() as session:
        values = session.execute(select(JobNormalized.embedding_cost_usd)).scalars().all()
        return round(sum(v or 0.0 for v in values), 6)
