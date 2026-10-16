"""Bullet Bank: distinct sentences, plain substring AND search, and tags."""

from datetime import date

import pytest

from app import db
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
from app.models import Bullet, Resume, Section

DEFINE = "Defined success metrics and led the AI rollout"
CAMPAIGN = "Ran a lifecycle campaign that lifted retention 12%"


@pytest.fixture
def bank(tmp_path):
    """Two resumes sharing DEFINE (one with odd spacing), one with CAMPAIGN."""
    db.reset_for_tests(tmp_path / "test.db")
    with db.session_scope() as session:
        for rid, day, company in (("r1", 1, "Acme"), ("r2", 20, "Beta")):
            session.add(Resume(id=rid, filename=f"{rid}.pdf", company=company, title="PM", resume_date=date(2026, 9, day)))
            session.add(Section(id=f"{rid}/fet_am", resume_id=rid, slot="fet_am"))
        session.add(Bullet(id="r1/fet_am/1", section_id="r1/fet_am", position=1, text=DEFINE))
        session.add(Bullet(id="r2/fet_am/1", section_id="r2/fet_am", position=1, text=DEFINE.replace(" the ", "  the ")))
        session.add(Bullet(id="r2/fet_am/2", section_id="r2/fet_am", position=2, text=CAMPAIGN))
    yield
    db.reset_for_tests(tmp_path / "unused.db")


def test_the_same_sentence_in_two_resumes_is_one_row(bank):
    rows = {r["text"]: r for r in list_bank()}
    assert set(rows) == {DEFINE, CAMPAIGN}
    assert rows[DEFINE]["resume_count"] == 2
    assert rows[DEFINE]["last_used"] == "2026-09-20"
    assert [r["company"] for r in rows[DEFINE]["resumes"]] == ["Beta", "Acme"]
    assert rows[DEFINE]["slots"] == ["fet_am"]


def test_keywords_are_comma_separated_case_insensitive_substrings_all_required(bank):
    assert parse_keywords(" Define, AI ,, ") == ["define", "ai"]
    assert [r["text"] for r in list_bank(["define", "ai"])] == [DEFINE]
    # Plain substring, as chosen: "ai" also matches inside "campaign".
    assert {r["text"] for r in list_bank(["ai"])} == {DEFINE, CAMPAIGN}
    assert list_bank(["define", "retention"]) == []


def test_tags_filter_with_and_and_untagged(bank):
    ai = create_tag("Agentic/LLM Product", "Product Manager", "LLM products")
    lifecycle = create_tag("Lifecycle/CRM", "Marketing")
    set_sentence_tags(DEFINE, [ai["id"], lifecycle["id"]])
    set_sentence_tags(CAMPAIGN, [lifecycle["id"]])

    assert {r["text"] for r in list_bank(tag_ids=[lifecycle["id"]])} == {DEFINE, CAMPAIGN}
    assert [r["text"] for r in list_bank(tag_ids=[lifecycle["id"], ai["id"]])] == [DEFINE]
    assert list_bank(untagged=True) == []
    set_sentence_tags(CAMPAIGN, [])
    assert [r["text"] for r in list_bank(untagged=True)] == [CAMPAIGN]


def test_tagging_matches_a_sentence_regardless_of_spacing(bank):
    tag = create_tag("Pilot-to-Scale", "Strategy")
    # The odd-spacing copy is the same sentence.
    set_sentence_tags(DEFINE.replace(" the ", "   the "), [tag["id"]])
    assert list_bank(tag_ids=[tag["id"]])[0]["text"] == DEFINE


def test_tag_rules(bank):
    tag = create_tag("Workflow Automation", "Strategy", "Automating manual processes")
    with pytest.raises(BulletBankError, match="already exists"):
        create_tag("workflow automation")
    with pytest.raises(BulletBankError, match="unknown category"):
        create_tag("Other", "Sales")
    with pytest.raises(BulletBankError, match="no bullet"):
        set_sentence_tags("A sentence no resume has", [tag["id"]])
    with pytest.raises(BulletBankError, match="no tag"):
        set_sentence_tags(DEFINE, [999])

    uncategorized = create_tag("One-off", None)
    assert uncategorized["category"] is None
    assert update_tag(tag["id"], definition="Cut cycle time")["definition"] == "Cut cycle time"


def test_tags_list_in_role_order_with_usage_and_delete_untags(bank):
    marketing = create_tag("Lifecycle/CRM", "Marketing")
    pm = create_tag("Experimentation", "Product Manager")
    set_sentence_tags(CAMPAIGN, [marketing["id"]])

    assert [(t["name"], t["usage"]) for t in list_tags()] == [("Experimentation", 0), ("Lifecycle/CRM", 1)]

    delete_tag(marketing["id"])
    assert [t["name"] for t in list_tags()] == ["Experimentation"]
    assert {r["text"] for r in list_bank(untagged=True)} == {DEFINE, CAMPAIGN}
    assert [t["id"] for t in list_tags()] == [pm["id"]]
