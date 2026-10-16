"""Resume Assembler, phase 1: seeding, the working-copy draft, and the trace log."""

import pytest

import app.assembler_service as assembler_service
from app import db
from app.assembler_service import (
    AssemblerUnavailable,
    create_run,
    finish_run,
    get_run,
    list_runs,
    load_draft,
    log_turn,
    seed,
    total_assembler_cost,
)
from app.models import Application, Bullet, Job, Resume, Section


@pytest.fixture
def fresh_db(tmp_path):
    db.reset_for_tests(tmp_path / "test.db")
    yield
    db.reset_for_tests(tmp_path / "unused.db")


def _application(company: str) -> int:
    with db.session_scope() as session:
        app = Application(company=company, title="PM")
        session.add(app)
        session.flush()
        return app.id


def _resume(resume_id: str, application_id: int | None, sections: dict[str, tuple[str | None, list[str]]]) -> None:
    with db.session_scope() as session:
        session.add(Resume(id=resume_id, filename=f"{resume_id}.pdf", application_id=application_id, headline="H"))
        for slot, (header, bullets) in sections.items():
            section_id = f"{resume_id}/{slot}"
            session.add(Section(id=section_id, resume_id=resume_id, slot=slot, header=header))
            for position, text in enumerate(bullets, start=1):
                session.add(Bullet(id=f"{section_id}/{position}", section_id=section_id, position=position, text=text))


def _ranking(monkeypatch, application_ids: list[int]) -> None:
    """Fake the overall similarity ranking, highest first."""
    overall = [
        {"application_id": a, "company": f"Co{a}", "title": "PM", "score": 3.0 - i * 0.5}
        for i, a in enumerate(application_ids)
    ]
    monkeypatch.setattr(assembler_service, "find_similar_applications", lambda *a, **k: {"overall": overall})


def test_seed_skips_roles_without_a_resume_and_takes_the_next_highest(fresh_db, monkeypatch):
    no_resume = _application("A")
    first = _application("B")
    second = _application("C")
    third = _application("D")
    fourth = _application("E")
    for app_id, rid in [(first, "r1"), (second, "r2"), (third, "r3"), (fourth, "r4")]:
        _resume(rid, app_id, {"northbeam": ("Analyst", ["x"])})
    _ranking(monkeypatch, [no_resume, first, second, third, fourth])

    picked = seed("linkedin", "job")

    assert picked["anchor"]["resume_id"] == "r1"
    assert [d["resume_id"] for d in picked["donors"]] == ["r2", "r3"]
    # The skipped role is recorded, and the walk stops once the seed is full.
    assert [c["resume_id"] for c in picked["ranked"]] == [None, "r1", "r2", "r3"]


def test_seed_with_fewer_than_three_resumes_returns_what_exists(fresh_db, monkeypatch):
    only = _application("A")
    _resume("r1", only, {"northbeam": ("Analyst", ["x"])})
    _ranking(monkeypatch, [_application("B"), only])

    picked = seed("linkedin", "job")

    assert picked["anchor"]["resume_id"] == "r1"
    assert picked["donors"] == []


def test_seed_raises_when_no_similar_role_has_a_resume(fresh_db, monkeypatch):
    _ranking(monkeypatch, [_application("A")])
    with pytest.raises(AssemblerUnavailable):
        seed("linkedin", "job")


def test_seed_raises_when_there_is_no_ranking_at_all(fresh_db, monkeypatch):
    _ranking(monkeypatch, [])
    with pytest.raises(AssemblerUnavailable):
        seed("linkedin", "job")


def test_load_draft_orders_sections_and_tags_every_line_with_its_source(fresh_db):
    _resume(
        "r1",
        None,
        {
            "lakeshore": (None, ["edu bullet"]),
            "bp_pm": ("Assistant Manager, 2022 - 2025", ["b1", "b2"]),
        },
    )
    with db.session_scope() as session:
        draft = load_draft(session, "r1")

    assert draft["headline"] == "H"
    assert [s["slot"] for s in draft["sections"]] == ["bp_pm", "lakeshore"]
    fet = draft["sections"][0]
    assert fet["header"] == {"text": "Assistant Manager, 2022 - 2025", "source_resume_id": "r1"}
    assert fet["bullets"][1] == {"text": "b2", "source_resume_id": "r1", "source_bullet_id": "r1/bp_pm/2"}
    assert draft["sections"][1]["header"] is None


