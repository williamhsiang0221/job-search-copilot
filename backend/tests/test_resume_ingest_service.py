"""Resume ingest: parsing a tailored resume PDF into resumes/sections/bullets.

Runs on hand-written resume text for the fictional example profile
(backend/conftest.py). The acceptance tests over the owner's real resume
PDFs — word-for-word round trip, misfiled-text check, pilot ingests — live
with the owner's profile in profile/tests/, since they hold personal
filenames and figures and are never published.
"""

import pytest

from app import db
from app.models import Application, Bullet, Resume, Section
from app.resume_ingest_service import (
    ResumeIngestError,
    attach_resume_to_application,
    build_resume_id,
    parse_filename,
    parse_resume_text,
    resume_for_application,
    slugify,
)


# --- filename / id parsing -------------------------------------------------


def test_parse_filename_splits_date_title_company():
    resume_date, title, company = parse_filename(
        "Jordan Lee Resume 20260723 AI Strategy and Implementation Lead @ Verizon.pdf"
    )
    assert resume_date.isoformat() == "2026-07-23"
    assert title == "AI Strategy and Implementation Lead"
    assert company == "Verizon"


def test_parse_filename_rejects_unrecognized_shape():
    with pytest.raises(ResumeIngestError):
        parse_filename("resume_final_v2.pdf")


def test_slugify_lowercases_and_collapses_punctuation():
    assert slugify("AI Strategy and") == "ai-strategy-and"
    assert slugify("McKinsey & Company") == "mckinsey-company"


def test_build_resume_id_uses_date_company_first_three_title_words():
    from datetime import date

    assert build_resume_id(date(2026, 9, 29), "Uber", "Sr Strategic Operations Manager") == (
        "20260929_uber_sr-strategic-operations"
    )


# --- parse_resume_text: structure ------------------------------------------

_MINIMAL = """\
JORDAN LEE
Headline Line
Contact Line
EDUCATION
2013 - 2017 RIVERTON UNIVERSITY Taipei, Taiwan
  Bachelor of Science in Statistics, June 2017
• Leadership: captain of the debate team
EXPERIENCE
2017 - 2018 Northbeam Digital Agency (CRM & analytics consultancy for global FMCG brands) Taipei, Taiwan
 Analyst
• Grew client sign-ups 40%
ADDITIONAL DATA
• Work Authorization: U.S. Citizen | Languages: English
• Tools: Python, SQL
"""


def test_parses_headline_and_slots():
    parsed = parse_resume_text(_MINIMAL)
    assert parsed.headline == "Headline Line"
    slots = {s.slot: s for s in parsed.sections}
    assert set(slots) == {"riverton", "northbeam", "additional"}
    assert slots["riverton"].header is None
    assert slots["riverton"].bullets == ["Leadership: captain of the debate team"]
    assert slots["northbeam"].header == "Analyst"


def test_work_authorization_bullet_is_dropped():
    parsed = parse_resume_text(_MINIMAL)
    slots = {s.slot: s for s in parsed.sections}
    assert slots["additional"].bullets == ["Tools: Python, SQL"]


def test_wrapped_bullet_continuation_is_joined_with_one_space():
    text = _MINIMAL.replace(
        "• Grew client sign-ups 40%",
        "• Grew client sign-ups 40% and revenue 12% for three retail\naccounts by leading a mobile app launch",
    )
    parsed = parse_resume_text(text)
    slots = {s.slot: s for s in parsed.sections}
    assert slots["northbeam"].bullets == [
        "Grew client sign-ups 40% and revenue 12% for three retail accounts by leading a mobile app launch"
    ]


