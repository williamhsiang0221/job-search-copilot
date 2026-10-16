"""Resume Assembler, phase 3: the agent loop.

A hand-rolled tool-use loop against the Messages API, on purpose, rather than
a framework's runner: every turn — call the model, read its tool_use blocks,
execute them, send back tool_result blocks — is visible here and logged to
assembly_turns as it happens, which is what the live tracer shows.

The harness is the referee, not the model:
- Swaps are validated in the tool handlers. The same-slot, one-for-one rule,
  the "only lines from loaded resumes" rule and the no-duplicate rule are
  enforced here and come back to the model as error tool_results — they are
  not left to the prompt. Swapped text is always copied from the database,
  never from the model's arguments.
- Stopping is decided here too. The run passes when all three scanners pass
  on the current draft; it ends as hit_cap when rounds, turns or cost run
  out; it ends as stopped if the model finishes without passing.

A round is one distinct draft sent to the two prompted scanners. Scanning an
unchanged draft again returns the cached verdict for free, and the hard gate
(code, $0) never starts a round on its own.
"""

from __future__ import annotations

import copy
import json
import random
import threading

from app import config
from app import prompts as _prompts
from app import scanners_service as scanners
from app.assembler_service import (
    AssemblerUnavailable,
    create_run,
    finish_run,
    get_run,
    log_turn,
    load_draft,
    ranked_candidates,
    update_run,
)
from app.db import session_scope
from app.evaluator import price
from app.models import Bullet, JobNormalized, Section
from app.resume_service import _render_job

FETCH_MORE_BATCH = 2
ROUND_SCANS = ("ats", "recruiter")

# Sent when a reply hits the output limit with no tool call. Without it the
# loop read the cut-off as the agent choosing to stop.
CUTOFF_NUDGE = (
    "Your last reply hit the output limit before you made a move. Keep your "
    "notes to a few lines and make your next tool call now."
)

TOOLS = [
    {
        "name": "view_draft",
        "description": "Show the current draft: every header and bullet with its reference and the resume it came from.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "swap_bullet",
        "description": (
            "Replace the bullet at `position` in section `slot` with a bullet from a loaded resume, "
            "identified by its id. The source bullet must be from the same slot. One for one."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "slot": {"type": "string", "description": "Section slot in the draft, e.g. fet_am."},
                "position": {"type": "integer", "description": "1-based bullet position in that section."},
                "source_bullet_id": {"type": "string", "description": "Id of the bullet to copy in."},
            },
            "required": ["slot", "position", "source_bullet_id"],
        },
    },
    {
        "name": "swap_header",
        "description": "Replace section `slot`'s role header with the same slot's header from another loaded resume.",
        "input_schema": {
            "type": "object",
            "properties": {
                "slot": {"type": "string"},
                "source_resume_id": {"type": "string"},
            },
            "required": ["slot", "source_resume_id"],
        },
    },
    {
        "name": "fetch_more_resumes",
        "description": "Load two more donor resumes, from the next most similar past roles.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "run_hard_gate_scan",
        "description": "Check every line is copied verbatim from a real source line in the same slot. Free.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "run_ats_scan",
        "description": "ATS screen: current draft vs. the anchor, criterion by criterion. Passes if the draft wins.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "run_recruiter_scan",
        "description": "Recruiter six-second skim: current draft vs. the anchor. Passes if the draft wins.",
        "input_schema": {"type": "object", "properties": {}},
    },
]


class _ToolError(Exception):
    """A rejected move — returned to the model as an error tool_result."""


def _client():
    import anthropic

    return anthropic.Anthropic()


def _job_snapshot(source: str, job_id: str):
    with session_scope() as session:
        job = session.get(JobNormalized, (source, job_id))
        if job is None:
            raise AssemblerUnavailable(f"{source}/{job_id} has not been normalized")
        return type(
            "_Job",
            (),
            {
                "company": job.company,
                "title": job.title,
                "responsibilities": list(job.responsibilities or []),
                "qualifications": list(job.qualifications or []),
                "role_summary": list(job.role_summary or []),
            },
        )()


