"""Resume Assembler: seed, working-copy draft, and the run/turn log.

Phase 1 of the assembler — no LLM calls here. This module picks the starting
resumes and lays down the storage the agent loop (and the live tracer) will
write to and read from.

Seeding uses JD-vs-JD similarity as routing, not as a judgment of resume
quality: the closest past *roles* to this posting are found first, and the
resumes approved for those roles become the starting material. Walking the
ranking top-down and skipping roles with no resume on file means the seed
degrades gracefully while the resume backfill is still in progress.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import literal_column, select
from sqlalchemy.orm import Session

from app.db import session_scope
from app.models import ROLE_CATEGORIES, Application, AssemblyRun, AssemblyTurn, Bullet, Job, Resume, Section
from app.resume_ingest_service import SLOT_DISPLAY_ORDER
from app.similarity_service import find_similar_applications

SEED_SIZE = 3
# find_similar_applications truncates to top_n; the seed needs the whole
# ranking to walk past roles with no resume.
_FULL_RANKING = 10_000


class AssemblerUnavailable(Exception):
    pass


def ranked_candidates(source: str, job_id: str) -> list[dict]:
    """Every similar past application, most similar first, each with the
    resume attached to it (resume_id None when there isn't one)."""
    ranking = find_similar_applications(source, job_id, top_n=_FULL_RANKING)["overall"]
    with session_scope() as session:
        resume_by_application = {
            application_id: resume_id
            for resume_id, application_id in session.execute(
                select(Resume.id, Resume.application_id).where(Resume.application_id.is_not(None))
            )
        }
    return [
        {
            "application_id": match["application_id"],
            "resume_id": resume_by_application.get(match["application_id"]),
            "company": match["company"],
            "title": match["title"],
            "score": match["score"],
            "reason": "similar",
        }
        for match in ranking
    ]


def latest_by_category() -> dict[str, dict]:
    """Each role category's newest resume, as a seed candidate.

    Newest by the date in the resume's filename; a same-day tie goes to the
    later upload (SQLite rowid). Categories with no resume are absent.
    """
    with session_scope() as session:
        rows = session.execute(
            select(Application.role, Resume.id, Resume.application_id, Application.company, Application.title)
            .join(Application, Application.id == Resume.application_id)
            .where(Application.role.in_(ROLE_CATEGORIES))
            .order_by(Resume.resume_date.desc(), literal_column("resumes.rowid").desc())
        ).all()
    latest: dict[str, dict] = {}
    for role, resume_id, application_id, company, title in rows:
        latest.setdefault(
            role,
            {
                "application_id": application_id,
                "resume_id": resume_id,
                "company": company,
                "title": title,
                "score": None,
                "reason": f"latest {role}",
            },
        )
    return latest


def seed(source: str, job_id: str) -> dict:
    """The anchor and donors for this posting.

    The top SEED_SIZE resumes by role similarity come first — the most
    similar is the anchor. Then each role category's newest resume joins as
    a donor, unless it is already in, so a run always has material from
    every kind of role the candidate has written for, not just the three
    nearest (which can be near-copies of one another).

    Returns {"anchor": candidate, "donors": [candidate, ...], "ranked": [...]}
    where each candidate is {application_id, resume_id, company, title,
    score, reason}, and "ranked" is every candidate walked, including
    skipped ones (resume_id None) up to the point the similarity seed filled.
    reason is "similar" or "latest <category>"; score is None for a
    category donor that is not in the similarity ranking.
    """
    ranking = ranked_candidates(source, job_id)
    if not ranking:
        raise AssemblerUnavailable("no similar past applications — this posting may have no embeddings yet")

    picked: list[dict] = []
    walked: list[dict] = []
    for candidate in ranking:
        walked.append(candidate)
        if candidate["resume_id"] is not None:
            picked.append(candidate)
            if len(picked) == SEED_SIZE:
                break

    if not picked:
        raise AssemblerUnavailable(
            "none of the similar past applications has a resume on file — attach some in Needs JD / Resume"
        )

    scores = {c["application_id"]: c["score"] for c in ranking}
    in_seed = {c["resume_id"] for c in picked}
    latest = latest_by_category()
    for role in ROLE_CATEGORIES:
        candidate = latest.get(role)
        if candidate and candidate["resume_id"] not in in_seed:
            picked.append({**candidate, "score": scores.get(candidate["application_id"])})
            in_seed.add(candidate["resume_id"])

    return {"anchor": picked[0], "donors": picked[1:], "ranked": walked}


def load_draft(session: Session, resume_id: str) -> dict:
    """A resume as an assembler draft: sections in print order, every header
    and bullet tagged with where it came from."""
    by_slot = {s.slot: s for s in session.query(Section).filter_by(resume_id=resume_id).all()}
    ordered = [slot for slot in SLOT_DISPLAY_ORDER if slot in by_slot]
    ordered += [slot for slot in by_slot if slot not in SLOT_DISPLAY_ORDER]

    sections = []
    for slot in ordered:
        section = by_slot[slot]
        bullets = session.query(Bullet).filter_by(section_id=section.id).order_by(Bullet.position).all()
        sections.append(
            {
                "slot": slot,
                "header": (
                    {"text": section.header, "source_resume_id": resume_id} if section.header is not None else None
                ),
                "bullets": [
                    {"text": b.text, "source_resume_id": resume_id, "source_bullet_id": b.id} for b in bullets
                ],
            }
        )
    # The headline is carried as-is: swaps are header-for-header and
    # bullet-for-bullet only, never the headline.
    return {"headline": session.get(Resume, resume_id).headline, "sections": sections}


def create_run(source: str, job_id: str) -> int:
    """Seed a run and lay down its working copy — a copy of the anchor."""
    picked = seed(source, job_id)
    anchor_id = picked["anchor"]["resume_id"]

    with session_scope() as session:
        job = session.get(Job, (source, job_id))
        if job is None:
            raise AssemblerUnavailable(f"no stored job {source}/{job_id}")

        run = AssemblyRun(
            source=source,
            job_id=job_id,
            company=job.company,
            title=job.title,
            anchor_resume_id=anchor_id,
            donor_resume_ids=[d["resume_id"] for d in picked["donors"]],
            seed=picked,
            draft=load_draft(session, anchor_id),
            status="seeded",
        )
        session.add(run)
        session.flush()
        run_id = run.id

    log_turn(run_id, kind="system", tool_name="seed", result=picked)
    return run_id


def log_turn(
    run_id: int,
    *,
    kind: str,
    tool_name: str | None = None,
    payload: dict | None = None,
    result: dict | None = None,
    model: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost_usd: float | None = None,
) -> None:
    """Append one step to a run's trace, committed immediately so a poller
    sees it while the run is still going. Token/cost totals on the run row
    are kept in step here, so the tracer's running cost is never a sum it
    has to compute itself."""
    with session_scope() as session:
        run = session.get(AssemblyRun, run_id)
        seq = session.query(AssemblyTurn).filter_by(run_id=run_id).count() + 1
        session.add(
            AssemblyTurn(
                run_id=run_id,
                seq=seq,
                kind=kind,
                tool_name=tool_name,
                payload=payload,
                result=result,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
            )
        )
        run.input_tokens += input_tokens or 0
        run.output_tokens += output_tokens or 0
        run.cost_usd = round(run.cost_usd + (cost_usd or 0.0), 6)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _run_as_dict(run: AssemblyRun) -> dict:
    return {
        "id": run.id,
        "source": run.source,
        "job_id": run.job_id,
        "company": run.company,
        "title": run.title,
        "anchor_resume_id": run.anchor_resume_id,
        "donor_resume_ids": run.donor_resume_ids,
        "seed": run.seed,
        "draft": run.draft,
        "status": run.status,
        "rounds_used": run.rounds_used,
        "turns_used": run.turns_used,
        "verdicts": run.verdicts,
        "prompt_versions": run.prompt_versions,
        "error": run.error,
        "input_tokens": run.input_tokens,
        "output_tokens": run.output_tokens,
        "cost_usd": run.cost_usd,
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
    }


def get_run(run_id: int) -> dict | None:
    """A run and its full trace, in order — what the tracer polls."""
    with session_scope() as session:
        run = session.get(AssemblyRun, run_id)
        if run is None:
            return None
        turns = session.query(AssemblyTurn).filter_by(run_id=run_id).order_by(AssemblyTurn.seq).all()
        result = _run_as_dict(run)
        result["turns"] = [
            {
                "seq": t.seq,
                "kind": t.kind,
                "tool_name": t.tool_name,
                "payload": t.payload,
                "result": t.result,
                "model": t.model,
                "input_tokens": t.input_tokens,
                "output_tokens": t.output_tokens,
                "cost_usd": t.cost_usd,
                "created_at": _iso(t.created_at),
            }
            for t in turns
        ]
        return result


def list_runs() -> list[dict]:
    """Every run, newest first, without turns."""
    with session_scope() as session:
        runs = session.query(AssemblyRun).order_by(AssemblyRun.id.desc()).all()
        return [_run_as_dict(r) for r in runs]


def update_run(run_id: int, **fields) -> None:
    """Write run-level state (draft, counters, verdicts) the moment it
    changes, so the tracer's view of the draft is live too."""
    with session_scope() as session:
        run = session.get(AssemblyRun, run_id)
        for name, value in fields.items():
            setattr(run, name, value)


def finish_run(run_id: int, *, status: str, error: str | None = None) -> None:
    with session_scope() as session:
        run = session.get(AssemblyRun, run_id)
        run.status = status
        run.error = error
        run.finished_at = datetime.now(timezone.utc)


def total_assembler_cost() -> float:
    with session_scope() as session:
        return round(sum(cost or 0.0 for (cost,) in session.query(AssemblyRun.cost_usd).all()), 6)
