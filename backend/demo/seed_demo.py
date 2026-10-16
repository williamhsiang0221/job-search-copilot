#!/usr/bin/env python
"""Build the demo database: a fictional candidate's job search, end to end.

    cd backend && .venv/bin/python demo/seed_demo.py

Writes backend/demo.db (gitignored) and nothing else — it refuses to touch
jobs.db. Runs with the fictional example profile. Wherever the app would call
a model, the real code path runs with a scripted stand-in for the model, so
the stored results — weighted scores, gates, verdicts, parsed resumes, the
Assembler's validated swaps and trace — are what the app itself produces.
No API calls, no cost, same result every run.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

BACKEND = Path(__file__).resolve().parent.parent
DEMO_DB = BACKEND / "demo.db"

# Before any app import: the app reads these when its config module loads.
os.environ["JOB_BOARD_DB"] = str(DEMO_DB)
os.environ["JOB_BOARD_PROFILE"] = str(BACKEND / "profile.example")
os.environ["USE_FIXTURES"] = "1"
sys.path.insert(0, str(BACKEND))

from app import config  # noqa: E402

if config.DB_PATH.resolve() != DEMO_DB.resolve() or config.DB_PATH.name == "jobs.db":
    sys.exit(f"Refusing to seed {config.DB_PATH}: the demo only ever writes {DEMO_DB}.")

import app.evaluator as evaluator  # noqa: E402
import app.resume_ingest_service as resume_ingest  # noqa: E402
import app.resume_service as resume_service  # noqa: E402
from app import assembler_service, bullet_bank_service, bullet_tagger_service, db  # noqa: E402
from app.assembler_agent import run_assembly  # noqa: E402
from app.evaluations_service import evaluate_jobs, set_evaluation_note  # noqa: E402
from app.models import Application, Evaluation, Job, JobNormalized, TrackedCompany  # noqa: E402
from app.resume_service import ExperienceEntry, IcpResumeDraft  # noqa: E402
from app.scanners_service import AtsCriteria, AtsCriterion, AtsVerdict, Coverage, RecruiterVerdict  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import demo_data as data  # noqa: E402

TODAY = date.today()
NOW = datetime.now(timezone.utc)


def _usage(tin: int, tout: int, write: int = 0, read: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        input_tokens=tin, output_tokens=tout, cache_creation_input_tokens=write, cache_read_input_tokens=read
    )


# --- stand-in embeddings ----------------------------------------------------
# The real app embeds with OpenAI. A hashed bag of words gives the similarity
# search something meaningful to rank without an API call.

def _embed(lines: list[str], dims: int = 256) -> list[float]:
    vec = [0.0] * dims
    for word in re.findall(r"[a-z]{3,}", " ".join(lines).lower()):
        vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % dims] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [round(v / norm, 6) for v in vec]


def _description(job: dict) -> str:
    parts = [" ".join(job["summary"]), "", "What you'll do:"]
    parts += [f"- {r}" for r in job["responsibilities"]]
    parts += ["", "What you'll bring:"] + [f"- {q}" for q in job["qualifications"]]
    if job["comp"]:
        parts += ["", f"Base salary range: ${job['comp'][0]:,} - ${job['comp'][1]:,}."]
    return "\n".join(parts)


def seed_jobs() -> None:
    with db.session_scope() as session:
        for job in data.JOBS:
            posted = TODAY - timedelta(days=job["posted_days_ago"])
            fetched = NOW - timedelta(days=job["posted_days_ago"])
            session.add(Job(
                source=job["source"], job_id=job["job_id"], title=job["title"], company=job["company"],
                location=job["location"], url=f"https://example.com/jobs/{job['job_id']}",
                posted_at=posted, description_raw=_description(job), workplace_raw=job["workplace"],
                salary_text=(f"${job['comp'][0]:,} - ${job['comp'][1]:,}" if job["comp"] else None),
                fetched_at=fetched,
            ))
            session.add(JobNormalized(
                source=job["source"], job_id=job["job_id"], title=job["title"], company=job["company"],
                posted_at=posted, responsibilities=job["responsibilities"], qualifications=job["qualifications"],
                comp_min=job["comp"][0] if job["comp"] else None, comp_max=job["comp"][1] if job["comp"] else None,
                workplace=job["workplace"], role_summary=job["summary"], normalized_at=fetched,
                model="claude-haiku-4-5", normalizer_version="v3",
                input_tokens=1850, output_tokens=420, cost_usd=0.00395,
                responsibilities_embedding=_embed(job["responsibilities"]),
                qualifications_embedding=_embed(job["qualifications"]),
                embedding_input_tokens=160, embedding_cost_usd=0.0000032,
            ))


def seed_applications() -> dict[str, int]:
    ids = {}
    sources = {j["job_id"]: j["source"] for j in data.JOBS}
    with db.session_scope() as session:
        for company, title, role, status, highest, days, job_id, referral in data.APPLICATIONS:
            app = Application(
                company=company, title=title, role=role, status=status, highest_round=highest,
                applied_at=TODAY - timedelta(days=days), job_id=job_id,
                source=sources.get(job_id) if job_id else None, referral=referral,
            )
            session.add(app)
            session.flush()
            ids[company] = app.id
        for company, source, token in data.TRACKED_COMPANIES:
            session.add(TrackedCompany(company=company, source=source, board_token=token))
    return ids


def seed_resumes(app_ids: dict[str, int]) -> None:
    # The real parser, reading text instead of PDF bytes.
    resume_ingest.extract_text = lambda pdf_bytes: pdf_bytes.decode()
    for company, text in data.RESUMES.items():
        result = resume_ingest.attach_resume_to_application(app_ids[company], "resume.pdf", text.encode())
        assert result["status"] == "ingested", (company, result)


class _Parse:
    """A client whose messages.parse returns whatever `answer(kwargs)` builds."""

    def __init__(self, answer, usage):
        self.messages = SimpleNamespace(
            parse=lambda **kwargs: SimpleNamespace(parsed_output=answer(kwargs), usage=usage)
        )


def seed_evaluations() -> None:
    def assessment(kwargs):
        content = kwargs["messages"][0]["content"]
        company = next(c for c in data.EVALUATIONS if f"Company: {c}" in content)
        spec = data.EVALUATIONS[company]
        fields = {}
        for name in evaluator.CODE_BY_FIELD:
            score, rationale = spec[name]
            fields[name] = evaluator.SubScore(score=score, abstained=score is None, rationale=rationale)
        return evaluator.RoleAssessment(
            **fields, reasoning=spec["reasoning"], pm_years_required=spec.get("pm_years_required")
        )

    evaluator._client = lambda: _Parse(assessment, _usage(2950, 610))
    open_jobs = [j for j in data.JOBS if j["kind"] == "open"]
    for source in {j["source"] for j in open_jobs}:
        evaluate_jobs([j["job_id"] for j in open_jobs if j["source"] == source], source=source, delay_seconds=0)

    with db.session_scope() as session:
        notes = {
            row.id: data.EVALUATIONS[row_company]["note"]
            for row, row_company in (
                (e, session.get(JobNormalized, (e.source, e.job_id)).company)
                for e in session.query(Evaluation).all()
            )
            if "note" in data.EVALUATIONS.get(row_company, {})
        }
    for evaluation_id, note in notes.items():
        set_evaluation_note(evaluation_id, note)


def seed_bullet_bank() -> None:
    import json

    tag_ids = {}
    for tag in json.loads((BACKEND / "data" / "bullet_tags_seed.json").read_text()):
        tag_ids[tag["name"]] = bullet_bank_service.create_tag(tag["name"], tag["category"], tag["definition"])["id"]
    for sentence, names in data.TAGGED.items():
        bullet_bank_service.set_sentence_tags(sentence, [tag_ids[n] for n in names])

    def picks(kwargs):
        user = kwargs["messages"][0]["content"]
        listed = [line.split(". ", 1) for line in user.split("Bullets:\n", 1)[1].splitlines()]
        return bullet_tagger_service.TaggerOutput(bullets=[
            bullet_tagger_service.BulletPicks(index=int(i), tags=[
                bullet_tagger_service.TagPick(tag=t, reason=r) for t, r in data.SUGGESTED.get(text, [])
            ])
            for i, text in listed
        ])

    bullet_tagger_service.suggest_tags(list(data.SUGGESTED), client=_Parse(picks, _usage(2400, 380)))
    # Some decided, some left pending, so the accept rate and the pending
    # chips both show.
    rows = bullet_bank_service.list_bank()
    pending = {r["text"]: r["suggestions"] for r in rows if r["suggestions"]}
    decisions = [(data._TRIAGE_V2, True), (data._EXPERIMENTS, True), (data._PRICING, True), (data._AGENCY, True)]
    for sentence, accept in decisions:
        for suggestion in pending.get(sentence, [])[:1]:
            bullet_tagger_service.decide(suggestion["id"], accept)
    for suggestion in pending.get(data._PRICING, [])[1:2]:  # "Predictive Modeling" on a pricing analysis
        bullet_tagger_service.decide(suggestion["id"], False)


def seed_icp_resume() -> None:
    draft = IcpResumeDraft(experience=[ExperienceEntry(context=c, bullets=b) for c, b in data.ICP_EXPERIENCE])
    resume_service._client = lambda: _Parse(lambda kwargs: draft, _usage(3300, 900))
    resume_service.create_icp_resume(*data.ASSEMBLER_JOB)


class _AssemblerClient:
    """Scripted assembler model and scanners, run through the real harness:
    every swap is validated by the tool handlers, every scan result is mapped
    and stored by the real scanner code."""

    def __init__(self, run_id: int):
        self.run_id = run_id
        self.turn = 0
        self.messages = SimpleNamespace(create=self._create, parse=self._parse)

    def _swaps(self) -> list[dict]:
        """Lead the two internship sections (what a recruiter skims first)
        with the strongest donor line not already in the draft."""
        run = assembler_service.get_run(self.run_id)
        in_draft = {b["text"] for s in run["draft"]["sections"] for b in s["bullets"]}
        swaps = []
        with db.session_scope() as session:
            for slot in ("carewell", "courtside"):
                for resume_id in run["donor_resume_ids"]:
                    draft = assembler_service.load_draft(session, resume_id)
                    section = next((s for s in draft["sections"] if s["slot"] == slot), None)
                    line = next((b for b in (section or {}).get("bullets", []) if b["text"] not in in_draft), None)
                    if line:
                        swaps.append({"slot": slot, "position": 1, "source_bullet_id": line["source_bullet_id"]})
                        in_draft.add(line["text"])
                        break
        return swaps

    def _create(self, **kwargs):
        self.turn += 1
        block = lambda **kw: SimpleNamespace(**kw)  # noqa: E731
        if self.turn == 1:
            content = [
                block(type="text", text=(
                    "The posting is an activation role: funnel ownership, a high-velocity experimentation "
                    "program, cohort analysis and onboarding messaging. The anchor already leads its growth "
                    "section with the activation story. The weak spot is the top of the resume a recruiter "
                    "skims first — the two internships lead with lines that don't speak to activation or "
                    "evaluation rigor. Checking the draft before swapping."
                )),
                block(type="tool_use", id="toolu_demo_1", name="view_draft", input={}),
            ]
            usage = _usage(1200, 140, write=6900, read=0)
        elif self.turn == 2:
            calls = [block(type="tool_use", id=f"toolu_demo_s{i}", name="swap_bullet", input=s)
                     for i, s in enumerate(self._swaps())]
            content = [
                block(type="text", text=(
                    "Leading each internship with the line that shows measured rigor: the evaluation "
                    "harness for the LLM pilot, and the pricing analysis that sized a revenue upside. "
                    "Both are copied verbatim from donor resumes in the same sections. Then running "
                    "all three scans."
                )),
                *calls,
                block(type="tool_use", id="toolu_demo_g", name="run_hard_gate_scan", input={}),
                block(type="tool_use", id="toolu_demo_a", name="run_ats_scan", input={}),
                block(type="tool_use", id="toolu_demo_r", name="run_recruiter_scan", input={}),
            ]
            usage = _usage(900, 260, write=1400, read=6900)
        else:
            content = [block(type="text", text="All three scans pass; the draft is ready.")]
            usage = _usage(300, 30, write=900, read=8300)
        stop = "tool_use" if any(b.type == "tool_use" for b in content) else "end_turn"
        return SimpleNamespace(content=content, stop_reason=stop, usage=usage)

    def _parse(self, **kwargs):
        fmt = kwargs["output_format"]
        if fmt is AtsCriteria:
            parsed = AtsCriteria(criteria=[
                AtsCriterion(criterion=c, category=cat, required=req, keywords=kw) for c, cat, req, kw in data.ATS_CRITERIA
            ])
            usage = _usage(1450, 330)
        elif fmt is AtsVerdict:
            # Candidate is A (fixed RNG below).
            coverage = [Coverage(a=True, b=req) for _, _, req, _ in data.ATS_CRITERIA]
            coverage[1] = Coverage(a=True, b=True)
            coverage[5] = Coverage(a=True, b=False)
            parsed = AtsVerdict(coverage=coverage, winner="A", reasons=(
                "A covers every required criterion with direct evidence: activation ownership, an experimentation "
                "program, cohort analysis and SQL. A also shows evaluation rigor on an LLM pilot. B misses explicit "
                "consumer-subscription evidence, so A wins on coverage."
            ))
            usage = _usage(2100, 420)
        else:
            parsed = RecruiterVerdict(winner="A", reasons=(
                "A's first internship bullet leads with an evaluation harness and a rollout, which reads as someone "
                "who ships carefully; B's leads with a narrower pilot result. The growth role headline and the "
                "35% activation line make A an obvious fit for an activation PM in one pass."
            ))
            usage = _usage(1300, 210)
        return SimpleNamespace(parsed_output=parsed, usage=usage)


class _CandidateIsA:
    def random(self):
        return 0.1


def seed_assembler_run() -> None:
    run_id = assembler_service.create_run(*data.ASSEMBLER_JOB)
    status = run_assembly(run_id, client=_AssemblerClient(run_id), rng=_CandidateIsA())
    assert status == "passed", f"demo assembler run ended {status}"


def main() -> int:
    if DEMO_DB.exists():
        DEMO_DB.unlink()
    seed_jobs()
    app_ids = seed_applications()
    seed_resumes(app_ids)
    seed_evaluations()
    seed_bullet_bank()
    seed_icp_resume()
    seed_assembler_run()

    with db.session_scope() as session:
        verdicts = sorted(e.verdict for e in session.query(Evaluation).all())
    print(f"Demo database written to {DEMO_DB}")
    print(f"  {len(data.JOBS)} jobs, {len(data.APPLICATIONS)} applications, {len(data.RESUMES)} resumes; verdicts {verdicts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
