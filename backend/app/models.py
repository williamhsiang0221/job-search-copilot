"""Database models for stored job descriptions.

Capture stays stateless — it is a view onto the inbox. This database holds only
the jobs actually chosen for a closer look, which is a far smaller set: a
handful a day rather than the couple of hundred that scroll past.

Job ids are only unique within a source, so every table keys on (source,
job_id). Greenhouse, Ashby and Lever job ids are further scoped to a single
company's board — resolving one to a fetchable URL needs the tracked
company's board token, not just the id (see TrackedCompany).
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Job(Base):
    """A job posting as the source published it, with as little interpretation
    as possible. Fields ending in _raw keep each board's own vocabulary —
    Ashby says "FullTime", Lever says "Permanent", LinkedIn says "Full-time" —
    because flattening them would destroy information for no gain.
    """

    __tablename__ = "jobs"

    source: Mapped[str] = mapped_column(String(20), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)

    title: Mapped[str] = mapped_column(String(500))
    company: Mapped[str] = mapped_column(String(300))
    location: Mapped[str] = mapped_column(String(300), default="")
    url: Mapped[str] = mapped_column(Text, default="")
    # LinkedIn withholds the real apply URL from guests; Ashby and Lever give it.
    apply_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    posted_at: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    # LinkedIn only says "1 day ago", so its dates are derived, not stated.
    # Flagged so a sort never implies precision the source did not provide.
    posted_at_is_approximate: Mapped[bool] = mapped_column(Boolean, default=False)
    # Most recent alert email to carry this job. LinkedIn only.
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Plain text, never HTML. Lever splits its description across several
    # fields, so for that source this is a concatenation.
    description_raw: Mapped[str] = mapped_column(Text, default="")

    level_raw: Mapped[str | None] = mapped_column(String(120), nullable=True)
    employment_type_raw: Mapped[str | None] = mapped_column(String(120), nullable=True)
    workplace_raw: Mapped[str | None] = mapped_column(String(60), nullable=True)
    department: Mapped[str | None] = mapped_column(String(200), nullable=True)
    team: Mapped[str | None] = mapped_column(String(200), nullable=True)
    job_function: Mapped[str | None] = mapped_column(String(200), nullable=True)
    industries: Mapped[str | None] = mapped_column(String(300), nullable=True)

    salary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    normalized: Mapped["JobNormalized | None"] = relationship(
        back_populates="job", uselist=False, cascade="all, delete-orphan"
    )


class JobNormalized(Base):
    """Model-extracted fields, one row per job.

    Deliberately denormalized: title, company and posted_at are copied from
    Job so the evaluator can read this table alone. That duplication is
    intentional, not an oversight.

    Only holds what no board provides structurally. Compensation is the clear
    case — Greenhouse's pay_input_ranges is null and Lever's salaryRange is
    null even when the range sits in the description text.

    Qualifications are a single list on purpose. Most postings never separate
    required from preferred (three of five sampled did not), and having the
    extractor guess which is which would put invented distinctions in front of
    the evaluator. Extraction here, judgement downstream.
    """

    __tablename__ = "job_normalized"
    __table_args__ = (
        ForeignKeyConstraint(["source", "job_id"], ["jobs.source", "jobs.job_id"]),
    )

    source: Mapped[str] = mapped_column(String(20), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)

    title: Mapped[str] = mapped_column(String(500))
    company: Mapped[str] = mapped_column(String(300))
    posted_at: Mapped[datetime | None] = mapped_column(Date, nullable=True)

    responsibilities: Mapped[list] = mapped_column(JSON, default=list)
    qualifications: Mapped[list] = mapped_column(JSON, default=list)

    # None means the posting did not state it. Never a guess: the evaluator
    # must be able to tell "not stated" from an actual figure.
    comp_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comp_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Only inferred where the board gave no workplace_raw of its own.
    workplace: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # The posting's own sentences on what the role or team is for (normalizer
    # v3+), each verified to appear in the raw description. None means the
    # row predates v3 and was never asked; [] means the posting had none.
    role_summary: Mapped[list | None] = mapped_column(JSON, nullable=True)

    normalized_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    model: Mapped[str] = mapped_column(String(60), default="")
    # Which data/prompts/normalizer/{version}.md ran. Every row before this
    # column existed ran under v1 — the only version that has ever existed —
    # so the backfill default is a real fact, not a guess.
    normalizer_version: Mapped[str] = mapped_column(String(20), default="v1")

    # Same fields and reasoning as Evaluation's: facts from the API, so cost
    # stays accurate after prices move. Null on every row normalized before
    # this was added — that history cannot be recovered, so a cost total is
    # only complete for rows normalized from here on.
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Embeddings for JD lookalike scoring — one vector per field, kept separate
    # because "same duties" and "same required background" are different
    # signals for deciding whether to apply. Best-effort: a missing OpenAI key
    # or a failed call leaves these null without blocking normalization, the
    # same way a normalizer outage never costs a fetch.
    responsibilities_embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    qualifications_embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    embedding_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)

    job: Mapped[Job] = relationship(back_populates="normalized")


# Verdicts, in the order they cost the candidate attention. SKIP is the only
# one they act on blindly, which is why it is the only one that needs
# precision: MAYBE and APPLY both end with them looking at the role.
VERDICTS = ["SKIP", "MAYBE", "APPLY"]

# The ten sub-score codes the rubric defines. Stored as codes rather than
# columns so a v2 rubric can add or retire dimensions without orphaning the
# rows v1 wrote.
SUBSCORE_CODES = ["4a", "4b", "4c", "4d", "5a", "5b", "5c", "5d", "5e", "5f"]


class Evaluation(Base):
    """One scoring of one job against one version of the rubric.

    Many rows per job on purpose. Re-running a job under a new rubric must not
    destroy the old verdict — changing the rubric makes verdicts incomparable,
    and rubric_version is the only thing that says which is which.

    Scores and verdict are computed in Python from the sub-scores, never by the
    model. The model reads a scale and picks a number; the arithmetic is code,
    so a weight change is a diff rather than a prompt that drifts.
    """

    __tablename__ = "evaluations"
    __table_args__ = (
        ForeignKeyConstraint(["source", "job_id"], ["jobs.source", "jobs.job_id"]),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    source: Mapped[str] = mapped_column(String(20), index=True)
    job_id: Mapped[str] = mapped_column(String(64), index=True)

    # Which prompt file produced this row. Without it, two disagreeing verdicts
    # for the same job are unexplainable.
    rubric_version: Mapped[str] = mapped_column(String(20))

    score_1: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_2: Mapped[float | None] = mapped_column(Float, nullable=True)
    verdict: Mapped[str] = mapped_column(String(10))

    # Which gate forced a SKIP, if one did. Without this a stored SKIP is
    # ambiguous — bad scores and a fired gate need different responses, and
    # "how often does the salary floor do the killing" is worth being able
    # to ask.
    disqualifier: Mapped[str | None] = mapped_column(String(40), nullable=True)

    reasoning: Mapped[str] = mapped_column(Text, default="")

    model: Mapped[str] = mapped_column(String(60), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    # Token counts are facts from the API and never change. cost_usd is what
    # the call actually cost at the time, which stays true after prices move —
    # so a Haiku row and an Opus row remain directly comparable.
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # The user's own note on this verdict — why they applied or passed, or
    # where the evaluator got it wrong. Optional and sparse by design; read
    # back when reviewing the rubric, so it attaches to the evaluation (the
    # verdict being reacted to), not to the job.
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    note_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    scores: Mapped[list["EvaluationScore"]] = relationship(
        back_populates="evaluation", cascade="all, delete-orphan"
    )


class EvaluationScore(Base):
    """One sub-score of one evaluation.

    The weight is stored as applied, not looked up at read time, so a v2 rubric
    cannot retroactively rewrite what a v1 verdict was based on.

    A null score with abstained=True means the posting did not state the fact —
    not that it scored badly. The distinction drives the verdict: an evaluation
    carrying an abstention cannot return SKIP.
    """

    __tablename__ = "evaluation_scores"

    evaluation_id: Mapped[int] = mapped_column(
        ForeignKey("evaluations.id"), primary_key=True
    )
    code: Mapped[str] = mapped_column(String(4), primary_key=True)

    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight: Mapped[float] = mapped_column(Float)
    abstained: Mapped[bool] = mapped_column(Boolean, default=False)
    rationale: Mapped[str] = mapped_column(Text, default="")

    evaluation: Mapped[Evaluation] = relationship(back_populates="scores")


# The furthest stage an application reached, in order. Kept separate from
# status because Notion's Progress is a terminal state: a role that reached a
# phone screen and was then rejected records only "Rejected", which makes
# response rates look far worse than they were.
ROUND_LADDER = [
    "applied",
    "phone_screen",
    "interview",
    "final_round",
    "offer",
    "accepted",
]

# The only role categories the dashboard assigns going forward. Legacy Notion
# rows carry free-text values (e.g. "Strategist") outside this list — those
# are reconciled as part of the deferred legacy migration, not enforced here.
#
# Simplified from six categories to four: Product Marketing merged into
# Marketing, Product Strategy & Ops merged into Product Manager, AI Strategy
# renamed to Strategy. Existing rows were rewritten to match (see BACKLOG).
ROLE_CATEGORIES = [
    "Product Manager",
    "Strategy",
    "Data Analyst",
    "Marketing",
]


class Application(Base):
    """A submitted application and what became of it.

    Imported once from the Notion Job Applications database, then maintained
    here. Deliberately a one-way import rather than a two-way sync — keeping
    two systems agreeing is a category of bug not worth introducing for a
    single-user tool.
    """

    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    company: Mapped[str] = mapped_column(String(300))
    role: Mapped[str | None] = mapped_column(String(80), nullable=True)
    title: Mapped[str] = mapped_column(String(500), default="")

    # Join key back to jobs. Populated on only some Notion rows, and the ids
    # come from several ATSes, so it is not a foreign key.
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    source: Mapped[str | None] = mapped_column(String(20), nullable=True)

    applied_at: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Where it stands now: applied / rejected / withdrawn / offer / accepted.
    status: Mapped[str] = mapped_column(String(40), default="applied")

    # How far it actually got. NULL means unknown and needing backfill — for
    # imported rejections this is genuinely unknown, and guessing "applied"
    # would bake in the very undercount this column exists to fix.
    highest_round: Mapped[str | None] = mapped_column(String(40), nullable=True)

    referral: Mapped[str | None] = mapped_column(String(200), nullable=True)
    salary_range: Mapped[str | None] = mapped_column(String(200), nullable=True)

    imported_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


# Which ATS APIs the scan step knows how to call. LinkedIn is excluded: it has
# its own email-based capture path, not a company board list.
ATS_SOURCES = ["greenhouse", "ashby", "lever", "workday", "oracle"]


class TrackedCompany(Base):
    """A company's job board to scan for openings.

    User-managed, not a hardcoded list — added and removed from the ATS Boards
    page. The API URL is derived from (source, board_token) rather than stored,
    so there is nothing to fall out of sync with.
    """

    __tablename__ = "tracked_companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    company: Mapped[str] = mapped_column(String(300))
    source: Mapped[str] = mapped_column(String(20))
    board_token: Mapped[str] = mapped_column(String(200))

    # Scanned without being removed — keeps the company's fetch history if
    # re-enabled, rather than losing it to a delete-and-re-add.
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class IcpResume(Base):
    """One ICP Resume generation for one posting.

    Every run appends, same reasoning as Evaluation: a prompt-version change
    makes runs incomparable, and the only way to tell which is which is the
    version stamped on the row. company/title are copied from Job at
    generation time so this table reads standalone, same convention as
    JobNormalized.
    """

    __tablename__ = "icp_resumes"
    __table_args__ = (
        ForeignKeyConstraint(["source", "job_id"], ["jobs.source", "jobs.job_id"]),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(20))
    job_id: Mapped[str] = mapped_column(String(64))

    company: Mapped[str] = mapped_column(String(300))
    title: Mapped[str] = mapped_column(String(500))

    # One entry per included experience: {"context": str, "bullets": [str]}.
    experience: Mapped[list] = mapped_column(JSON, default=list)

    model: Mapped[str] = mapped_column(String(60))
    prompt_version: Mapped[str] = mapped_column(String(20))
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)

    generated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Resume(Base):
    """One tailored resume, as ingested from a PDF.

    Data layer only, for a future resume assembler — stores just the parts
    that change between resumes (headline, section headers, bullet text).
    Anything constant across every resume (name, contact line, section
    titles, company/degree lines, Work Authorization) is not stored; it is
    generated by code later. id is a readable path-style string, not a
    surrogate int, because this table is populated by a one-off ingest
    script a human runs and debugs by eye, not by the app at request time.

    Two ways a row gets here, both in resume_ingest_service.py: a one-off
    batch script over old resumes named by the user's own filename
    convention (application_id stays NULL — nothing tracked ties them to a
    specific application), or an upload against a specific Application row
    in the "Upload Resumes" tab (application_id set, company/title/date
    taken from that Application rather than parsed from the filename).
    filename is not unique for this reason — two uploads through the tab can
    share a generic browser filename like "resume.pdf".
    """

    __tablename__ = "resumes"

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    filename: Mapped[str] = mapped_column(String(300))
    company: Mapped[str | None] = mapped_column(String(300), nullable=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    resume_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    application_id: Mapped[int | None] = mapped_column(ForeignKey("applications.id"), nullable=True)

    # Verbatim second line of the resume. No name, no contact line.
    headline: Mapped[str | None] = mapped_column(String(500), nullable=True)


class Section(Base):
    """One resume section slot (a company stint or an education entry).

    Only sections actually present on that resume get a row — a resume with
    no Storm stint has no storm section. Section order is not stored: it is
    fixed by slot (reverse chronological), and whether Education or
    Experience prints first is a layout choice for the assembler.
    """

    __tablename__ = "sections"
    __table_args__ = (UniqueConstraint("resume_id", "slot", name="uq_sections_resume_slot"),)

    id: Mapped[str] = mapped_column(String(140), primary_key=True)
    resume_id: Mapped[str] = mapped_column(ForeignKey("resumes.id"))
    slot: Mapped[str] = mapped_column(String(20))

    # The role row as printed (e.g. "Product Manager, Growth - Consumer App,
    # 2022 - 2025"). NULL for education slots and for additional — those have
    # no role row.
    header: Mapped[str | None] = mapped_column(String(300), nullable=True)


class Bullet(Base):
    """One bullet, verbatim, including exact duplicates across resumes.

    No story ids, no tags: the same accomplishment is reworded in every
    resume and cannot be reliably labeled, so the assembler — not this
    schema — decides what to swap. A bullet's section is per resume; the
    same accomplishment can sit under fet_am in one resume and fet_ma in
    another.
    """

    __tablename__ = "bullets"
    __table_args__ = (UniqueConstraint("section_id", "position", name="uq_bullets_section_position"),)

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    section_id: Mapped[str] = mapped_column(ForeignKey("sections.id"))
    # Sort by this, never by the id string.
    position: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)


class AssemblyRun(Base):
    """One "Build My Resume" run of the Resume Assembler for one posting.

    The working copy lives in `draft` as a self-contained JSON snapshot —
    never in resumes/sections/bullets, which stay the verbatim record of what
    was actually sent. Every header and bullet in the draft carries the
    resume (and bullet) it came from. anchor/donor ids are plain strings, not
    foreign keys: the draft already holds the full text, so a run stays
    readable even after the resumes it drew from are deleted or re-ingested.
    """

    __tablename__ = "assembly_runs"
    __table_args__ = (
        ForeignKeyConstraint(["source", "job_id"], ["jobs.source", "jobs.job_id"]),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(20))
    job_id: Mapped[str] = mapped_column(String(64))
    company: Mapped[str] = mapped_column(String(300))
    title: Mapped[str] = mapped_column(String(500))

    anchor_resume_id: Mapped[str] = mapped_column(String(120))
    donor_resume_ids: Mapped[list] = mapped_column(JSON, default=list)
    # The ranked candidates the seed step walked, including ones skipped for
    # having no resume — so a thin seed can be explained, not just observed.
    seed: Mapped[dict] = mapped_column(JSON, default=dict)
    # {"headline": str, "sections": [{"slot", "header": {text, source_resume_id} | None,
    #   "bullets": [{text, source_resume_id, source_bullet_id}]}]}
    draft: Mapped[dict] = mapped_column(JSON, default=dict)

    # seeded / running / passed / hit_cap / error
    status: Mapped[str] = mapped_column(String(20), default="seeded")
    rounds_used: Mapped[int] = mapped_column(Integer, default=0)
    turns_used: Mapped[int] = mapped_column(Integer, default=0)
    # Latest verdict per scanner, keyed "ats" / "recruiter" / "hard_gate".
    verdicts: Mapped[dict] = mapped_column(JSON, default=dict)
    # Prompt version used per agent kind, e.g. {"assembler": "v1", "ats_scanner": "v1"}.
    prompt_versions: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)

    started_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AssemblyTurn(Base):
    """One step of an assembly run, written the moment it happens — this is
    what the live tracer polls. A model call and each tool call it requested
    are separate rows, in order."""

    __tablename__ = "assembly_turns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("assembly_runs.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    # model / tool / system
    kind: Mapped[str] = mapped_column(String(20))
    tool_name: Mapped[str | None] = mapped_column(String(60), nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    model: Mapped[str | None] = mapped_column(String(60), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class BulletTag(Base):
    """A user-defined tag for resume bullets (e.g. "Lifecycle/CRM").

    category is one of ROLE_CATEGORIES, or None for an uncategorized tag;
    it drives the chip color. definition is what a tag means — read by the
    user, and by the planned tag suggester.
    """

    __tablename__ = "bullet_tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    definition: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class BulletTagging(Base):
    """One tag on one bullet *sentence*.

    Keyed by the sentence (whitespace-collapsed), not by a bullet row: the
    same sentence sits in many resumes, so tagging it once tags every copy,
    and a future upload with the identical sentence inherits its tags. A
    reworded variant is a different sentence and is tagged separately.
    """

    __tablename__ = "bullet_taggings"

    text_key: Mapped[str] = mapped_column(Text, primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("bullet_tags.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class TagSuggestBatch(Base):
    """One call to the tag suggester: which sentences it was shown, and what
    it cost. `texts` doubles as the record of which sentences have already
    been through the suggester, so a re-run does not pay to ask again."""

    __tablename__ = "tag_suggest_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    texts: Mapped[list] = mapped_column(JSON, default=list)
    model: Mapped[str] = mapped_column(String(60), default="")
    prompt_version: Mapped[str] = mapped_column(String(20), default="v1")
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class BulletTagSuggestion(Base):
    """A tag the suggester proposed for a sentence, and what the user did
    with it. Never applied on its own: status stays "suggested" until the
    user accepts (the tag is applied) or rejects (it is never proposed again
    for that sentence). The accepted / rejected split is how far the
    suggester can be trusted."""

    __tablename__ = "bullet_tag_suggestions"
    __table_args__ = (UniqueConstraint("text_key", "tag_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    text_key: Mapped[str] = mapped_column(Text, index=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("bullet_tags.id"))
    reason: Mapped[str] = mapped_column(Text, default="")
    # suggested / accepted / rejected
    status: Mapped[str] = mapped_column(String(20), default="suggested")
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("tag_suggest_batches.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

