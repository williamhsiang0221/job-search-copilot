"""Job Board Platform API.

The capture workflow is deliberately stateless: each request reads Gmail,
parses, and returns. Nothing is persisted — the dashboard is a view onto the
inbox, not a database of it.
"""

from __future__ import annotations

import threading
from datetime import date, timedelta

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app import config, resume_layout
from app.applications_service import (
    apply_from_normalized,
    backfill_summary,
    list_applications,
    update_application,
)
from app.ats_service import (
    add_company,
    list_companies,
    remove_company,
    resolve_job_context,
    scan_companies,
    set_company_enabled,
)
from app.batch_progress import evaluate_progress, fetch_progress, tagger_progress
from app.evaluations_service import evaluate_jobs, list_evaluations, set_evaluation_note, total_evaluation_cost
from app.evaluator import EvaluatorUnavailable
from app.evaluator import available_versions as evaluator_prompt_versions
from app.evaluator import load_prompt as evaluator_prompt_body
from app.normalizer import NormalizerUnavailable
from app.normalizer import available_versions as normalizer_prompt_versions
from app.normalizer import load_prompt as normalizer_prompt_body
from app.resume_service import ResumeUnavailable
from app.resume_service import available_versions as resume_prompt_versions
from app.resume_service import load_prompt as resume_prompt_body
from app.resume_service import create_icp_resume, list_icp_resumes, total_resume_cost
from app.jd_sources import (
    AshbySource,
    GreenhouseSource,
    JobDescriptionSource,
    LeverSource,
    OracleSource,
    WorkdaySource,
)
from app.jobs_service import (
    fetch_and_store,
    linkedin_fetch_available,
    list_jobs,
    list_normalized,
    ready_job_ids,
    total_embedding_cost,
    total_normalize_cost,
)
from app.attachments_service import applications_needing_attachments
from app.bullet_tagger_service import (
    decide,
    pending_sentences,
    suggest_tags,
    suggestion_stats,
    total_tagger_cost,
)
from app.bullet_bank_service import (
    BulletBankError,
    create_tag,
    delete_tag,
    list_bank,
    list_tags,
    parse_keywords,
    set_sentence_tags,
    update_tag,
)
from app.jd_linking_service import attach_pdf_to_application
from app.manual_capture_service import store_manual_pdf
from app.models import ATS_SOURCES
from app.resume_ingest_service import (
    ResumeIngestError,
    attach_resume_to_application,
    resume_for_application,
)
from app import prompts as _prompts
from app.assembler_agent import start_assembly
from app.assembler_service import AssemblerUnavailable, get_run, list_runs, total_assembler_cost
from app.parser import dedupe_roles, parse_messages
from app.scanners_service import SCANNER_KINDS, ScannerUnavailable
from app.scanners_service import active_version as scanner_active_version
from app.scanners_service import available_versions as scanner_prompt_versions
from app.scanners_service import load_prompt as scanner_prompt_body
from app.similarity_service import find_similar_applications
from app.sources import FixtureSource, GmailSource, NotAuthorizedError

app = FastAPI(title="Job Board Platform", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.FRONTEND_ORIGINS,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["*"],
)


def get_source():
    if config.USE_FIXTURES:
        return FixtureSource()
    return GmailSource(config.GMAIL_CREDENTIALS_PATH, config.GMAIL_TOKEN_PATH)


def resolve_range(
    preset: str, start: date | None, end: date | None, today: date | None = None
) -> tuple[date, date]:
    """Turn a dropdown preset into an inclusive calendar-day range.

    Presets are calendar days rather than rolling 24h windows, so that
    "Yesterday" means yesterday rather than 24-48 hours ago.
    """
    today = today or date.today()

    if preset == "today":
        return today, today
    if preset == "yesterday":
        day = today - timedelta(days=1)
        return day, day
    if preset == "past3":
        return today - timedelta(days=2), today
    if preset == "past7":
        return today - timedelta(days=6), today
    if preset == "custom":
        if start is None or end is None:
            raise HTTPException(400, "custom range requires both start and end")
        if start > end:
            raise HTTPException(400, "start date must not be after end date")
        return start, end

    raise HTTPException(400, f"unknown range preset: {preset}")


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "source": "fixtures" if config.USE_FIXTURES else "gmail",
        "gmail_authorized": config.GMAIL_TOKEN_PATH.exists(),
    }


