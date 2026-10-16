"""Resume Assembler, phase 3: the tool loop, driven by a scripted fake model.

Checks the harness, not the model: that illegal moves are rejected as
tool_results, that text is copied from the database, and that every stop
rule (passed, stopped, round/turn/cost caps, error) ends the run properly.
"""

import itertools
from types import SimpleNamespace

import pytest

import app.assembler_service as assembler_service
from app import config, db
from app.assembler_agent import run_assembly
from app.assembler_service import create_run, get_run
from app.models import Application, Bullet, Job, JobNormalized, Resume, Section
from app.scanners_service import AtsCriteria, AtsCriterion, AtsVerdict, Coverage, RecruiterVerdict


class FixedRng:
    """Candidate always goes in as "A"."""

    def random(self):
        return 0.1


def _tool(name, **inp):
    return SimpleNamespace(type="tool_use", id=f"t{next(_ids)}", name=name, input=inp)


_ids = itertools.count()


def _text(text):
    return SimpleNamespace(type="text", text=text)


class ScriptedClient:
    """messages.create replays scripted assistant turns; messages.parse
    answers the scanners. scanner_pick is what the judge says ("A" = the
    candidate draft, given FixedRng)."""

    def __init__(self, turns, scanner_pick="A"):
        self.turns = list(turns)
        self.scanner_pick = scanner_pick
        self.create_calls = []
        self.parse_calls = []
        self.messages = SimpleNamespace(create=self._create, parse=self._parse)

    def _create(self, **kwargs):
        # Snapshot: the loop keeps appending to the same list after this call.
        self.create_calls.append({**kwargs, "messages": list(kwargs["messages"])})
        content = self.turns.pop(0) if self.turns else [_text("done")]
        stop = "tool_use" if any(b.type == "tool_use" for b in content) else "end_turn"
        return SimpleNamespace(content=content, stop_reason=stop, usage=SimpleNamespace(input_tokens=1000, output_tokens=100))

    def _parse(self, **kwargs):
        self.parse_calls.append(kwargs)
        fmt = kwargs["output_format"]
        if fmt is AtsCriteria:
            parsed = AtsCriteria(criteria=[AtsCriterion(criterion="SQL", category="tool", required=True, keywords=["SQL"])])
        elif fmt is AtsVerdict:
            parsed = AtsVerdict(coverage=[Coverage(a=True, b=False)], winner=self.scanner_pick, reasons="r")
        else:
            parsed = RecruiterVerdict(winner=self.scanner_pick, reasons="r")
        return SimpleNamespace(parsed_output=parsed, usage=SimpleNamespace(input_tokens=500, output_tokens=50))


@pytest.fixture
def run_id(tmp_path, monkeypatch):
    """A seeded run: anchor r1 and donor r2, each with bp_pm (2 bullets) and northbeam (1)."""
    db.reset_for_tests(tmp_path / "test.db")
    with db.session_scope() as session:
        session.add(Job(source="linkedin", job_id="job", title="Growth PM", company="Acme"))
        session.add(
            JobNormalized(source="linkedin", job_id="job", title="Growth PM", company="Acme",
                          responsibilities=["own growth"], qualifications=["SQL"])
        )
        app_ids = []
        for company in ("A", "B", "C"):
            application = Application(company=company, title="PM")
            session.add(application)
            session.flush()
            app_ids.append(application.id)
        for rid, app_id in (("r1", app_ids[0]), ("r2", app_ids[1]), ("r3", app_ids[2])):
            session.add(Resume(id=rid, filename=f"{rid}.pdf", application_id=app_id, headline=f"{rid} headline"))
            for slot, count in (("bp_pm", 2), ("northbeam", 1)):
                section_id = f"{rid}/{slot}"
                session.add(Section(id=section_id, resume_id=rid, slot=slot, header=f"{rid} {slot} header"))
                for pos in range(1, count + 1):
                    session.add(Bullet(id=f"{section_id}/{pos}", section_id=section_id, position=pos,
                                       text=f"{rid} {slot} bullet {pos}"))

    overall = [{"application_id": a, "company": c, "title": "PM", "score": 3.0 - i}
               for i, (a, c) in enumerate(zip(app_ids, ("A", "B", "C")))]
    monkeypatch.setattr(assembler_service, "find_similar_applications", lambda *a, **k: {"overall": overall})
    # Seed: r1 anchor, r2 donor; r3 is only reachable through fetch_more_resumes.
    monkeypatch.setattr(assembler_service, "SEED_SIZE", 2)
    rid = create_run("linkedin", "job")
    yield rid
    db.reset_for_tests(tmp_path / "unused.db")


