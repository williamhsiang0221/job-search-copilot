"""Resume Assembler scanners: rendering, the recruiter's slice, A/B handling,
and pass/fail being decided in code. The model is faked throughout."""

from types import SimpleNamespace

import pytest

from app.scanners_service import (
    SCANNER_KINDS,
    AtsCriteria,
    AtsCriterion,
    AtsVerdict,
    Coverage,
    RecruiterVerdict,
    available_versions,
    build_ats_criteria,
    load_prompt,
    recruiter_view,
    render_draft,
    run_ats_scan,
    run_hard_gate_scan,
    recruiter_positions,
    run_recruiter_scan,
)


class FakeClient:
    """Records each call and returns a canned parsed output."""

    def __init__(self, parsed):
        self.parsed = parsed
        self.calls = []
        self.messages = SimpleNamespace(parse=self._parse)

    def _parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(parsed_output=self.parsed, usage=SimpleNamespace(input_tokens=1000, output_tokens=100))


class ExplodingClient:
    messages = SimpleNamespace(parse=lambda **k: pytest.fail("the model should not have been called"))


class FixedRng:
    def __init__(self, value):
        self.value = value

    def random(self):
        return self.value


CANDIDATE_IS_A = FixedRng(0.1)
CANDIDATE_IS_B = FixedRng(0.9)


def _bullet(text, source="r1"):
    return {"text": text, "source_resume_id": source, "source_bullet_id": f"{source}/x"}


def _draft(fet_bullets=("am one", "am two", "am three"), headline="Growth PM"):
    return {
        "headline": headline,
        "sections": [
            {"slot": "lakeshore", "header": None, "bullets": [_bullet("MBA coursework")]},
            {"slot": "carewell", "header": {"text": "AI PM Intern", "source_resume_id": "r1"}, "bullets": [
                _bullet("inn one"), _bullet("inn two"), _bullet("inn three")]},
            {"slot": "bp_pm", "header": {"text": "Assistant Manager, 2022 - 2025", "source_resume_id": "r1"},
             "bullets": [_bullet(t) for t in fet_bullets]},
            {"slot": "northbeam", "header": {"text": "Analyst", "source_resume_id": "r1"}, "bullets": [_bullet("northbeam one")]},
        ],
    }


CRITERIA = [
    {"criterion": "Lifecycle marketing", "category": "domain", "required": True, "keywords": ["lifecycle"]},
    {"criterion": "SQL", "category": "tool", "required": False, "keywords": ["SQL"]},
]


def test_every_scanner_kind_has_a_v1_prompt():
    for kind in SCANNER_KINDS:
        assert "v1" in available_versions(kind)
        assert load_prompt(kind, "v1").strip()


def test_render_draft_labels_every_line_when_asked():
    text = render_draft(_draft(), refs=True)
    assert "Headline: Growth PM" in text
    assert "[bp_pm.header] Role: Assistant Manager, 2022 - 2025" in text
    assert "- [bp_pm.3] am three" in text
    # Employer context comes from code, identical for every version.
    assert "Brightpath Mobile — consumer fintech app" in text
    assert "[bp_pm" not in render_draft(_draft())


def test_recruiter_view_is_the_top_two_roles_and_two_bullets_each_skipping_education():
    view = recruiter_view(_draft())
    assert view["headline"] == "Growth PM"
    assert [s["slot"] for s in view["sections"]] == ["carewell", "bp_pm"]
    assert [b["text"] for b in view["sections"][0]["bullets"]] == ["inn one", "inn two"]


def test_recruiter_view_skips_a_leading_summary_paragraph():
    draft = _draft()
    draft["sections"].insert(0, {"slot": "summary", "header": None, "bullets": [_bullet("I am a PM")]})
    assert [s["slot"] for s in recruiter_view(draft)["sections"]] == ["carewell", "bp_pm"]


def test_identical_drafts_are_a_tie_without_a_model_call():
    for scan in (run_ats_scan, run_recruiter_scan):
        result = scan(CRITERIA, _draft(), _draft(), client=ExplodingClient())
        assert result.skipped is True
        assert result.output["winner"] == "tie"
        assert result.output["passed"] is False
        assert result.cost_usd == 0.0