@app.get("/api/capture")
def capture(
    range: str = Query("today", description="today | yesterday | past3 | past7 | custom"),
    start: date | None = Query(None),
    end: date | None = Query(None),
):
    range_start, range_end = resolve_range(range, start, end)

    try:
        messages = get_source().fetch(range_start, range_end)
    except NotAuthorizedError as exc:
        raise HTTPException(401, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:  # surface the real reason to the dashboard
        raise HTTPException(502, f"could not read mail: {exc}") from exc

    parsed = parse_messages(messages)
    roles = dedupe_roles(parsed)

    return {
        "roles": [r.as_dict() for r in roles],
        "meta": {
            "emails_scanned": len(messages),
            "roles_found": len(roles),
            "rows_parsed": len(parsed),
            "duplicates_collapsed": len(parsed) - len(roles),
            "range_start": range_start.isoformat(),
            "range_end": range_end.isoformat(),
            "source": "fixtures" if config.USE_FIXTURES else "gmail",
        },
    }


class FetchRequest(BaseModel):
    job_ids: list[str] = Field(min_length=1, max_length=50)
    source: str = "linkedin"
    # Required for Greenhouse/Ashby/Lever: job_id -> company, so the right
    # tracked board's token can be resolved. A job id alone isn't fetchable on
    # these boards — unlike LinkedIn, ids are only meaningful within one
    # company's board. Ignored for linkedin.
    job_companies: dict[str, str] | None = None


ATS_SOURCE_CLASSES: dict[str, type[JobDescriptionSource]] = {
    "greenhouse": GreenhouseSource,
    "ashby": AshbySource,
    "lever": LeverSource,
    "workday": WorkdaySource,
    "oracle": OracleSource,
}


@app.get("/api/jobs/status")
def jobs_status(
    ids: str = Query(..., description="Comma-separated job ids"),
    source: str = Query("linkedin"),
):
    """Which of these job ids already have normalized fields stored.

    Drives the Fetched JD column: a checked row is finished, so it is disabled
    and cannot be selected for refetching.
    """
    job_ids = [i.strip() for i in ids.split(",") if i.strip()]
    return {"source": source, "ready": sorted(ready_job_ids(source, job_ids))}


def _build_ats_source(source: str, job_ids: list[str], job_companies: dict[str, str] | None):
    companies = job_companies or {}
    missing = [j for j in job_ids if j not in companies]
    if missing:
        raise HTTPException(400, f"missing company for job ids: {missing}")

    token_by_company = resolve_job_context(source, list(set(companies.values())))
    job_tokens = {j: token_by_company.get(companies[j], "") for j in job_ids}
    unresolved = [j for j, t in job_tokens.items() if not t]
    if unresolved:
        raise HTTPException(400, f"no tracked board for job ids: {unresolved}")

    source_cls = ATS_SOURCE_CLASSES[source]
    if source == "greenhouse":
        return source_cls(job_tokens=job_tokens)
    return source_cls(job_tokens=job_tokens, job_companies=companies)


@app.post("/api/jobs/fetch")
def jobs_fetch(request: FetchRequest):
    """Start fetching, storing and normalizing descriptions for the selected jobs.

    Runs in a background thread rather than blocking the request: capped per
    request and fetched sequentially with a pause (LinkedIn's is an
    undocumented guest endpoint, and hammering it is how access is lost; the
    ATS sources are documented public APIs but stay sequential for the same
    politeness), so a full batch can take a while. Poll
    /api/jobs/fetch/progress for live status and the final report.

    Progress is tracked per source, not globally: two LinkedIn batches must
    never run at once (same rate-limit concern as within a batch), but a
    Greenhouse and a Lever batch fetching concurrently is fine — they're
    different hosts, and the frontend already fires one request per source
    when a selection spans several.
    """
    if fetch_progress.is_running(request.source):
        raise HTTPException(409, f"a {request.source} fetch is already in progress")

    if request.source == "linkedin":
        if not linkedin_fetch_available():
            raise HTTPException(501, "LinkedIn description fetch is not included in this build")
        source_impl: JobDescriptionSource | None = None
    elif request.source in ATS_SOURCES:
        # Resolved up front so a bad request (missing company, untracked
        # board) fails the request itself rather than the background thread.
        source_impl = _build_ats_source(request.source, request.job_ids, request.job_companies)
    else:
        raise HTTPException(400, f"unsupported source: {request.source}")

    def run() -> None:
        try:
            report = fetch_and_store(
                request.job_ids,
                source=source_impl,
                on_progress=lambda job_id: fetch_progress.mark_done(request.source, job_id),
            )
            fetch_progress.finish(request.source, report.as_dict())
        except Exception as exc:
            fetch_progress.fail(request.source, str(exc))

    fetch_progress.start(request.source, total=len(set(request.job_ids)))
    threading.Thread(target=run, daemon=True).start()
    return {"started": True}


@app.get("/api/jobs/fetch/progress")
def jobs_fetch_progress(source: str = Query("linkedin")):
    """Live status of the fetch started by /api/jobs/fetch, meant to be polled."""
    return fetch_progress.snapshot(source)


@app.post("/api/jobs/upload-pdf")
async def jobs_upload_pdf(
    company: str = Form(...),
    title: str = Form(...),
    url: str = Form(""),
    file: UploadFile = File(...),
):
    """Store and normalize a posting with no ATS API behind it — captured as
    a PDF from wherever it was actually posted."""
    pdf_bytes = await file.read()
    try:
        report = store_manual_pdf(company, title, pdf_bytes, url=url)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return report.as_dict()


class TrackedCompanyCreate(BaseModel):
    company: str
    source: str
    board_token: str


class TrackedCompanyToggle(BaseModel):
    enabled: bool


@app.get("/api/ats/companies")
def ats_companies_list():
    return {"companies": list_companies()}


@app.post("/api/ats/companies")
def ats_companies_add(request: TrackedCompanyCreate):
    try:
        return add_company(request.company, request.source, request.board_token)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.delete("/api/ats/companies/{company_id}")
def ats_companies_remove(company_id: int):
    if not remove_company(company_id):
        raise HTTPException(404, "not found")
    return {"removed": company_id}


@app.patch("/api/ats/companies/{company_id}")
def ats_companies_toggle(company_id: int, request: TrackedCompanyToggle):
    result = set_company_enabled(company_id, request.enabled)
    if result is None:
        raise HTTPException(404, "not found")
    return result


@app.post("/api/ats/scan")
def ats_scan():
    """Scan every enabled tracked company's board for open roles.

    Stateless, same as /api/capture: nothing is written to the database until
    a role is selected and fetched.
    """
    return scan_companies().as_dict()


@app.get("/api/jobs")
def jobs_raw(source: str | None = Query(None)):
    """Stored jobs as published, full description included."""
    rows = list_jobs(source)
    return {"jobs": rows, "count": len(rows)}


@app.get("/api/jobs/normalized")
def jobs_normalized(source: str | None = Query(None)):
    """Model-extracted fields, one row per normalized job."""
    rows = list_normalized(source)
    return {"jobs": rows, "count": len(rows)}


@app.get("/api/jobs/{source}/{job_id}/similar-applications")
def jobs_similar_applications(source: str, job_id: str):
    """Top 5 most similar past applications, by Responsibilities and by
    Qualifications, with each match's outcome alongside it.

    Recomputed on every call rather than cached — see similarity_service's
    module docstring for why that is cheap enough to be the simple choice.
    """
    return find_similar_applications(source, job_id)


@app.post("/api/jobs/{source}/{job_id}/icp-resume")
def jobs_generate_icp_resume(source: str, job_id: str):
    """Generate and store one ICP resume for this posting.

    Synchronous, not backgrounded like fetch/evaluate — this is a single LLM
    call (a few seconds), not a batch. Every call appends a new row rather
    than replacing a prior one, since re-generating on purpose to compare
    against an earlier run is expected while the prompt is still being
    iterated on.
    """
    try:
        return create_icp_resume(source, job_id)
    except ResumeUnavailable as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/icp-resumes")
def icp_resumes_list():
    """Every ICP resume ever generated, newest first."""
    rows = list_icp_resumes()
    return {"resumes": rows, "count": len(rows)}


class EvaluateRequest(BaseModel):
    job_ids: list[str] = Field(min_length=1, max_length=50)
    source: str = "linkedin"
    rubric_version: str | None = None


@app.post("/api/evaluate")
def evaluations_run(request: EvaluateRequest):
    """Start scoring the selected jobs against the rubric.

    Same shape as /api/jobs/fetch: runs in a background thread rather than
    blocking the request (sequential with a pause, one failure never aborting
    the batch), tracked per source so a selection spanning several sources can
    run concurrently. Poll /api/evaluate/progress for live status and the
    final report.
    """
    if evaluate_progress.is_running(request.source):
        raise HTTPException(409, f"a {request.source} evaluation is already in progress")

    def run() -> None:
        try:
            report = evaluate_jobs(
                request.job_ids,
                source=request.source,
                rubric_version=request.rubric_version,
                on_progress=lambda job_id: evaluate_progress.mark_done(request.source, job_id),
            )
            evaluate_progress.finish(request.source, report.as_dict())
        except Exception as exc:
            evaluate_progress.fail(request.source, str(exc))

    evaluate_progress.start(request.source, total=len(set(request.job_ids)))
    threading.Thread(target=run, daemon=True).start()
    return {"started": True}


@app.get("/api/evaluate/progress")
def evaluations_progress(source: str = Query("linkedin")):
    """Live status of the evaluation started by /api/evaluate, meant to be polled."""
    return evaluate_progress.snapshot(source)


@app.get("/api/evaluations")
def evaluations_list(source: str | None = Query(None)):
    """Every verdict, newest first, with the sub-scores behind it."""
    rows = list_evaluations(source)
    return {"evaluations": rows, "count": len(rows)}


class EvaluationNoteRequest(BaseModel):
    note: str | None = None


@app.put("/api/evaluations/{evaluation_id}/note")
def evaluation_note(evaluation_id: int, request: EvaluationNoteRequest):
    """Save the user's note on one verdict; blank text clears it."""
    saved = set_evaluation_note(evaluation_id, request.note)
    if saved is None:
        raise HTTPException(404, f"no evaluation {evaluation_id}")
    return saved


# Each entry: (list versions, load one version, its "unavailable" exception,
# which version runs by default). Every prompted workflow plugs into the same
# two routes below rather than each growing its own pair.
_PROMPT_KINDS: dict[str, tuple] = {
    "evaluator": (
        evaluator_prompt_versions,
        evaluator_prompt_body,
        EvaluatorUnavailable,
        lambda: config.EVALUATOR_RUBRIC_VERSION,
    ),
    "normalizer": (
        normalizer_prompt_versions,
        normalizer_prompt_body,
        NormalizerUnavailable,
        lambda: config.NORMALIZER_PROMPT_VERSION,
    ),
    "resume": (
        resume_prompt_versions,
        resume_prompt_body,
        ResumeUnavailable,
        lambda: config.RESUME_PROMPT_VERSION,
    ),
}
for _kind in SCANNER_KINDS:
    _PROMPT_KINDS[_kind] = (
        lambda kind=_kind: scanner_prompt_versions(kind),
        lambda version, kind=_kind: scanner_prompt_body(kind, version),
        ScannerUnavailable,
        lambda kind=_kind: scanner_active_version(kind),
    )
_PROMPT_KINDS["assembler"] = (
    lambda: _prompts.available_versions("assembler"),
    lambda version: _prompts.load_prompt("assembler", version),
    _prompts.PromptUnavailable,
    lambda: config.ASSEMBLER_PROMPT_VERSION,
)
_PROMPT_KINDS["bullet_tagger"] = (
    lambda: _prompts.available_versions("bullet_tagger"),
    lambda version: _prompts.load_prompt("bullet_tagger", version),
    _prompts.PromptUnavailable,
    lambda: config.BULLET_TAGGER_PROMPT_VERSION,
)


def _prompt_kind(kind: str) -> tuple:
    entry = _PROMPT_KINDS.get(kind)
    if entry is None:
        raise HTTPException(404, f"unknown prompt kind '{kind}'")
    return entry


@app.get("/api/prompts/{kind}")
def prompt_versions(kind: str):
    """Which prompt versions exist for this workflow, and which runs by default."""
    versions_fn, _, _, active_fn = _prompt_kind(kind)
    return {"versions": versions_fn(), "active": active_fn()}


@app.get("/api/prompts/{kind}/{version}")
def prompt_body(kind: str, version: str):
    """One prompt version verbatim, for this workflow.

    Same reasoning as the Raw tab: when an output looks wrong, the prompt that
    produced it is what settles the argument.
    """
    _, load_fn, unavailable, _ = _prompt_kind(kind)
    try:
        return {"version": version, "body": load_fn(version)}
    except unavailable as exc:
        raise HTTPException(404, str(exc)) from exc


class ApplicationUpdate(BaseModel):
    status: str | None = None
    highest_round: str | None = None
    referral: str | None = None
    job_id: str | None = None
    role: str | None = None
    applied_at: str | None = None
    company: str | None = None
    title: str | None = None


class ApplyRequest(BaseModel):
    job_ids: list[str] = Field(min_length=1, max_length=50)
    source: str = "linkedin"


@app.get("/api/applications")
def applications_list():
    """Every application, plus how much outcome history is still unknown."""
    return {"applications": list_applications(), "summary": backfill_summary()}


@app.get("/api/applications/needing-attachments")
def applications_needing_attachments_list():
    """Applications missing a JD, a resume, or both — the merged one-time
    backfill worklist, not part of the regular applications flow."""
    return {"applications": applications_needing_attachments()}


@app.post("/api/applications/{application_id}/attach-pdf")
async def applications_attach_pdf(application_id: int, file: UploadFile = File(...)):
    """Stores and normalizes a JD PDF exactly like /api/jobs/upload-pdf, then
    links it to this application — the one-time backfill counterpart to that
    endpoint, kept separate rather than added as a parameter there."""
    pdf_bytes = await file.read()
    try:
        report = attach_pdf_to_application(application_id, pdf_bytes)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return report.as_dict()


@app.post("/api/applications/{application_id}/attach-resume")
async def applications_attach_resume(application_id: int, file: UploadFile = File(...), replace: bool = False):
    """Parses a resume PDF into resumes/sections/bullets and links it to this
    application. Company/title/date come from the application itself, not
    the filename — unlike the batch ingest script, the point of picking a
    known application is that its identity doesn't need to be re-derived.
    ?replace=true swaps out a resume already linked to this application."""
    pdf_bytes = await file.read()
    try:
        result = attach_resume_to_application(
            application_id, file.filename or "resume.pdf", pdf_bytes, replace=replace
        )
    except ResumeIngestError as exc:
        raise HTTPException(400, str(exc)) from exc
    return result


@app.get("/api/applications/{application_id}/resume")
def application_resume(application_id: int):
    """The parsed resume attached to this application, if any — for the All
    Applications expand panel."""
    return {"resume": resume_for_application(application_id)}


@app.get("/api/costs")
def costs():
    """Total API spend tracked so far, across both Anthropic and OpenAI.

    Only calls from after cost tracking was added to each of normalize,
    evaluate and embed are counted — earlier rows recorded no token usage and
    cannot be backfilled, so this total is a floor, not a complete historical
    figure.
    """
    normalize_cost = total_normalize_cost()
    evaluation_cost = total_evaluation_cost()
    embedding_cost = total_embedding_cost()
    resume_cost = total_resume_cost()
    assembler_cost = total_assembler_cost()
    tagger_cost = total_tagger_cost()
    return {
        "normalize_cost_usd": normalize_cost,
        "evaluation_cost_usd": evaluation_cost,
        "embedding_cost_usd": embedding_cost,
        "resume_cost_usd": resume_cost,
        "assembler_cost_usd": assembler_cost,
        "bullet_tagger_cost_usd": tagger_cost,
        "total_cost_usd": round(
            normalize_cost + evaluation_cost + embedding_cost + resume_cost + assembler_cost + tagger_cost, 6
        ),
    }


@app.post("/api/jobs/{source}/{job_id}/assemble")
def jobs_assemble(source: str, job_id: str):
    """Start a Resume Assembler run for this posting. Seeding happens here,
    so "no similar role has a resume" fails the request itself; the agent
    loop then runs in the background — poll /api/assembly-runs/{id}."""
    try:
        run_id = start_assembly(source, job_id)
    except AssemblerUnavailable as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"run_id": run_id}