def test_fet_sub_roles_are_told_apart_by_trailing_date_range_not_title_wording():
    text = """\
JORDAN LEE
Headline
Contact
EXPERIENCE
2018 - 2025 Brightpath Mobile Telecom (FET) (Taiwan's 3rd largest telecom provider) Taipei, Taiwan
 Some Reworded Title A, 2022 - 2025
• bullet am
 A Totally Different Title B, 2021 - 2022
• bullet sda
 Yet Another Title C, 2019 - 2021
• bullet ma
"""
    parsed = parse_resume_text(text)
    slots = {s.slot: s for s in parsed.sections}
    assert slots["bp_pm"].bullets == ["bullet am"]
    assert slots["bp_sa"].bullets == ["bullet sda"]
    assert slots["bp_da"].bullets == ["bullet ma"]


def test_unrecognized_line_with_no_pending_bullet_raises():
    text = _MINIMAL.replace(
        "EDUCATION\n", "EDUCATION\nsome stray line that matches nothing and follows no bullet\n"
    )
    with pytest.raises(ResumeIngestError):
        parse_resume_text(text)


def test_stray_control_character_raises_instead_of_silently_kept():
    text = _MINIMAL.replace("Leadership", "Leader\x01ship")
    with pytest.raises(ResumeIngestError):
        parse_resume_text(text)


def test_known_x02_control_character_is_replaced_with_a_hyphen():
    from app.resume_ingest_service import _sanitize

    assert _sanitize("K\x02means") == "K-means"


_WITH_COURTSIDE = """\
JORDAN LEE
Headline
Contact
EXPERIENCE
Spring 2026 Carewell Health (digital primary-care startup; through Lakeshore AI Lab) Chicago, IL
 AI Product Manager, MBA Intern
• Built an LLM triage prototype on patient messages, sorting 312 unstructured requests into 6 urgency-ranked
care themes; secured COO sign-off
Fall 2025 Courtside Analytics (through Lakeshore Consulting Lab) Chicago, IL
 Analytical Consultant, MBA Intern
• Analyzed 210K ticket transactions to surface dynamic pricing
opportunities (up to 4.2x lift); presented recommendations to Courtside Analytics BI leadership
2019 - 2025 Brightpath Mobile (consumer fintech app, 3M users) New York, NY
 Assistant Manager, Product Manager, 2022 - 2025
• bullet am
 Senior Data Analyst, E-Commerce Vertical, 2021 - 2022
• bullet sda
"""


def test_internship_gets_its_own_slot_instead_of_joining_the_previous_employer():
    parsed = parse_resume_text(_WITH_COURTSIDE)
    slots = {s.slot: s for s in parsed.sections}
    assert slots["carewell"].bullets == [
        "Built an LLM triage prototype on patient messages, sorting 312 unstructured requests into 6 "
        "urgency-ranked care themes; secured COO sign-off"
    ]
    assert slots["courtside"].header == "Analytical Consultant, MBA Intern"


def test_employer_named_in_a_wrapped_bullet_line_is_not_read_as_a_company_line():
    parsed = parse_resume_text(_WITH_COURTSIDE)
    slots = {s.slot: s for s in parsed.sections}
    assert slots["courtside"].bullets == [
        "Analyzed 210K ticket transactions to surface dynamic pricing opportunities "
        "(up to 4.2x lift); presented recommendations to Courtside Analytics BI leadership"
    ]
    assert slots["bp_pm"].bullets == ["bullet am"]


def test_unknown_date_prefixed_employer_raises_instead_of_joining_the_previous_bullet():
    text = _WITH_COURTSIDE.replace("Fall 2025 Courtside Analytics", "Fall 2025 Acme Corp")
    with pytest.raises(ResumeIngestError, match="no known employer"):
        parse_resume_text(text)


@pytest.mark.parametrize("dash", ["–", "—"])
def test_fet_role_date_range_accepts_en_and_em_dash(dash):
    text = _WITH_COURTSIDE.replace("2022 - 2025\n", f"2022 {dash} 2025\n").replace(
        "2021 - 2022\n", f"2021 {dash} 2022\n"
    )
    parsed = parse_resume_text(text)
    slots = {s.slot: s for s in parsed.sections}
    # The second role is the silent case: with a hyphen-only pattern its
    # header and bullets used to fold into fet_am instead of raising.
    assert slots["bp_pm"].bullets == ["bullet am"]
    assert slots["bp_sa"].bullets == ["bullet sda"]
    assert slots["bp_sa"].header == f"Senior Data Analyst, E-Commerce Vertical, 2021 {dash} 2022"