def test_create_run_copies_the_anchor_without_touching_it(fresh_db, monkeypatch):
    with db.session_scope() as session:
        session.add(Job(source="linkedin", job_id="job", title="Growth PM", company="Acme"))
    anchor_app = _application("B")
    donor_app = _application("C")
    _resume("r1", anchor_app, {"northbeam": ("Analyst", ["anchor bullet"])})
    _resume("r2", donor_app, {"northbeam": ("Analyst", ["donor bullet"])})
    _ranking(monkeypatch, [anchor_app, donor_app])

    run_id = create_run("linkedin", "job")
    run = get_run(run_id)

    assert run["status"] == "seeded"
    assert run["company"] == "Acme"
    assert run["anchor_resume_id"] == "r1"
    assert run["donor_resume_ids"] == ["r2"]
    assert run["draft"]["sections"][0]["bullets"][0]["text"] == "anchor bullet"
    # The seed is the first entry in the trace.
    assert [(t["kind"], t["tool_name"]) for t in run["turns"]] == [("system", "seed")]

    # Editing the draft never reaches the live resume tables.
    with db.session_scope() as session:
        assert session.get(Bullet, "r1/northbeam/1").text == "anchor bullet"


def test_log_turn_appends_in_order_and_rolls_up_cost(fresh_db, monkeypatch):
    with db.session_scope() as session:
        session.add(Job(source="linkedin", job_id="job", title="PM", company="Acme"))
    anchor_app = _application("B")
    _resume("r1", anchor_app, {"northbeam": ("Analyst", ["x"])})
    _ranking(monkeypatch, [anchor_app])
    run_id = create_run("linkedin", "job")

    log_turn(run_id, kind="model", model="m", input_tokens=100, output_tokens=20, cost_usd=0.01)
    log_turn(run_id, kind="tool", tool_name="view_draft", payload={}, result={"ok": True})
    log_turn(run_id, kind="model", model="m", input_tokens=50, output_tokens=5, cost_usd=0.002)
    finish_run(run_id, status="passed")

    run = get_run(run_id)
    assert [t["seq"] for t in run["turns"]] == [1, 2, 3, 4]
    assert run["input_tokens"] == 150
    assert run["output_tokens"] == 25
    assert run["cost_usd"] == pytest.approx(0.012)
    assert run["status"] == "passed"
    assert run["finished_at"] is not None
    assert total_assembler_cost() == pytest.approx(0.012)


def test_list_runs_is_newest_first_and_excludes_turns(fresh_db, monkeypatch):
    with db.session_scope() as session:
        session.add(Job(source="linkedin", job_id="job", title="PM", company="Acme"))
    anchor_app = _application("B")
    _resume("r1", anchor_app, {"northbeam": ("Analyst", ["x"])})
    _ranking(monkeypatch, [anchor_app])
    first = create_run("linkedin", "job")
    second = create_run("linkedin", "job")

    runs = list_runs()
    assert [r["id"] for r in runs] == [second, first]
    assert "turns" not in runs[0]


def test_get_run_returns_none_for_unknown_id(fresh_db):
    assert get_run(999) is None


def _role_application(company: str, role: str) -> int:
    with db.session_scope() as session:
        app = Application(company=company, title=f"{role} role", role=role)
        session.add(app)
        session.flush()
        return app.id


def _dated_resume(resume_id: str, application_id: int, day: int) -> None:
    from datetime import date

    _resume(resume_id, application_id, {"northbeam": ("Analyst", ["x"])})
    with db.session_scope() as session:
        session.get(Resume, resume_id).resume_date = date(2026, 9, day)


def test_seed_adds_each_categorys_newest_resume_as_a_donor(fresh_db, monkeypatch):
    pm_old = _role_application("PmOld", "Product Manager")
    pm_new = _role_application("PmNew", "Product Manager")
    mkt = _role_application("Mkt", "Marketing")
    strat = _role_application("Strat", "Strategy")
    _dated_resume("pm_old", pm_old, 1)
    _dated_resume("pm_new", pm_new, 20)
    _dated_resume("mkt", mkt, 10)
    _dated_resume("strat", strat, 5)
    # Similarity picks pm_old (anchor), mkt, strat. Marketing's and Strategy's
    # newest are already in; Product Manager's newest (pm_new) is not.
    _ranking(monkeypatch, [pm_old, mkt, strat, pm_new])

    picked = seed("linkedin", "job")

    assert picked["anchor"]["resume_id"] == "pm_old"
    assert [(d["resume_id"], d["reason"]) for d in picked["donors"]] == [
        ("mkt", "similar"),
        ("strat", "similar"),
        ("pm_new", "latest Product Manager"),
    ]
    # Ranked further down, so it carries its similarity score along.
    assert picked["donors"][2]["score"] is not None


def test_a_category_donor_outside_the_ranking_has_no_score(fresh_db, monkeypatch):
    pm = _role_application("Pm", "Product Manager")
    analyst = _role_application("Analyst", "Data Analyst")
    _dated_resume("pm", pm, 1)
    _dated_resume("analyst", analyst, 2)
    _ranking(monkeypatch, [pm])

    picked = seed("linkedin", "job")

    assert [(d["resume_id"], d["score"], d["reason"]) for d in picked["donors"]] == [
        ("analyst", None, "latest Data Analyst"),
    ]