@pytest.mark.parametrize(
    "rng, model_pick, expected_winner",
    [
        (CANDIDATE_IS_A, "A", "candidate"),
        (CANDIDATE_IS_A, "B", "anchor"),
        (CANDIDATE_IS_B, "A", "anchor"),
        (CANDIDATE_IS_B, "B", "candidate"),
        (CANDIDATE_IS_A, "tie", "tie"),
    ],
)
def test_pairwise_maps_a_and_b_back_to_anchor_and_candidate(rng, model_pick, expected_winner):
    client = FakeClient(RecruiterVerdict(winner=model_pick, reasons="because"))
    result = run_recruiter_scan(CRITERIA, _draft(), _draft(fet_bullets=("better",)), client=client, rng=rng)
    assert result.output["winner"] == expected_winner
    assert result.output["passed"] is (expected_winner == "candidate")


def test_the_model_is_never_told_which_version_is_the_anchor():
    client = FakeClient(RecruiterVerdict(winner="A", reasons="x"))
    run_recruiter_scan(CRITERIA, _draft(), _draft(fet_bullets=("better",)), client=client, rng=CANDIDATE_IS_A)
    user = client.calls[0]["messages"][0]["content"]
    assert "anchor" not in user.lower()
    assert "=== Resume A ===" in user and "=== Resume B ===" in user


def test_recruiter_scan_only_shows_the_slice():
    client = FakeClient(RecruiterVerdict(winner="A", reasons="x"))
    run_recruiter_scan(
        CRITERIA, _draft(), _draft(fet_bullets=("am one", "better two", "hidden three")), client=client, rng=CANDIDATE_IS_A
    )
    user = client.calls[0]["messages"][0]["content"]
    assert "better two" in user
    assert "hidden three" not in user
    assert "northbeam one" not in user
    assert "MBA coursework" not in user


def test_recruiter_scan_sees_the_role_summary_when_there_is_one():
    client = FakeClient(RecruiterVerdict(winner="A", reasons="x"))
    run_recruiter_scan(
        CRITERIA, _draft(), _draft(fet_bullets=("better",)),
        role_summary=["You will grow our consumer app's daily users."], client=client, rng=CANDIDATE_IS_A,
    )
    user = client.calls[0]["messages"][0]["content"]
    assert user.startswith("About the role (the posting's own words):\n- You will grow our consumer app's daily users.")

    client = FakeClient(RecruiterVerdict(winner="A", reasons="x"))
    run_recruiter_scan(CRITERIA, _draft(), _draft(fet_bullets=("better",)), client=client, rng=CANDIDATE_IS_A)
    assert "About the role" not in client.calls[0]["messages"][0]["content"]


def test_ats_criteria_are_built_with_the_role_summary():
    client = FakeClient(AtsCriteria(criteria=[]))
    job = SimpleNamespace(
        company="Acme", title="Growth PM", responsibilities=["Own growth"], qualifications=["SQL"],
        role_summary=["The Growth team owns activation for our B2B platform."],
    )
    build_ats_criteria(job, client=client)
    assert "The Growth team owns activation for our B2B platform." in client.calls[0]["messages"][0]["content"]


def test_ats_coverage_is_remapped_to_candidate_and_anchor():
    client = FakeClient(
        AtsVerdict(coverage=[Coverage(a=True, b=False), Coverage(a=False, b=True)], winner="A", reasons="x")
    )
    result = run_ats_scan(CRITERIA, _draft(), _draft(fet_bullets=("better",)), client=client, rng=CANDIDATE_IS_B)
    # Candidate was B here, so the model's "b" column is the candidate's.
    assert result.output["coverage"] == [
        {"criterion": "Lifecycle marketing", "required": True, "candidate": False, "anchor": True},
        {"criterion": "SQL", "required": False, "candidate": True, "anchor": False},
    ]
    assert result.output["winner"] == "anchor"
    assert result.output["labels"] == {"A": "anchor", "B": "candidate"}


def test_build_ats_criteria_uses_its_prompt_and_records_cost():
    job = SimpleNamespace(company="Acme", title="Growth PM", responsibilities=["own lifecycle"], qualifications=["SQL"])
    client = FakeClient(
        AtsCriteria(criteria=[AtsCriterion(criterion="SQL", category="tool", required=True, keywords=["SQL"])])
    )
    result = build_ats_criteria(job, client=client, model="claude-haiku-4-5")

    assert result.output["criteria"][0]["criterion"] == "SQL"
    assert client.calls[0]["system"] == load_prompt("ats_criteria", "v1")
    assert "own lifecycle" in client.calls[0]["messages"][0]["content"]
    assert result.prompt_version == "v1"
    assert result.cost_usd == pytest.approx((1000 * 1.0 + 100 * 5.0) / 1_000_000)