@app.get("/api/resume-layout")
def resume_layout_labels():
    """Section labels in print order, from the profile's resume layout — the
    frontend reads these instead of hardcoding the candidate's employers."""
    return {"slots": [{"slot": s, "label": resume_layout.SLOT_LABELS[s]} for s in resume_layout.SLOT_DISPLAY_ORDER]}


@app.get("/api/bullet-bank")
def bullet_bank(
    q: str | None = Query(None, description="Comma-separated keywords; every one must appear"),
    tags: str | None = Query(None, description="Comma-separated tag ids; every one must be on the bullet"),
    untagged: bool = Query(False),
):
    """Distinct resume bullets matching every keyword and tag."""
    try:
        tag_ids = [int(t) for t in (tags or "").split(",") if t.strip()]
    except ValueError:
        raise HTTPException(400, "tags must be comma-separated ids")
    rows = list_bank(parse_keywords(q), tag_ids, untagged)
    return {"bullets": rows, "count": len(rows), "suggestion_stats": suggestion_stats()}


class SuggestRequest(BaseModel):
    # The bullets on screen; null = every experience bullet not yet asked.
    texts: list[str] | None = None


@app.post("/api/bullet-bank/suggest")
def bullet_bank_suggest(request: SuggestRequest):
    """Start suggesting tags in the background; poll /suggest/progress."""
    if tagger_progress.is_running("bullets"):
        raise HTTPException(409, "tag suggestions are already running")

    def run() -> None:
        try:
            report = suggest_tags(request.texts, on_progress=lambda t: tagger_progress.mark_done("bullets", t))
            tagger_progress.finish("bullets", report)
        except Exception as exc:
            tagger_progress.fail("bullets", f"{type(exc).__name__}: {exc}")

    total = len(pending_sentences(request.texts))
    tagger_progress.start("bullets", total=total)
    threading.Thread(target=run, daemon=True).start()
    return {"started": True, "total": total}


