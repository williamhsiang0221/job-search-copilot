"""Parses a tailored resume PDF into the resumes/sections/bullets data layer.

Data layer only, for a future resume assembler -- see app/models.py's Resume/
Section/Bullet docstrings for what is and isn't stored and why.

Slot detection deliberately does not match on role-title wording (e.g.
"^Assistant Manager,"). The same FET stint is titled differently in every
resume -- "Assistant Manager, Product Manager" in one, "Assistant Manager,
Growth Analytics Lead" in another -- because rewording the same experience is
the entire point of a tailored resume. The one thing that stays constant
across rewordings is the employment date range printed at the end of the role
line, so FET's three sub-roles are told apart by that instead.

The parser fails loudly on anything it doesn't recognize rather than guessing.
A wrapped bullet line is the only thing allowed to fall through unmatched, and
it has a known shape (column 0, not date-prefixed, not an all-caps heading).
The alternative -- folding any unrecognized line into the previous bullet --
once silently filed a whole internship under the previous employer's section.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import resume_layout
from app.db import session_scope
from app.manual_capture_service import extract_text
from app.models import Application, Bullet, Resume, Section

BULLET_PREFIX = "•"

# Pure structural noise -- printed but carry no data of their own.
SECTION_MARKERS = {"EDUCATION", "EXPERIENCE"}

# Headings whose body is a prose paragraph rather than bullets. The whole
# paragraph is stored as the section's single bullet, wrapped lines joined.
PARAGRAPH_SECTIONS = {"PROFESSIONAL SUMMARY": "summary", "SUMMARY": "summary"}

# Any other all-caps line is an unknown section heading, and raises -- after
# a bullet it would otherwise be swallowed as a wrapped continuation.
_HEADING_RE = re.compile(r"^[A-Z][A-Z &]{3,}$")

# Substring anchors, not full-line matches: the rest of a company/education
# line (dates, descriptor text, location) is constant and code-generated
# later, so this only needs to recognize the line, not capture it. The
# anchors themselves are the candidate's, from the profile's
# resume_layout.json (see app/resume_layout.py).
#
# Anchors are only checked on date-prefixed lines (_DATE_PREFIX_RE): an
# employer's name can also appear mid-bullet ("presented recommendations to
# Acme's BI leadership"), and a wrapped bullet line starting there must not be
# taken for that employer's company line.
def _layout_rules(layout: resume_layout.ResumeLayout):
    """(company anchors -> employer index, education anchors -> slot,
    employer index -> its one role's slot, employer index -> {years: slot})."""
    company_anchors = {e["anchor"]: i for i, e in enumerate(layout.employers)}
    # An employer with one role: the first non-bullet line after its company
    # line is that role's header.
    single_role_slot = {i: e["roles"][0]["slot"] for i, e in enumerate(layout.employers) if len(e["roles"]) == 1}
    # An employer with several roles (FET has three): told apart by the fixed
    # employment date range at the end of each role line -- see module
    # docstring.
    year_range_to_slot = {
        i: {r["years"]: r["slot"] for r in e["roles"]} for i, e in enumerate(layout.employers) if len(e["roles"]) > 1
    }
    return company_anchors, layout.education_anchors, single_role_slot, year_range_to_slot


# How every company and education line starts ("Spring 2026 Acme Health ...",
# "2018 - 2025 Acme Mobile ..."). A date-prefixed line that matches no anchor
# is a new employer or school, and raises rather than being read as a bullet.
_DATE_PREFIX_RE = re.compile(r"^(?:(?:Spring|Summer|Fall|Winter) \d{4}|\d{4}\s*[-–—]\s*\d{4})\s")

# Hyphen, en dash or em dash -- the McKinsey resume printed "2022 – 2025".
_YEAR_RANGE_RE = re.compile(r"(\d{4})\s*[-–—]\s*(\d{4})\s*$")

# Control characters pypdf can leave behind mid-word (seen once as a stray
# \x02 in place of a hyphen). Anything else under this pattern is unexpected
# and should fail loudly rather than silently ride into stored text.
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


class ResumeIngestError(Exception):
    pass


@dataclass
class ParsedSection:
    slot: str
    header: str | None
    bullets: list[str] = field(default_factory=list)


@dataclass
class ParsedResume:
    headline: str
    sections: list[ParsedSection]


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def parse_filename(filename: str, layout: resume_layout.ResumeLayout | None = None) -> tuple[date, str, str]:
    """Split a resume filename into (date, title, company) using the profile's
    filename_pattern, e.g. `{Name} Resume {yyyymmdd} {Title} @ {Company}.pdf`.

    Two known filenames break this shape (a literal "&" or an accented
    letter mangled on save) -- that's what --company/--title override for,
    not a reason to make this regex looser.
    """
    layout = layout or resume_layout.DEFAULT
    match = layout.filename_re.match(filename)
    if not match:
        raise ResumeIngestError(f"filename does not match '{layout.filename_example}': {filename!r}")
    resume_date = datetime.strptime(match.group("date"), "%Y%m%d").date()
    return resume_date, match.group("title").strip(), match.group("company").strip()


def build_resume_id(resume_date: date, company: str, title: str) -> str:
    title_words = " ".join(title.split()[:3])
    return f"{resume_date:%Y%m%d}_{slugify(company)}_{slugify(title_words)}"


def _sanitize(text: str) -> str:
    text = text.replace("\x02", "-")
    stray = sorted(set(_CONTROL_CHAR_RE.findall(text)))
    if stray:
        raise ResumeIngestError(
            f"unexpected control characters in extracted PDF text: {[hex(ord(c)) for c in stray]}"
        )
    return text


def parse_resume_text(text: str, layout: resume_layout.ResumeLayout | None = None) -> ParsedResume:
    """Parse with the given layout, or the active profile's."""
    company_anchors, education_anchors, single_role_slot, year_range_to_slot = _layout_rules(
        layout or resume_layout.DEFAULT
    )
    # Leading whitespace is kept long enough to record which lines were
    # indented: pypdf prints every role header and degree line with a leading
    # space and every wrapped bullet line at column 0 (true of all 11 real
    # resumes checked), so an indented line is never a bullet continuation.
    raw_lines = [ln for ln in _sanitize(text).split("\n") if ln.strip()]
    lines = [ln.strip() for ln in raw_lines]
    indented = [ln[:1].isspace() for ln in raw_lines]

    if len(lines) < 4:
        raise ResumeIngestError("resume text too short to contain name/headline/contact/body")

    headline = lines[1]
    body = list(zip(lines[3:], indented[3:]))  # drop name, headline, contact line

    sections: list[ParsedSection] = []
    by_slot: dict[str, ParsedSection] = {}
    current_slot: str | None = None
    current_company: str | None = None
    expect_degree_next = False
    pending_bullet: str | None = None

    def flush_bullet() -> None:
        nonlocal pending_bullet
        if pending_bullet is None:
            return
        section = by_slot[current_slot]
        # Constant, code-generated later -- and here it is fused onto the
        # Languages half of the same bullet line, so the whole bullet drops.
        if section.slot == "additional" and pending_bullet.startswith("Work Authorization"):
            pending_bullet = None
            return
        section.bullets.append(pending_bullet)
        pending_bullet = None

    def start_section(slot: str, header: str | None) -> None:
        nonlocal current_slot
        flush_bullet()
        if slot not in by_slot:
            section = ParsedSection(slot=slot, header=header)
            by_slot[slot] = section
            sections.append(section)
        current_slot = slot

    for line, is_indented in body:
        if line in SECTION_MARKERS:
            continue

        if line in PARAGRAPH_SECTIONS:
            current_company = None
            start_section(PARAGRAPH_SECTIONS[line], header=None)
            continue

        dated = not is_indented and bool(_DATE_PREFIX_RE.match(line))

        company = next((v for k, v in company_anchors.items() if k in line), None) if dated else None
        if company is not None:
            flush_bullet()
            current_company = company
            current_slot = None  # next non-bullet line is that stint's role header
            continue

        education_slot = next((v for k, v in education_anchors.items() if k in line), None) if dated else None
        if education_slot is not None:
            current_company = None
            start_section(education_slot, header=None)
            expect_degree_next = True
            continue

        if line == "ADDITIONAL DATA":
            current_company = None
            start_section("additional", header=None)
            continue

        if dated:
            raise ResumeIngestError(f"date-prefixed line matches no known employer or school: {line!r}")

        if _HEADING_RE.match(line):
            raise ResumeIngestError(f"unknown section heading: {line!r}")

        if expect_degree_next:
            expect_degree_next = False
            continue  # degree line -- constant, dropped

        if line.startswith(BULLET_PREFIX):
            flush_bullet()
            pending_bullet = line[len(BULLET_PREFIX):].strip()
            continue

        # A role header for a several-role employer (FET) is identified by its
        # trailing employment date range, checked on every line regardless of
        # current_slot, because those roles come in sequence and only the
        # first follows the company anchor directly.
        if current_company in year_range_to_slot:
            match = _YEAR_RANGE_RE.search(line)
            year_range = f"{match.group(1)} - {match.group(2)}" if match else None
            if year_range in year_range_to_slot[current_company]:
                start_section(year_range_to_slot[current_company][year_range], header=line)
                continue

        if current_company in single_role_slot and current_slot is None:
            start_section(single_role_slot[current_company], header=line)
            continue

        # Past this point the only legitimate line is a wrapped bullet
        # continuation, which is never indented -- see the top of this function.
        if is_indented:
            raise ResumeIngestError(f"indented line is not a known role header or degree line: {line!r}")

        if current_slot in PARAGRAPH_SECTIONS.values():
            pending_bullet = line if pending_bullet is None else f"{pending_bullet} {line}"
            continue

        if pending_bullet is not None:
            pending_bullet = f"{pending_bullet} {line}"
            continue

        raise ResumeIngestError(f"unrecognized line, no pending bullet to continue: {line!r}")

    flush_bullet()
    return ParsedResume(headline=headline, sections=sections)


def _persist(
    session: Session,
    *,
    resume_id: str,
    filename: str,
    company: str | None,
    title: str | None,
    resume_date: date | None,
    application_id: int | None,
    parsed: ParsedResume,
) -> dict:
    session.add(
        Resume(
            id=resume_id,
            filename=filename,
            company=company,
            title=title,
            resume_date=resume_date,
            application_id=application_id,
            headline=parsed.headline,
        )
    )
    for section in parsed.sections:
        section_id = f"{resume_id}/{section.slot}"
        session.add(Section(id=section_id, resume_id=resume_id, slot=section.slot, header=section.header))
        for position, bullet_text in enumerate(section.bullets, start=1):
            session.add(
                Bullet(id=f"{section_id}/{position}", section_id=section_id, position=position, text=bullet_text)
            )
    session.flush()

    return {
        "status": "ingested",
        "resume_id": resume_id,
        "sections": len(parsed.sections),
        "bullets": sum(len(s.bullets) for s in parsed.sections),
    }


def ingest_resume(
    pdf_path: Path,
    *,
    session: Session,
    company_override: str | None = None,
    title_override: str | None = None,
) -> dict:
    """Batch path: a one-off script over old resumes named by the user's own
    convention. Idempotent by filename, since that's the one thing a batch of
    files reliably has that a browser upload doesn't."""
    filename = pdf_path.name

    existing_by_filename = session.scalar(select(Resume).where(Resume.filename == filename))
    if existing_by_filename is not None:
        return {"status": "already_ingested", "resume_id": existing_by_filename.id}

    resume_date, parsed_title, parsed_company = parse_filename(filename)
    company = company_override or parsed_company
    title = title_override or parsed_title
    resume_id = build_resume_id(resume_date, company, title)

    if session.get(Resume, resume_id) is not None:
        raise ResumeIngestError(
            f"resume id {resume_id!r} already exists under a different filename "
            "-- refusing to silently overwrite"
        )

    parsed = parse_resume_text(extract_text(pdf_path.read_bytes()))
    return _persist(
        session,
        resume_id=resume_id,
        filename=filename,
        company=company,
        title=title,
        resume_date=resume_date,
        application_id=None,
        parsed=parsed,
    )


# Reverse chronological, matching how a resume actually prints. Display
# convenience only, for the All Applications expand panel -- the schema
# itself deliberately doesn't store section order (see models.py).
# Print order, from the profile's resume layout.
SLOT_DISPLAY_ORDER = resume_layout.SLOT_DISPLAY_ORDER


def resume_for_application(application_id: int) -> dict | None:
    """The parsed resume attached to this application, if any."""
    with session_scope() as session:
        resume = session.scalar(select(Resume).where(Resume.application_id == application_id))
        if resume is None:
            return None

        by_slot = {s.slot: s for s in session.query(Section).filter_by(resume_id=resume.id).all()}
        ordered_slots = [slot for slot in SLOT_DISPLAY_ORDER if slot in by_slot]
        ordered_slots += [slot for slot in by_slot if slot not in SLOT_DISPLAY_ORDER]

        sections = []
        for slot in ordered_slots:
            section = by_slot[slot]
            bullets = session.query(Bullet).filter_by(section_id=section.id).order_by(Bullet.position).all()
            sections.append({"slot": slot, "header": section.header, "bullets": [b.text for b in bullets]})

        return {"resume_id": resume.id, "headline": resume.headline, "sections": sections}


_VERSION_SUFFIX_RE = re.compile(r"_v(\d+)$")


def _delete_resume(session: Session, resume_id: str) -> None:
    """Children first: the schema declares no cascades."""
    section_ids = select(Section.id).where(Section.resume_id == resume_id)
    session.execute(delete(Bullet).where(Bullet.section_id.in_(section_ids)))
    session.execute(delete(Section).where(Section.resume_id == resume_id))
    session.execute(delete(Resume).where(Resume.id == resume_id))
    session.flush()


def attach_resume_to_application(
    application_id: int, filename: str, pdf_bytes: bytes, *, replace: bool = False
) -> dict:
    """Uploads a resume against a known application. Company/title/date come
    from the Application row itself, not parsed from the filename -- unlike
    the batch path, the point of picking a specific application is that its
    identity is already known, so the upload doesn't depend on the user
    having kept their own filename convention.

    Idempotent by application_id: an application that already has a resume
    is reported as already-linked rather than gaining a second row. The
    worklist this feeds is now attachments_service.applications_needing_
    attachments, merged with the JD-linking worklist.

    replace=True swaps an existing resume for this one instead. The new PDF
    is parsed before anything is deleted, so a bad upload leaves the old
    resume untouched. The new resume gets a version-suffixed id (_v2, _v3,
    ...) so its bullet ids never reuse the old ones -- Resume Assembler runs
    keep source_bullet_id strings, which would otherwise silently point at
    different text.
    """
    with session_scope() as session:
        application = session.get(Application, application_id)
        if application is None:
            raise ResumeIngestError(f"no application with id {application_id}")

        existing = session.scalar(select(Resume).where(Resume.application_id == application_id))
        if existing is not None and not replace:
            return {"status": "already_linked", "resume_id": existing.id}

        resume_date = application.applied_at or date.today()
        company, title = application.company, application.title
        # Prefixed with the application id, which is already unique on its
        # own -- date/company/title-words just keep the id human-readable,
        # the way build_resume_id's do for the batch path.
        resume_id = f"app{application_id}_{build_resume_id(resume_date, company or '', title or '')}"

        parsed = parse_resume_text(extract_text(pdf_bytes))

        replaced_resume_id = None
        if existing is not None:
            replaced_resume_id = existing.id
            version_match = _VERSION_SUFFIX_RE.search(existing.id)
            version = (int(version_match.group(1)) if version_match else 1) + 1
            while session.get(Resume, f"{resume_id}_v{version}") is not None:
                version += 1
            resume_id = f"{resume_id}_v{version}"
            _delete_resume(session, existing.id)

        result = _persist(
            session,
            resume_id=resume_id,
            # Namespaced by application id: a browser upload's filename can
            # be a generic "resume.pdf" reused across applications, and this
            # column still carries a UNIQUE constraint on existing databases
            # created before this path existed.
            filename=f"app{application_id}/{filename}",
            company=company,
            title=title,
            resume_date=resume_date,
            application_id=application_id,
            parsed=parsed,
        )
        if replaced_resume_id is not None:
            result["status"] = "replaced"
            result["replaced_resume_id"] = replaced_resume_id
        return result
