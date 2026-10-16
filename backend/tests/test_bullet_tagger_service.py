"""Bullet Bank tag suggestions, driven by a scripted fake model."""

from datetime import date
from types import SimpleNamespace

import pytest

import app.bullet_tagger_service as tagger
from app import db
from app.bullet_bank_service import create_tag, list_bank, set_sentence_tags
from app.bullet_tagger_service import (
    BulletPicks,
    TaggerOutput,
    TagPick,
    decide,
    pending_sentences,
    suggest_tags,
    suggestion_stats,
    total_tagger_cost,
)
from app.models import Bullet, Resume, Section

EXPERIENCE = ["Built a churn model scoring 5M users", "Ran SMS win-back cutting churn 15%"]
EDUCATION = "Marketing Major | Dean's List"


class FakeClient:
    """Answers with picks keyed by sentence text, and records what it was sent."""

    def __init__(self, picks_by_text: dict[str, list[tuple[str, str]]]):
        self.picks_by_text = picks_by_text
        self.sent: list[str] = []
        self.messages = SimpleNamespace(parse=self._parse)

    def _parse(self, **kwargs):
        user = kwargs["messages"][0]["content"]
        self.sent.append(user)
        bullets = [line.split(". ", 1) for line in user.split("Bullets:\n", 1)[1].splitlines()]
        output = TaggerOutput(
            bullets=[
                BulletPicks(index=int(i), tags=[TagPick(tag=t, reason=r) for t, r in self.picks_by_text.get(text, [])])
                for i, text in bullets
            ]
        )
        return SimpleNamespace(parsed_output=output, usage=SimpleNamespace(input_tokens=2000, output_tokens=300))


@pytest.fixture
def bank(tmp_path):
    db.reset_for_tests(tmp_path / "test.db")
    with db.session_scope() as session:
        session.add(Resume(id="r1", filename="r1.pdf", company="Acme", resume_date=date(2026, 9, 1)))
        session.add(Section(id="r1/bp_pm", resume_id="r1", slot="bp_pm"))
        session.add(Section(id="r1/lakeshore", resume_id="r1", slot="lakeshore"))
        for i, text in enumerate(EXPERIENCE, start=1):
            session.add(Bullet(id=f"r1/bp_pm/{i}", section_id="r1/bp_pm", position=i, text=text))
        session.add(Bullet(id="r1/lakeshore/1", section_id="r1/lakeshore", position=1, text=EDUCATION))
    tags = {
        name: create_tag(name, category)["id"]
        for name, category in (
            ("Predictive Modeling", "Data Analyst"),
            ("Lifecycle/CRM", "Marketing"),
            ("Experimentation", "Product Manager"),
            ("Audience Targeting", "Marketing"),
        )
    }
    yield tags
    db.reset_for_tests(tmp_path / "unused.db")


def test_only_experience_bullets_are_sent(bank):
    client = FakeClient({})
    suggest_tags(client=client)
    sent = "\n".join(client.sent)
    assert all(text in sent for text in EXPERIENCE)
    assert EDUCATION not in sent
    assert "Tag: Predictive Modeling\n  Category: Data Analyst" in sent


def test_suggestions_are_stored_pending_and_filtered(bank):
    set_sentence_tags(EXPERIENCE[1], [bank["Lifecycle/CRM"]])
    client = FakeClient(
        {
            EXPERIENCE[0]: [
                ("Predictive Modeling", "builds a churn model"),
                ("Made Up Tag", "x"),  # unknown: dropped
                ("Experimentation", "a"),
                ("Audience Targeting", "b"),
                ("Lifecycle/CRM", "fourth: over the cap"),
            ],
            EXPERIENCE[1]: [("Lifecycle/CRM", "already applied: dropped")],
        }
    )
    report = suggest_tags(client=client)

    assert report["sentences"] == 2 and report["batches"] == 1
    assert report["suggestions"] == 3
    rows = {r["text"]: r for r in list_bank()}
    assert [s["tag_id"] for s in rows[EXPERIENCE[0]]["suggestions"]] == [
        bank["Predictive Modeling"], bank["Experimentation"], bank["Audience Targeting"],
    ]
    assert rows[EXPERIENCE[0]]["suggestions"][0]["reason"] == "builds a churn model"
    assert rows[EXPERIENCE[0]]["tag_ids"] == []  # nothing applied automatically
    assert rows[EXPERIENCE[1]]["suggestions"] == []
    assert suggestion_stats() == {"suggested": 3, "accepted": 0, "rejected": 0}
    assert total_tagger_cost() == pytest.approx(2000 / 1e6 + 300 * 5 / 1e6)


def test_a_sentence_is_only_asked_once(bank):
    suggest_tags(client=FakeClient({}))
    assert pending_sentences() == []
    second = FakeClient({})
    assert suggest_tags(client=second)["sentences"] == 0
    assert second.sent == []


def test_texts_limit_the_run_to_the_bullets_on_screen(bank):
    client = FakeClient({})
    suggest_tags([EXPERIENCE[1], EDUCATION], client=client)
    assert EXPERIENCE[1] in client.sent[0]
    assert EXPERIENCE[0] not in client.sent[0]
    assert pending_sentences() == [EXPERIENCE[0]]


def test_accept_applies_the_tag_and_reject_never_comes_back(bank):
    suggest_tags(client=FakeClient({EXPERIENCE[0]: [("Predictive Modeling", "r"), ("Experimentation", "r")]}))
    first, second = list_bank(["churn model"])[0]["suggestions"]

    assert decide(first["id"], accept=True)["status"] == "accepted"
    assert decide(second["id"], accept=False)["status"] == "rejected"
    assert decide(999, accept=True) is None

    row = list_bank(["churn model"])[0]
    assert row["tag_ids"] == [bank["Predictive Modeling"]]
    assert row["suggestions"] == []
    assert suggestion_stats() == {"suggested": 0, "accepted": 1, "rejected": 1}


def test_a_suggestion_for_a_tag_applied_by_hand_is_hidden(bank, monkeypatch):
    monkeypatch.setattr(tagger, "BATCH_SIZE", 1)
    suggest_tags(client=FakeClient({EXPERIENCE[0]: [("Predictive Modeling", "r")]}))
    set_sentence_tags(EXPERIENCE[0], [bank["Predictive Modeling"]])
    assert list_bank(["churn model"])[0]["suggestions"] == []


def test_a_name_returned_with_its_category_still_matches(bank):
    # The first live run lost all 27 picks to names the code could not match.
    suggest_tags(client=FakeClient({EXPERIENCE[1]: [('"Lifecycle/CRM (Marketing)"', "SMS win-back")]}))
    assert [s["tag_id"] for s in list_bank(["win-back"])[0]["suggestions"]] == [bank["Lifecycle/CRM"]]


def test_the_output_format_only_allows_real_tag_names():
    from pydantic import ValidationError

    from app.bullet_tagger_service import _output_format

    fmt = _output_format(["Lifecycle/CRM", "Predictive Modeling"])
    fmt.model_validate({"bullets": [{"index": 1, "tags": [{"tag": "Lifecycle/CRM", "reason": "r"}]}]})
    with pytest.raises(ValidationError):
        fmt.model_validate({"bullets": [{"index": 1, "tags": [{"tag": "Made Up", "reason": "r"}]}]})