@app.get("/api/bullet-bank/suggest/progress")
def bullet_bank_suggest_progress():
    snapshot = tagger_progress.snapshot("bullets")
    done = len(snapshot.pop("done_ids"))
    return {**snapshot, "done": done}


@app.post("/api/bullet-bank/suggestions/{suggestion_id}/{decision}")
def bullet_bank_decide(suggestion_id: int, decision: str):
    """Accept (applies the tag) or reject one suggestion."""
    if decision not in ("accept", "reject"):
        raise HTTPException(404, "use accept or reject")
    result = decide(suggestion_id, decision == "accept")
    if result is None:
        raise HTTPException(404, f"no suggestion {suggestion_id}")
    return result


class BulletTagCreate(BaseModel):
    name: str
    category: str | None = None
    definition: str = ""


class BulletTagUpdate(BaseModel):
    name: str | None = None
    category: str | None = None
    definition: str | None = None


class SentenceTags(BaseModel):
    text: str
    tag_ids: list[int]


@app.get("/api/bullet-tags")
def bullet_tags():
    return {"tags": list_tags()}


@app.post("/api/bullet-tags")
def bullet_tag_create(request: BulletTagCreate):
    try:
        return create_tag(request.name, request.category, request.definition)
    except BulletBankError as exc:
        raise HTTPException(409 if "already exists" in str(exc) else 400, str(exc))