def _tool_turns(run):
    return [t for t in run["turns"] if t["kind"] == "tool"]


SCAN_ALL = [_tool("run_hard_gate_scan"), _tool("run_ats_scan"), _tool("run_recruiter_scan")]


def test_a_good_swap_that_wins_every_scan_passes(run_id):
    client = ScriptedClient([[_tool("swap_bullet", slot="bp_pm", position=1, source_bullet_id="r2/bp_pm/1"), *SCAN_ALL]])

    assert run_assembly(run_id, client=client, rng=FixedRng()) == "passed"

    run = get_run(run_id)
    assert run["status"] == "passed"
    assert run["rounds_used"] == 1
    swapped = run["draft"]["sections"][0]["bullets"][0]
    assert swapped == {"text": "r2 bp_pm bullet 1", "source_resume_id": "r2", "source_bullet_id": "r2/bp_pm/1"}
    assert {k: v["passed"] for k, v in run["verdicts"].items()} == {"hard_gate": True, "ats": True, "recruiter": True}
    # Criteria + 1 model turn + 2 scanner calls, all costed and rolled up.
    assert run["cost_usd"] > 0
    assert run["prompt_versions"]["assembler"] == "v1"
    # The live resume tables are never touched.
    with db.session_scope() as session:
        assert session.get(Bullet, "r1/bp_pm/1").text == "r1 bp_pm bullet 1"


def test_illegal_moves_come_back_as_errors_and_change_nothing(run_id):
    client = ScriptedClient(
        [[
            _tool("swap_bullet", slot="bp_pm", position=1, source_bullet_id="r2/northbeam/1"),   # wrong slot
            _tool("swap_bullet", slot="bp_pm", position=1, source_bullet_id="r3/bp_pm/1"),  # not loaded
            _tool("swap_bullet", slot="bp_pm", position=2, source_bullet_id="r1/bp_pm/1"),  # duplicate
            _tool("swap_bullet", slot="bp_pm", position=9, source_bullet_id="r2/bp_pm/1"),  # no position
            _tool("swap_bullet", slot="lakeshore", position=1, source_bullet_id="r2/bp_pm/1"),    # no section
        ]]
    )
    assert run_assembly(run_id, client=client, rng=FixedRng()) == "stopped"

    run = get_run(run_id)
    errors = [t["result"]["error"] for t in _tool_turns(run)]
    assert len(errors) == 5
    assert "can only be replaced from 'bp_pm'" in errors[0]
    assert "haven't loaded" in errors[1]
    assert "already in the draft" in errors[2]
    assert "doesn't exist" in errors[3]
    assert "no 'lakeshore' section" in errors[4]
    assert [b["source_bullet_id"] for b in run["draft"]["sections"][0]["bullets"]] == ["r1/bp_pm/1", "r1/bp_pm/2"]
    # And the model was told they failed.
    results = client.create_calls[1]["messages"][-1]["content"]
    assert all(r["is_error"] for r in results)


def test_identical_text_under_a_different_id_counts_as_a_duplicate(run_id):
    # r2's northbeam bullet carries the exact text of r1's bp_pm bullet 2 —
    # different id, different slot, same sentence.
    with db.session_scope() as session:
        session.add(Section(id="r2/bp_sa", resume_id="r2", slot="bp_sa", header="h"))
        session.get(Bullet, "r2/bp_pm/1").text = "r1 bp_pm bullet 2"
    client = ScriptedClient([[_tool("swap_bullet", slot="bp_pm", position=1, source_bullet_id="r2/bp_pm/1")]])
    run_assembly(run_id, client=client, rng=FixedRng())
    error = _tool_turns(get_run(run_id))[0]["result"]["error"]
    assert "already in the draft at [bp_pm.2]" in error