# --- hard gate: nothing invented, nothing moved across sections -------------

from app import db
from app.models import Bullet, Resume, Section


@pytest.fixture
def stored(tmp_path):
    """Two stored resumes to draw lines from."""
    db.reset_for_tests(tmp_path / "test.db")
    with db.session_scope() as session:
        for rid, word in (("r1", "anchor"), ("r2", "donor")):
            session.add(Resume(id=rid, filename=f"{rid}.pdf", headline="H"))
            for slot, header in (("bp_pm", f"{word} AM header"), ("bp_sa", f"{word} SDA header")):
                section_id = f"{rid}/{slot}"
                session.add(Section(id=section_id, resume_id=rid, slot=slot, header=header))
                session.add(Bullet(id=f"{section_id}/1", section_id=section_id, position=1, text=f"{word} {slot} one"))
    yield
    db.reset_for_tests(tmp_path / "unused.db")


def _line(text, resume_id, bullet_id):
    return {"text": text, "source_resume_id": resume_id, "source_bullet_id": bullet_id}


def _assembled(am_bullet, am_header=None):
    return {
        "headline": "H",
        "sections": [
            {
                "slot": "bp_pm",
                "header": am_header or {"text": "anchor AM header", "source_resume_id": "r1"},
                "bullets": [am_bullet],
            }
        ],
    }


def test_hard_gate_passes_lines_taken_verbatim_from_the_same_slot(stored):
    draft = _assembled(
        _line("donor bp_pm one", "r2", "r2/bp_pm/1"),
        am_header={"text": "donor AM header", "source_resume_id": "r2"},
    )
    result = run_hard_gate_scan(draft)
    assert result.output == {"passed": True, "defects": []}
    assert result.cost_usd == 0.0


@pytest.mark.parametrize(
    "bullet, kind",
    [
        (_line("donor bp_pm one, now with invented metrics", "r2", "r2/bp_pm/1"), "altered"),
        (_line("donor bp_pm one", "r2", "r2/bp_pm/99"), "unknown_origin"),
        (_line("donor bp_sa one", "r2", "r2/bp_sa/1"), "wrong_section"),
    ],
)
def test_hard_gate_flags_invented_or_moved_bullets(stored, bullet, kind):
    result = run_hard_gate_scan(_assembled(bullet))
    assert result.output["passed"] is False
    assert [(d["kind"], d["refs"]) for d in result.output["defects"]] == [(kind, ["bp_pm.1"])]


def test_hard_gate_flags_an_altered_header(stored):
    draft = _assembled(
        _line("anchor bp_pm one", "r1", "r1/bp_pm/1"),
        am_header={"text": "Senior Director, invented", "source_resume_id": "r1"},
    )
    result = run_hard_gate_scan(draft)
    assert [(d["kind"], d["refs"]) for d in result.output["defects"]] == [("altered", ["bp_pm.header"])]


def test_recruiter_positions_are_the_swappable_lines_it_reads():
    # Education and the third bullet onward are outside the skim.
    assert recruiter_positions(_draft()) == [
        "carewell.header", "carewell.1", "carewell.2",
        "bp_pm.header", "bp_pm.1", "bp_pm.2",
    ]


def test_an_identical_recruiter_tie_names_the_positions_to_swap_into():
    # Only the third FET bullet differs — below what the recruiter reads.
    result = run_recruiter_scan(
        CRITERIA, _draft(), _draft(fet_bullets=("am one", "am two", "swapped three")), client=ExplodingClient()
    )
    assert result.output["winner"] == "tie"
    assert result.output["reads"] == recruiter_positions(_draft())
    assert "cannot change until you swap into one of: carewell.header, carewell.1" in result.output["reasons"]


def test_a_judged_recruiter_scan_also_lists_what_it_read():
    client = FakeClient(RecruiterVerdict(winner="A", reasons="B leads weaker."))
    result = run_recruiter_scan(
        CRITERIA, _draft(), _draft(fet_bullets=("better", "am two")), client=client, rng=CANDIDATE_IS_A
    )
    assert result.output["reads"] == recruiter_positions(_draft())
    assert result.output["reasons"] == "B leads weaker."