@app.patch("/api/bullet-tags/{tag_id}")
def bullet_tag_update(tag_id: int, request: BulletTagUpdate):
    try:
        return update_tag(tag_id, **request.model_dump(exclude_unset=True))
    except BulletBankError as exc:
        status = 404 if str(exc).startswith("no tag") else 409 if "already exists" in str(exc) else 400
        raise HTTPException(status, str(exc))


@app.delete("/api/bullet-tags/{tag_id}")
def bullet_tag_delete(tag_id: int):
    try:
        delete_tag(tag_id)
    except BulletBankError as exc:
        raise HTTPException(404, str(exc))
    return {"deleted": tag_id}


@app.put("/api/bullet-bank/tags")
def bullet_bank_set_tags(request: SentenceTags):
    """Replace the tags on one bullet sentence (every resume that uses it)."""
    try:
        return {"text": request.text, "tag_ids": set_sentence_tags(request.text, request.tag_ids)}
    except BulletBankError as exc:
        raise HTTPException(404 if str(exc).startswith("no ") else 400, str(exc))


@app.get("/api/assembly-runs")
def assembly_runs_list():
    """Every assembler run, newest first, without its trace."""
    return {"runs": list_runs()}


@app.get("/api/assembly-runs/{run_id}")
def assembly_run_detail(run_id: int):
    """One run with its full trace — what the live tracer polls."""
    run = get_run(run_id)
    if run is None:
        raise HTTPException(404, f"no assembly run {run_id}")
    return run


@app.post("/api/applications/apply")
def applications_apply(request: ApplyRequest):
    """Create an application for each selected normalized job.

    Role is left unset here — it's picked later in Needs Backfill, the same
    place highest_round gets filled in for legacy rows.
    """
    return apply_from_normalized(request.job_ids, request.source)


@app.patch("/api/applications/{app_id}")
def applications_update(app_id: int, update: ApplicationUpdate):
    changes = update.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(400, "no fields to update")

    try:
        result = update_application(app_id, changes)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    if result is None:
        raise HTTPException(404, f"no application with id {app_id}")
    return result