def test_indented_role_header_with_unknown_date_range_raises():
    text = _WITH_COURTSIDE.replace("E-Commerce Vertical, 2021 - 2022", "E-Commerce Vertical, 2019 - 2022")
    with pytest.raises(ResumeIngestError, match="indented line"):
        parse_resume_text(text)


def test_unknown_section_heading_after_a_bullet_raises():
    text = _MINIMAL.replace("ADDITIONAL DATA", "PROJECTS")
    with pytest.raises(ResumeIngestError, match="unknown section heading"):
        parse_resume_text(text)


@pytest.mark.parametrize("heading", ["PROFESSIONAL SUMMARY", "SUMMARY"])
def test_summary_paragraph_is_stored_as_one_bullet_in_a_summary_slot(heading):
    text = _MINIMAL.replace(
        "Contact Line\n",
        f"Contact Line\n{heading}\nProduct leader in consumer fintech with 6 years,\nshipping growth features.\n",
    )
    parsed = parse_resume_text(text)
    slots = {s.slot: s for s in parsed.sections}
    assert slots["summary"].header is None
    assert slots["summary"].bullets == ["Product leader in consumer fintech with 6 years, shipping growth features."]
    assert parsed.sections[0].slot == "summary"


# --- DB-level ingest --------------------------------------------------------


@pytest.fixture
def fresh_db(tmp_path):
    db.reset_for_tests(tmp_path / "test.db")
    yield
    db.reset_for_tests(tmp_path / "unused.db")


def test_position_sorts_numerically_not_by_id_string(fresh_db):
    with db.session_scope() as session:
        session.add(Resume(id="r1", filename="r1.pdf", company="Acme", title="X"))
        session.add(Section(id="r1/northbeam", resume_id="r1", slot="northbeam", header="Analyst"))
        for position in (1, 2, 9, 10):
            session.add(
                Bullet(id=f"r1/northbeam/{position}", section_id="r1/northbeam", position=position, text=f"bullet {position}")
            )

    with db.session_scope() as session:
        rows = session.query(Bullet).filter_by(section_id="r1/northbeam").order_by(Bullet.position).all()
        assert [r.position for r in rows] == [1, 2, 9, 10]


def test_resume_for_application_returns_none_when_no_resume(fresh_db):
    with db.session_scope() as session:
        application = Application(company="Acme", title="PM")
        session.add(application)
        session.flush()
        application_id = application.id

    assert resume_for_application(application_id) is None


def test_resume_for_application_orders_sections_reverse_chronologically(fresh_db):
    with db.session_scope() as session:
        application = Application(company="Acme", title="PM")
        session.add(application)
        session.flush()
        application_id = application.id
        session.add(
            Resume(
                id="r1",
                filename="r1.pdf",
                company="Acme",
                title="PM",
                headline="A headline",
                application_id=application_id,
            )
        )
        # Inserted out of display order on purpose.
        session.add(Section(id="r1/riverton", resume_id="r1", slot="riverton", header=None))
        session.add(Section(id="r1/northbeam", resume_id="r1", slot="northbeam", header="Analyst"))
        session.add(Bullet(id="r1/riverton/1", section_id="r1/riverton", position=1, text="riverton bullet"))
        session.add(Bullet(id="r1/northbeam/1", section_id="r1/northbeam", position=1, text="northbeam bullet"))

    resume = resume_for_application(application_id)
    assert resume["headline"] == "A headline"
    assert [s["slot"] for s in resume["sections"]] == ["northbeam", "riverton"]
    assert resume["sections"][0]["bullets"] == ["northbeam bullet"]


def test_attach_resume_to_application_raises_for_unknown_application(fresh_db):
    with pytest.raises(ResumeIngestError):
        attach_resume_to_application(999, "resume.pdf", b"irrelevant")