def test_fetch_more_resumes_unlocks_the_next_similar_role(run_id):
    client = ScriptedClient(
        [
            [_tool("fetch_more_resumes")],
            [_tool("swap_bullet", slot="northbeam", position=1, source_bullet_id="r3/northbeam/1")],
        ]
    )
    run_assembly(run_id, client=client, rng=FixedRng())

    run = get_run(run_id)
    fetched = _tool_turns(run)[0]["result"]
    assert fetched["loaded"] == ["r3"]
    assert "[r3/northbeam/1] r3 northbeam bullet 1" in fetched["resumes"]
    assert run["draft"]["sections"][1]["bullets"][0]["source_resume_id"] == "r3"


def test_swap_header_copies_the_donor_header_for_the_same_slot(run_id):
    client = ScriptedClient([[_tool("swap_header", slot="bp_pm", source_resume_id="r2")]])
    run_assembly(run_id, client=client, rng=FixedRng())
    header = get_run(run_id)["draft"]["sections"][0]["header"]
    assert header == {"text": "r2 bp_pm header", "source_resume_id": "r2"}


def test_losing_every_round_ends_at_the_round_cap(run_id, monkeypatch):
    monkeypatch.setattr(config, "ASSEMBLER_MAX_ROUNDS", 1)
    client = ScriptedClient(
        [[_tool("swap_bullet", slot="bp_pm", position=1, source_bullet_id="r2/bp_pm/1"), *SCAN_ALL]],
        scanner_pick="B",  # the anchor wins
    )
    assert run_assembly(run_id, client=client, rng=FixedRng()) == "hit_cap"
    run = get_run(run_id)
    assert run["verdicts"]["ats"]["winner"] == "anchor"
    assert run["turns"][-1]["result"]["reason"].startswith("round cap")


def test_rescanning_an_unchanged_draft_is_free_and_uses_no_round(run_id):
    client = ScriptedClient(
        [
            [_tool("swap_bullet", slot="bp_pm", position=1, source_bullet_id="r2/bp_pm/1"), _tool("run_ats_scan")],
            [_tool("run_ats_scan")],
        ],
        scanner_pick="B",
    )
    run_assembly(run_id, client=client, rng=FixedRng())
    run = get_run(run_id)
    ats_turns = [t for t in _tool_turns(run) if t["tool_name"] == "run_ats_scan"]
    assert "Cached" in ats_turns[1]["result"]["note"]
    assert ats_turns[1]["cost_usd"] is None
    assert run["rounds_used"] == 1
    # One criteria call + one ATS call; the rescan never reached the model.
    assert len(client.parse_calls) == 2


def test_turn_cap_stops_a_model_that_never_scans(run_id, monkeypatch):
    monkeypatch.setattr(config, "ASSEMBLER_MAX_TURNS", 2)
    client = ScriptedClient([[_tool("view_draft")]] * 5)
    assert run_assembly(run_id, client=client, rng=FixedRng()) == "hit_cap"
    assert len(client.create_calls) == 2


def test_cost_cap_stops_before_the_next_model_call(run_id, monkeypatch):
    monkeypatch.setattr(config, "ASSEMBLER_MAX_COST_USD", 0.001)
    client = ScriptedClient([[_tool("view_draft")]] * 5)
    assert run_assembly(run_id, client=client, rng=FixedRng()) == "hit_cap"
    assert len(client.create_calls) == 1
    assert "cost cap" in get_run(run_id)["turns"][-1]["result"]["reason"]


def test_an_unexpected_failure_ends_the_run_as_error_not_stuck_running(run_id):
    class Broken(ScriptedClient):
        def _create(self, **kwargs):
            raise RuntimeError("boom")

    assert run_assembly(run_id, client=Broken([]), rng=FixedRng()) == "error"
    run = get_run(run_id)
    assert run["status"] == "error"
    assert "boom" in run["error"]
    assert run["finished_at"] is not None


