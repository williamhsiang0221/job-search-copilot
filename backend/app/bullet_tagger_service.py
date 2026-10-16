"""Bullet Bank tag suggestions: the model proposes, the user decides.

Only professional-experience bullets are sent — the sections the profile's
resume layout marks as experience. Summary, education and Additional lines
never are (the user's rule), and headlines and role titles are not bullets
at all.

A suggestion is never applied on its own. It waits as "suggested" until the
user accepts it (the tag is applied) or rejects it (never proposed again for
that sentence). The accepted / rejected split is the measure of how far the
suggester agrees with the user — the same reasoning as calibrating any
judge against a human before trusting it.
"""

from __future__ import annotations

import re
from typing import Callable, Literal

from pydantic import BaseModel, Field, create_model
from sqlalchemy import func, select

from app import config
from app import prompts as _prompts
from app.bullet_bank_service import list_bank, list_tags, text_key
from app.db import session_scope
from app.evaluator import price
from app.models import BulletTagging, BulletTagSuggestion, TagSuggestBatch, _now
from app.scanners_service import NON_EXPERIENCE_SLOTS

BATCH_SIZE = 25
MAX_TAGS_PER_BULLET = 3


class TaggerUnavailable(RuntimeError):
    """No usable Anthropic credentials, or nothing to tag."""


class TagPick(BaseModel):
    tag: str = Field(description="A tag name, exactly as written in the list.")
    reason: str = Field(description="One short sentence: what in the bullet fits the definition.")


class BulletPicks(BaseModel):
    index: int = Field(description="The bullet's number from the list.")
    tags: list[TagPick] = Field(default_factory=list, description="Up to 3; empty when none clearly fits.")


class TaggerOutput(BaseModel):
    bullets: list[BulletPicks]


def _output_format(names: list[str]):
    """TaggerOutput with `tag` constrained to the exact tag names, so the
    structured output cannot return anything else. The first live run, with
    a free-text `tag`, came back with 27 picks and not one matched a name."""
    tag_name = Literal[tuple(names)]  # type: ignore[valid-type]
    pick = create_model("TagPick", tag=(tag_name, Field(description=TagPick.model_fields["tag"].description)),
                        reason=(str, Field(description=TagPick.model_fields["reason"].description)))
    picks = create_model("BulletPicks", index=(int, Field(description="The bullet's number from the list.")),
                         tags=(list[pick], Field(default_factory=list, description="Up to 3; empty when none clearly fits.")))
    return create_model("TaggerOutput", bullets=(list[picks], ...))


def _name_key(name: str) -> str:
    """Lenient match on a returned name: case, quotes and a trailing
    "(Category)" do not count."""
    name = name.strip().strip('"\'').strip()
    return re.sub(r"\s*\([^)]*\)\s*$", "", name).lower()


def _client():
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover
        raise TaggerUnavailable("anthropic package is not installed") from exc
    return anthropic.Anthropic()


def is_experience(slots: list[str]) -> bool:
    """A sentence counts if it appears under any professional-experience
    section, even if it is also reused under a non-experience one."""
    return any(slot not in NON_EXPERIENCE_SLOTS for slot in slots)


def _already_asked() -> set[str]:
    with session_scope() as session:
        asked: set[str] = set()
        for (texts,) in session.execute(select(TagSuggestBatch.texts)):
            asked.update(texts or [])
        return asked


def pending_sentences(texts: list[str] | None = None) -> list[str]:
    """Experience sentences (optionally limited to `texts`) that have not
    been through the suggester yet, most recently used first."""
    wanted = {text_key(t) for t in texts} if texts is not None else None
    asked = _already_asked()
    return [
        row["text"]
        for row in list_bank()
        if is_experience(row["slots"])
        and row["text"] not in asked
        and (wanted is None or row["text"] in wanted)
    ]


def _render(tags: list[dict], sentences: list[str]) -> str:
    tag_lines = [
        f"- Tag: {t['name']}\n  Category: {t['category'] or 'Uncategorized'}\n  Definition: {t['definition'] or 'None.'}"
        for t in tags
    ]
    bullet_lines = [f"{i}. {s}" for i, s in enumerate(sentences, start=1)]
    return "Tags:\n" + "\n".join(tag_lines) + "\n\nBullets:\n" + "\n".join(bullet_lines)