@pytest.fixture
def application_with_text_pdfs(fresh_db, monkeypatch):
    """An application, plus extract_text stubbed so each upload's "PDF bytes"
    are just its text -- the replace path's logic doesn't depend on pypdf."""
    import app.resume_ingest_service as service

    monkeypatch.setattr(service, "extract_text", lambda pdf_bytes: pdf_bytes.decode())
    with db.session_scope() as session:
        application = Application(company="Coinbase", title="Growth PM")
        session.add(application)
        session.flush()
        return application.id


def _resume_rows(application_id):
    with db.session_scope() as session:
        resumes = session.query(Resume).filter_by(application_id=application_id).all()
        return [
            (
                r.id,
                {s.slot: [b.text for b in session.query(Bullet).filter_by(section_id=s.id).order_by(Bullet.position)]
                 for s in session.query(Section).filter_by(resume_id=r.id)},
            )
            for r in resumes
        ]


def test_replace_swaps_the_resume_under_a_version_suffixed_id(application_with_text_pdfs):
    application_id = application_with_text_pdfs
    first = attach_resume_to_application(application_id, "v1.pdf", _MINIMAL.encode())
    updated = _MINIMAL.replace("Tools: Python, SQL", "Tools: Python, SQL, dbt")

    second = attach_resume_to_application(application_id, "v2.pdf", updated.encode(), replace=True)

    assert second["status"] == "replaced"
    assert second["replaced_resume_id"] == first["resume_id"]
    assert second["resume_id"] == f"{first['resume_id']}_v2"
    [(resume_id, slots)] = _resume_rows(application_id)
    assert resume_id == second["resume_id"]
    assert slots["additional"] == ["Tools: Python, SQL, dbt"]
    with db.session_scope() as session:
        # Children of the old resume are gone too, not orphaned.
        assert session.query(Section).filter(Section.resume_id == first["resume_id"]).count() == 0
        assert session.query(Bullet).filter(Bullet.section_id.like(f"{first['resume_id']}/%")).count() == 0


def test_replacing_twice_bumps_the_version_again(application_with_text_pdfs):
    application_id = application_with_text_pdfs
    first = attach_resume_to_application(application_id, "v1.pdf", _MINIMAL.encode())
    attach_resume_to_application(application_id, "v2.pdf", _MINIMAL.encode(), replace=True)
    third = attach_resume_to_application(application_id, "v3.pdf", _MINIMAL.encode(), replace=True)

    assert third["resume_id"] == f"{first['resume_id']}_v3"
    assert [resume_id for resume_id, _ in _resume_rows(application_id)] == [third["resume_id"]]


def test_replace_with_an_unparseable_resume_keeps_the_old_one(application_with_text_pdfs):
    application_id = application_with_text_pdfs
    first = attach_resume_to_application(application_id, "v1.pdf", _MINIMAL.encode())
    broken = _MINIMAL.replace("ADDITIONAL DATA", "PROJECTS")

    with pytest.raises(ResumeIngestError):
        attach_resume_to_application(application_id, "v2.pdf", broken.encode(), replace=True)

    [(resume_id, slots)] = _resume_rows(application_id)
    assert resume_id == first["resume_id"]
    assert slots["additional"] == ["Tools: Python, SQL"]


def test_attach_resume_endpoint_passes_replace_query_flag(application_with_text_pdfs):
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    url = f"/api/applications/{application_with_text_pdfs}/attach-resume"

    def upload(**params):
        files = {"file": ("resume.pdf", _MINIMAL.encode(), "application/pdf")}
        return client.post(url, files=files, params=params).json()["status"]

    assert upload() == "ingested"
    assert upload() == "already_linked"
    assert upload(replace="true") == "replaced"


def test_replace_on_an_application_with_no_resume_is_a_plain_ingest(application_with_text_pdfs):
    result = attach_resume_to_application(application_with_text_pdfs, "v1.pdf", _MINIMAL.encode(), replace=True)
    assert result["status"] == "ingested"
    assert not result["resume_id"].endswith("_v2")