def test_every_step_is_logged_in_order(run_id):
    client = ScriptedClient([[_tool("view_draft")], [_text("No better lines available.")]])
    run_assembly(run_id, client=client, rng=FixedRng())
    steps = [(t["kind"], t["tool_name"]) for t in get_run(run_id)["turns"]]
    assert steps == [
        ("system", "seed"),
        ("system", "ats_criteria"),
        ("model", None),
        ("tool", "view_draft"),
        ("model", None),
    ]


def _cache_markers(messages):
    return [
        (i, j)
        for i, message in enumerate(messages)
        if isinstance(message["content"], list)
        for j, block in enumerate(message["content"])
        if "cache_control" in block
    ]


def test_each_call_carries_one_cache_breakpoint_on_its_last_block(run_id):
    client = ScriptedClient([[_tool("view_draft")], [_tool("view_draft")], [_text("done")]])
    run_assembly(run_id, client=client, rng=FixedRng())

    assert len(client.create_calls) == 3
    for call in client.create_calls:
        messages = call["messages"]
        assert _cache_markers(messages) == [(len(messages) - 1, len(messages[-1]["content"]) - 1)]
    # The opening message was a plain string; the marked copy wraps it, and
    # the conversation the loop keeps never gains markers of its own.
    assert client.create_calls[0]["messages"][0]["content"][0]["type"] == "text"
    assert _cache_markers(client.create_calls[2]["messages"][:-1]) == []


def test_cached_tokens_count_toward_cost_and_are_recorded(run_id, monkeypatch):
    monkeypatch.setattr(config, "ASSEMBLER_MODEL", "claude-haiku-4-5")

    class Cached(ScriptedClient):
        def _create(self, **kwargs):
            response = super()._create(**kwargs)
            response.usage = SimpleNamespace(
                input_tokens=200, output_tokens=100,
                cache_creation_input_tokens=300, cache_read_input_tokens=7000,
            )
            return response

    run_assembly(run_id, client=Cached([[_text("done")]]), rng=FixedRng())

    model_turn = next(t for t in get_run(run_id)["turns"] if t["kind"] == "model")
    assert model_turn["input_tokens"] == 7500  # whole prompt, cached or not
    assert model_turn["payload"]["cache"] == {"write_tokens": 300, "read_tokens": 7000}
    # Haiku: 200 + 300*1.25 + 7000*0.1 = 1,275 input-equivalent, + 100 out at $5.
    expected = (200 + 375 + 700) / 1e6 * 1.0 + 100 / 1e6 * 5.0
    assert model_turn["cost_usd"] == pytest.approx(expected)


def test_a_cut_off_reply_is_nudged_not_treated_as_stopping(run_id):
    class CutOffFirst(ScriptedClient):
        def _create(self, **kwargs):
            response = super()._create(**kwargs)
            if len(self.create_calls) == 1:
                response.stop_reason = "max_tokens"
            return response

    client = CutOffFirst(
        [
            [_text("Comparing every bullet in detail, starting with")],
            [_tool("swap_bullet", slot="bp_pm", position=1, source_bullet_id="r2/bp_pm/1"), *SCAN_ALL],
        ]
    )

    assert run_assembly(run_id, client=client, rng=FixedRng()) == "passed"
    assert len(client.create_calls) == 2
    nudge = client.create_calls[1]["messages"][-1]
    assert nudge["role"] == "user" and "output limit" in nudge["content"][-1]["text"]
    assert ("system", "cutoff") in [(t["kind"], t["tool_name"]) for t in get_run(run_id)["turns"]]


def test_a_finished_reply_without_a_tool_call_still_stops(run_id):
    client = ScriptedClient([[_text("I am done.")]])
    assert run_assembly(run_id, client=client, rng=FixedRng()) == "stopped"
    assert len(client.create_calls) == 1