def _render_with_sources(draft: dict) -> str:
    """The draft as the assembler sees it: references plus each line's source."""
    lines = [f"Headline: {draft.get('headline') or '(none)'}", ""]
    for section in draft["sections"]:
        slot = section["slot"]
        lines.append(f"## {scanners.SLOT_LABELS.get(slot, slot)}  (slot: {slot})")
        header = section.get("header")
        if header:
            lines.append(f"[{slot}.header] (from {header['source_resume_id']}) {header['text']}")
        for i, bullet in enumerate(section["bullets"], start=1):
            lines.append(f"[{slot}.{i}] (from {bullet['source_resume_id']}) {bullet['text']}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _render_donor(draft: dict, resume_id: str, label: str) -> str:
    lines = [f"### Donor resume {resume_id} — originally for {label}"]
    for section in draft["sections"]:
        slot = section["slot"]
        lines.append(f"## slot: {slot}")
        if section.get("header"):
            lines.append(f"header: {section['header']['text']}")
        for bullet in section["bullets"]:
            lines.append(f"- [{bullet['source_bullet_id']}] {bullet['text']}")
    return "\n".join(lines)


def _render_criteria(criteria: list[dict]) -> str:
    return "\n".join(
        f"{i}. [{'REQUIRED' if c['required'] else 'preferred'}] {c['criterion']}"
        for i, c in enumerate(criteria, start=1)
    )


def _with_cache_breakpoint(messages: list[dict]) -> list[dict]:
    """A copy of the conversation with a prompt-cache breakpoint on its last
    block. Every turn resends the whole conversation (tools, system prompt,
    posting, donor resumes, every earlier turn); the breakpoint lets the API
    bill the part it saw last turn at the cache-read rate. Moving it forward
    each turn means each call only pays full price for what is new.

    One breakpoint covers tools and system too, since they come first in the
    cached prefix. A copy, not the stored list, so earlier markers never
    accumulate past the API's limit of four.
    """
    marked = copy.deepcopy(messages)
    last = marked[-1]
    if isinstance(last["content"], str):
        last["content"] = [{"type": "text", "text": last["content"]}]
    last["content"][-1]["cache_control"] = {"type": "ephemeral"}
    return marked


class AssemblyLoop:
    def __init__(self, run_id: int, *, client=None, rng: random.Random | None = None):
        self.run_id = run_id
        self.client = client or _client()
        self.rng = rng
        run = get_run(run_id)
        if run is None:
            raise AssemblerUnavailable(f"no assembly run {run_id}")
        self.source, self.job_id = run["source"], run["job_id"]
        self.anchor_id = run["anchor_resume_id"]
        self.anchor = copy.deepcopy(run["draft"])
        self.draft = copy.deepcopy(run["draft"])
        self.pool = [self.anchor_id, *run["donor_resume_ids"]]
        self.labels = {
            c["resume_id"]: f"{c['company']} — {c['title']}"
            # Say why a category donor is here: it was not picked for being
            # similar to this posting.
            + (f" (your newest {c['reason'][len('latest '):]} resume)" if c.get("reason", "").startswith("latest ") else "")
            for c in [run["seed"]["anchor"], *run["seed"]["donors"]]
        }

        self.version = 0
        self.scanned_versions: set[int] = set()
        self.scans: dict[str, tuple[int, dict]] = {}
        self.turns = 0
        self.cost = 0.0
        self.criteria: list[dict] = []
        self.role_summary: list[str] = []

    # --- bookkeeping ------------------------------------------------------

    def _add_cost(self, cost: float | None) -> None:
        self.cost = round(self.cost + (cost or 0.0), 6)

    def _passed(self) -> bool:
        return all(
            kind in self.scans and self.scans[kind][0] == self.version and self.scans[kind][1]["passed"]
            for kind in ("hard_gate", *ROUND_SCANS)
        )

    def _round_spent_and_failed(self) -> bool:
        """Every round is used, and the latest scanned draft is fully judged
        and failing — nothing left that could still pass."""
        if len(self.scanned_versions) < config.ASSEMBLER_MAX_ROUNDS:
            return False
        latest = max(self.scanned_versions)
        judged = all(kind in self.scans and self.scans[kind][0] == latest for kind in ROUND_SCANS)
        return judged and not self._passed()

    def _commit_draft(self) -> None:
        self.version += 1
        update_run(self.run_id, draft=copy.deepcopy(self.draft))

    # --- tools ------------------------------------------------------------

    def _section(self, slot: str) -> dict:
        for section in self.draft["sections"]:
            if section["slot"] == slot:
                return section
        raise _ToolError(f"The draft has no '{slot}' section.")

    def _tool_view_draft(self, _args) -> dict:
        return {"draft": _render_with_sources(self.draft)}

    def _tool_swap_bullet(self, args) -> dict:
        slot, position, bullet_id = args["slot"], int(args["position"]), args["source_bullet_id"]
        section = self._section(slot)
        if not 1 <= position <= len(section["bullets"]):
            raise _ToolError(f"'{slot}' has {len(section['bullets'])} bullets; position {position} doesn't exist.")

        with session_scope() as session:
            bullet = session.get(Bullet, bullet_id)
            if bullet is None:
                raise _ToolError(f"No bullet with id {bullet_id}.")
            source_section = session.get(Section, bullet.section_id)
            resume_id, source_slot, text = source_section.resume_id, source_section.slot, bullet.text

        if resume_id not in self.pool:
            raise _ToolError(f"{bullet_id} is from a resume you haven't loaded.")
        if source_slot != slot:
            raise _ToolError(
                f"{bullet_id} is a '{source_slot}' bullet; a '{slot}' bullet can only be replaced from '{slot}'."
            )
        # By text as well as id: two resumes can store the identical sentence
        # under different ids (and different slots), which is still the same
        # bullet printed twice.
        for other in self.draft["sections"]:
            for i, existing in enumerate(other["bullets"], start=1):
                if other["slot"] == slot and i == position:
                    continue
                if existing["source_bullet_id"] == bullet_id or existing["text"] == text:
                    raise _ToolError(f"That bullet is already in the draft at [{other['slot']}.{i}].")

        old = section["bullets"][position - 1]
        if old["source_bullet_id"] == bullet_id:
            return {"ok": True, "note": "That bullet is already in this position; nothing changed."}
        section["bullets"][position - 1] = {"text": text, "source_resume_id": resume_id, "source_bullet_id": bullet_id}
        self._commit_draft()
        return {"ok": True, "replaced": old["text"], "now": text, "draft_version": self.version}

    def _tool_swap_header(self, args) -> dict:
        slot, resume_id = args["slot"], args["source_resume_id"]
        section = self._section(slot)
        if section.get("header") is None:
            raise _ToolError(f"'{slot}' has no role header to swap.")
        if resume_id not in self.pool:
            raise _ToolError(f"{resume_id} isn't a resume you've loaded.")
        with session_scope() as session:
            source = session.get(Section, f"{resume_id}/{slot}")
            header = source.header if source is not None else None
        if header is None:
            raise _ToolError(f"{resume_id} has no '{slot}' role header.")
        if section["header"]["text"] == header:
            return {"ok": True, "note": "Same header text already; nothing changed."}
        old = section["header"]["text"]
        section["header"] = {"text": header, "source_resume_id": resume_id}
        self._commit_draft()
        return {"ok": True, "replaced": old, "now": header, "draft_version": self.version}

    def _tool_fetch_more_resumes(self, _args) -> dict:
        fresh = [
            c for c in ranked_candidates(self.source, self.job_id)
            if c["resume_id"] is not None and c["resume_id"] not in self.pool
        ][:FETCH_MORE_BATCH]
        if not fresh:
            return {"ok": False, "note": "No more resumes on file for similar roles."}
        blocks = []
        with session_scope() as session:
            for candidate in fresh:
                self.pool.append(candidate["resume_id"])
                label = f"{candidate['company']} — {candidate['title']}"
                self.labels[candidate["resume_id"]] = label
                blocks.append(_render_donor(load_draft(session, candidate["resume_id"]), candidate["resume_id"], label))
        return {"ok": True, "loaded": [c["resume_id"] for c in fresh], "resumes": "\n\n".join(blocks)}

    def _scan(self, kind: str) -> tuple[dict, scanners.ScanResult | None]:
        cached = self.scans.get(kind)
        if cached and cached[0] == self.version:
            return {**cached[1], "note": "Cached: the draft hasn't changed since this scan."}, None

        if kind in ROUND_SCANS and self.version not in self.scanned_versions:
            if len(self.scanned_versions) >= config.ASSEMBLER_MAX_ROUNDS:
                raise _ToolError(f"Round budget spent ({config.ASSEMBLER_MAX_ROUNDS}); this draft can't be scanned.")
            self.scanned_versions.add(self.version)
            update_run(self.run_id, rounds_used=len(self.scanned_versions))

        if kind == "hard_gate":
            result = scanners.run_hard_gate_scan(self.draft)
        elif kind == "ats":
            result = scanners.run_ats_scan(self.criteria, self.anchor, self.draft, client=self.client, rng=self.rng)
        else:
            result = scanners.run_recruiter_scan(
                self.criteria, self.anchor, self.draft,
                role_summary=self.role_summary, client=self.client, rng=self.rng,
            )

        self.scans[kind] = (self.version, result.output)
        self._add_cost(result.cost_usd)
        update_run(
            self.run_id,
            verdicts={k: {"draft_version": v, **out} for k, (v, out) in self.scans.items()},
        )
        return {**result.output, "draft_version": self.version}, result

    def _execute(self, name: str, args: dict) -> tuple[dict, bool, scanners.ScanResult | None]:
        handlers = {
            "view_draft": self._tool_view_draft,
            "swap_bullet": self._tool_swap_bullet,
            "swap_header": self._tool_swap_header,
            "fetch_more_resumes": self._tool_fetch_more_resumes,
        }
        scans = {"run_hard_gate_scan": "hard_gate", "run_ats_scan": "ats", "run_recruiter_scan": "recruiter"}
        try:
            if name in scans:
                output, result = self._scan(scans[name])
                return output, False, result
            if name in handlers:
                return handlers[name](args or {}), False, None
            raise _ToolError(f"Unknown tool {name}.")
        except _ToolError as exc:
            return {"error": str(exc)}, True, None

    # --- the loop ---------------------------------------------------------

    def _opening_message(self) -> str:
        with session_scope() as session:
            donors = [
                _render_donor(load_draft(session, rid), rid, self.labels.get(rid, rid))
                for rid in self.pool[1:]
            ]
        return "\n\n".join(
            [
                "# The job posting",
                _render_job(_job_snapshot(self.source, self.job_id)),
                "# Screening criteria",
                _render_criteria(self.criteria),
                f"# The draft (a copy of the anchor, originally for {self.labels.get(self.anchor_id, self.anchor_id)})",
                _render_with_sources(self.draft),
                "# Donor resumes",
                "\n\n".join(donors) if donors else "(none yet — use fetch_more_resumes)",
            ]
        )

    def run(self) -> str:
        prompt_version = config.ASSEMBLER_PROMPT_VERSION
        update_run(
            self.run_id,
            status="running",
            prompt_versions={
                "assembler": prompt_version,
                **{kind: scanners.active_version(kind) for kind in scanners.SCANNER_KINDS},
            },
        )

        job = _job_snapshot(self.source, self.job_id)
        self.role_summary = job.role_summary
        criteria = scanners.build_ats_criteria(job, client=self.client)
        self.criteria = criteria.output["criteria"]
        self._add_cost(criteria.cost_usd)
        log_turn(
            self.run_id,
            kind="system",
            tool_name="ats_criteria",
            result=criteria.output,
            model=criteria.model,
            input_tokens=criteria.input_tokens,
            output_tokens=criteria.output_tokens,
            cost_usd=criteria.cost_usd,
        )

        system = (
            _prompts.load_prompt("assembler", prompt_version)
            .replace("{max_rounds}", str(config.ASSEMBLER_MAX_ROUNDS))
            .replace("{max_turns}", str(config.ASSEMBLER_MAX_TURNS))
        )
        messages: list[dict] = [{"role": "user", "content": self._opening_message()}]

        while True:
            if self.turns >= config.ASSEMBLER_MAX_TURNS:
                return self._finish("hit_cap", f"turn cap ({config.ASSEMBLER_MAX_TURNS}) reached")
            if self.cost >= config.ASSEMBLER_MAX_COST_USD:
                return self._finish("hit_cap", f"cost cap (${config.ASSEMBLER_MAX_COST_USD:.2f}) reached")

            response = self.client.messages.create(
                model=config.ASSEMBLER_MODEL,
                max_tokens=config.ASSEMBLER_MAX_TOKENS,
                system=system,
                tools=TOOLS,
                messages=_with_cache_breakpoint(messages),
                thinking={"type": "disabled"},
            )
            self.turns += 1
            usage = getattr(response, "usage", None)
            tout = getattr(usage, "output_tokens", None)
            uncached = getattr(usage, "input_tokens", None)
            cache_write = getattr(usage, "cache_creation_input_tokens", None) or 0
            cache_read = getattr(usage, "cache_read_input_tokens", None) or 0
            # Stored input is the whole prompt, cached or not, so turns stay
            # comparable with runs from before caching; the split is kept in
            # the turn's payload.
            tin = None if uncached is None else uncached + cache_write + cache_read
            cost = price(config.ASSEMBLER_MODEL, uncached, tout, cache_write, cache_read)
            self._add_cost(cost)

            content = []
            for block in response.content:
                if block.type == "text":
                    content.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    content.append({"type": "tool_use", "id": block.id, "name": block.name, "input": block.input})
            tool_uses = [b for b in content if b["type"] == "tool_use"]
            log_turn(
                self.run_id,
                kind="model",
                payload={
                    "text": "\n".join(b["text"] for b in content if b["type"] == "text"),
                    "tool_calls": [{"name": b["name"], "input": b["input"]} for b in tool_uses],
                    "stop_reason": getattr(response, "stop_reason", None),
                    "cache": {"write_tokens": cache_write, "read_tokens": cache_read},
                },
                model=config.ASSEMBLER_MODEL,
                input_tokens=tin,
                output_tokens=tout,
                cost_usd=cost,
            )
            update_run(self.run_id, turns_used=self.turns)
            # The API rejects an empty assistant turn; a cut-off reply always
            # carries text, but guard anyway.
            messages.append({"role": "assistant", "content": content or [{"type": "text", "text": "(no output)"}]})

            if not tool_uses and getattr(response, "stop_reason", None) == "max_tokens":
                # Cut off mid-analysis, not a decision to stop: say so and let
                # the loop continue. The turn and cost caps still bound it.
                log_turn(
                    self.run_id,
                    kind="system",
                    tool_name="cutoff",
                    result={"max_tokens": config.ASSEMBLER_MAX_TOKENS},
                )
                messages.append({"role": "user", "content": CUTOFF_NUDGE})
                continue

            if not tool_uses:
                return self._finish("passed" if self._passed() else "stopped", None)

            results = []
            for call in tool_uses:
                output, is_error, scan = self._execute(call["name"], call["input"])
                log_turn(
                    self.run_id,
                    kind="tool",
                    tool_name=call["name"],
                    payload=call["input"],
                    result=output,
                    model=scan.model if scan else None,
                    input_tokens=scan.input_tokens if scan else None,
                    output_tokens=scan.output_tokens if scan else None,
                    cost_usd=scan.cost_usd if scan else None,
                )
                results.append(
                    {"type": "tool_result", "tool_use_id": call["id"], "content": json.dumps(output), "is_error": is_error}
                )
            messages.append({"role": "user", "content": results})

            if self._passed():
                return self._finish("passed", None)
            if self._round_spent_and_failed():
                return self._finish("hit_cap", f"round cap ({config.ASSEMBLER_MAX_ROUNDS}) reached without passing")

    def _finish(self, status: str, reason: str | None) -> str:
        if reason:
            log_turn(self.run_id, kind="system", tool_name="stop", result={"status": status, "reason": reason})
        finish_run(self.run_id, status=status, error=None)
        return status


def run_assembly(run_id: int, *, client=None, rng: random.Random | None = None) -> str:
    """Run the loop to completion. Any unexpected failure ends the run as
    error, logged, rather than leaving it stuck at running."""
    try:
        return AssemblyLoop(run_id, client=client, rng=rng).run()
    except Exception as exc:
        log_turn(run_id, kind="system", tool_name="error", result={"error": f"{type(exc).__name__}: {exc}"})
        finish_run(run_id, status="error", error=f"{type(exc).__name__}: {exc}")
        return "error"


def start_assembly(source: str, job_id: str) -> int:
    """Seed a run synchronously (so a bad seed fails the request itself) and
    run the loop in a background thread — the tracer polls the trace."""
    run_id = create_run(source, job_id)
    threading.Thread(target=run_assembly, args=(run_id,), daemon=True).start()
    return run_id