def _call(user: str, *, client, model: str, version: str, output_format=TaggerOutput):
    try:
        response = client.messages.parse(
            model=model,
            max_tokens=4096,
            system=_prompts.load_prompt("bullet_tagger", version),
            messages=[{"role": "user", "content": user}],
            output_format=output_format,
            thinking={"type": "disabled"},
        )
    except TypeError as exc:
        if "authentication" in str(exc).lower():
            raise TaggerUnavailable("no Anthropic credentials found") from exc
        raise
    except Exception as exc:
        if type(exc).__name__ in {"AuthenticationError", "PermissionDeniedError"}:
            raise TaggerUnavailable("no Anthropic credentials found") from exc
        raise
    usage = getattr(response, "usage", None)
    return response.parsed_output, getattr(usage, "input_tokens", None), getattr(usage, "output_tokens", None)


def suggest_tags(
    texts: list[str] | None = None,
    *,
    client=None,
    on_progress: Callable[[str], None] | None = None,
) -> dict:
    """Ask for suggestions on every pending experience sentence (optionally
    only those in `texts`), BATCH_SIZE at a time. Unknown tag names, tags
    already on the sentence, and repeats of an earlier suggestion are
    dropped."""
    tags = list_tags()
    if not tags:
        raise TaggerUnavailable("there are no tags to suggest")
    by_name = {_name_key(t["name"]): t["id"] for t in tags}
    output_format = _output_format([t["name"] for t in tags])
    todo = pending_sentences(texts)
    model = config.BULLET_TAGGER_MODEL
    version = config.BULLET_TAGGER_PROMPT_VERSION
    client = client or (_client() if todo else None)

    report = {"sentences": len(todo), "batches": 0, "suggestions": 0, "dropped": 0, "cost_usd": 0.0}
    for start in range(0, len(todo), BATCH_SIZE):
        batch = todo[start : start + BATCH_SIZE]
        parsed, tin, tout = _call(
            _render(tags, batch), client=client, model=model, version=version, output_format=output_format
        )
        cost = price(model, tin, tout)

        with session_scope() as session:
            row = TagSuggestBatch(
                texts=batch, model=model, prompt_version=version,
                input_tokens=tin, output_tokens=tout, cost_usd=cost,
            )
            session.add(row)
            session.flush()
            applied = {
                (k, t) for k, t in session.execute(
                    select(BulletTagging.text_key, BulletTagging.tag_id).where(BulletTagging.text_key.in_(batch))
                )
            }
            seen = {
                (k, t) for k, t in session.execute(
                    select(BulletTagSuggestion.text_key, BulletTagSuggestion.tag_id).where(
                        BulletTagSuggestion.text_key.in_(batch)
                    )
                )
            }
            for picks in parsed.bullets:
                if not 1 <= picks.index <= len(batch):
                    continue
                sentence = batch[picks.index - 1]
                kept = 0
                for pick in picks.tags:
                    tag_id = by_name.get(_name_key(pick.tag))
                    # The cap counts valid picks only: an invented tag name
                    # must not use up one of the three slots.
                    if (
                        tag_id is None
                        or (sentence, tag_id) in applied
                        or (sentence, tag_id) in seen
                        or kept >= MAX_TAGS_PER_BULLET
                    ):
                        report["dropped"] += 1
                        continue
                    kept += 1
                    seen.add((sentence, tag_id))
                    session.add(
                        BulletTagSuggestion(
                            text_key=sentence, tag_id=tag_id, reason=pick.reason.strip(), batch_id=row.id
                        )
                    )
                    report["suggestions"] += 1

        report["batches"] += 1
        report["cost_usd"] = round(report["cost_usd"] + (cost or 0), 6)
        if on_progress:
            for sentence in batch:
                on_progress(sentence)
    return report


def decide(suggestion_id: int, accept: bool) -> dict | None:
    """Accept (apply the tag) or reject one suggestion. None if unknown."""
    with session_scope() as session:
        suggestion = session.get(BulletTagSuggestion, suggestion_id)
        if suggestion is None:
            return None
        suggestion.status = "accepted" if accept else "rejected"
        suggestion.decided_at = _now()
        if accept and session.get(BulletTagging, (suggestion.text_key, suggestion.tag_id)) is None:
            session.add(BulletTagging(text_key=suggestion.text_key, tag_id=suggestion.tag_id))
        return {"id": suggestion.id, "status": suggestion.status, "text": suggestion.text_key, "tag_id": suggestion.tag_id}


def suggestion_stats() -> dict:
    with session_scope() as session:
        counts = dict(
            session.execute(
                select(BulletTagSuggestion.status, func.count()).group_by(BulletTagSuggestion.status)
            ).all()
        )
    return {status: counts.get(status, 0) for status in ("suggested", "accepted", "rejected")}


def total_tagger_cost() -> float:
    with session_scope() as session:
        return round(session.execute(select(func.coalesce(func.sum(TagSuggestBatch.cost_usd), 0.0))).scalar_one(), 6)
