"""Bullet Bank: every distinct resume bullet, searchable and taggable.

The unit is the *sentence*, not the bullet row — 1,300 bullet rows across the
uploaded resumes hold under 300 distinct sentences, because the same line is
reused from resume to resume. Each sentence carries how many resumes used it
and when it was last used, so the bank reads as "what have I written, and
what do I still use".

Search is deliberately plain: comma-separated keywords, every one must
appear as a case-insensitive substring (the user's choice over word-start
matching, knowing "ai" also hits "campaign"). Tags narrow it the same way:
every selected tag must be on the sentence.
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.db import session_scope
from app.models import ROLE_CATEGORIES, Bullet, BulletTag, BulletTagging, BulletTagSuggestion, Resume, Section


class BulletBankError(ValueError):
    """A bad tag request — unknown id, duplicate name, unknown category."""


def text_key(text: str) -> str:
    """The sentence identity: whitespace-collapsed, otherwise exact."""
    return " ".join(text.split())


def parse_keywords(query: str | None) -> list[str]:
    return [k.strip().lower() for k in (query or "").split(",") if k.strip()]


def list_bank(
    keywords: list[str] | None = None,
    tag_ids: list[int] | None = None,
    untagged: bool = False,
) -> list[dict]:
    """Distinct sentences matching every keyword and every tag, most recently
    used first. Each carries the sections it appears in, its tag ids, and
    every resume that used it (for the expand panel)."""
    keywords = keywords or []
    wanted_tags = set(tag_ids or [])

    with session_scope() as session:
        rows = session.execute(
            select(Bullet.text, Section.slot, Resume.id, Resume.company, Resume.title, Resume.resume_date)
            .join(Section, Section.id == Bullet.section_id)
            .join(Resume, Resume.id == Section.resume_id)
        ).all()
        taggings = session.execute(select(BulletTagging.text_key, BulletTagging.tag_id)).all()
        pending = session.execute(
            select(
                BulletTagSuggestion.id, BulletTagSuggestion.text_key, BulletTagSuggestion.tag_id, BulletTagSuggestion.reason
            ).where(BulletTagSuggestion.status == "suggested")
        ).all()

    tags_by_key: dict[str, set[int]] = {}
    for key, tag_id in taggings:
        tags_by_key.setdefault(key, set()).add(tag_id)
    suggestions_by_key: dict[str, list[dict]] = {}
    for suggestion_id, key, tag_id, reason in pending:
        # A tag the user already applied by hand needs no suggestion chip.
        if tag_id not in tags_by_key.get(key, set()):
            suggestions_by_key.setdefault(key, []).append({"id": suggestion_id, "tag_id": tag_id, "reason": reason})

    bank: dict[str, dict] = {}
    for text, slot, resume_id, company, title, resume_date in rows:
        key = text_key(text)
        entry = bank.setdefault(key, {"text": key, "slots": [], "resumes": {}})
        if slot not in entry["slots"]:
            entry["slots"].append(slot)
        entry["resumes"].setdefault(
            resume_id,
            {
                "resume_id": resume_id,
                "company": company,
                "title": title,
                "resume_date": resume_date.isoformat() if resume_date else None,
            },
        )

    results = []
    for key, entry in bank.items():
        lowered = key.lower()
        if not all(k in lowered for k in keywords):
            continue
        tags = tags_by_key.get(key, set())
        if untagged and tags:
            continue
        if not wanted_tags <= tags:
            continue
        resumes = sorted(entry["resumes"].values(), key=lambda r: r["resume_date"] or "", reverse=True)
        results.append(
            {
                "text": key,
                "slots": entry["slots"],
                "resume_count": len(resumes),
                "last_used": resumes[0]["resume_date"] if resumes else None,
                "tag_ids": sorted(tags),
                "suggestions": suggestions_by_key.get(key, []),
                "resumes": resumes,
            }
        )

    results.sort(key=lambda r: (r["last_used"] or "", r["resume_count"]), reverse=True)
    return results


def _tag_dict(tag: BulletTag, usage: int = 0) -> dict:
    return {
        "id": tag.id,
        "name": tag.name,
        "category": tag.category,
        "definition": tag.definition or "",
        "usage": usage,
    }


def _check_category(category: str | None) -> str | None:
    category = (category or "").strip() or None
    if category is not None and category not in ROLE_CATEGORIES:
        raise BulletBankError(f"unknown category {category!r}; use one of {ROLE_CATEGORIES} or none")
    return category


def _name_taken(session, name: str, except_id: int | None = None) -> bool:
    query = select(BulletTag.id).where(func.lower(BulletTag.name) == name.lower())
    if except_id is not None:
        query = query.where(BulletTag.id != except_id)
    return session.execute(query).first() is not None


def list_tags() -> list[dict]:
    """Every tag, in role-category order then by name, with how many
    sentences carry it."""
    with session_scope() as session:
        usage = dict(
            session.execute(
                select(BulletTagging.tag_id, func.count()).group_by(BulletTagging.tag_id)
            ).all()
        )
        tags = session.execute(select(BulletTag)).scalars().all()
        order = {c: i for i, c in enumerate(ROLE_CATEGORIES)}
        tags.sort(key=lambda t: (order.get(t.category, len(order)), t.id))
        return [_tag_dict(t, usage.get(t.id, 0)) for t in tags]


def create_tag(name: str, category: str | None = None, definition: str = "") -> dict:
    name = (name or "").strip()
    if not name:
        raise BulletBankError("a tag needs a name")
    category = _check_category(category)
    with session_scope() as session:
        if _name_taken(session, name):
            raise BulletBankError(f"a tag named {name!r} already exists")
        tag = BulletTag(name=name, category=category, definition=(definition or "").strip())
        session.add(tag)
        session.flush()
        return _tag_dict(tag)


def update_tag(tag_id: int, **changes) -> dict:
    with session_scope() as session:
        tag = session.get(BulletTag, tag_id)
        if tag is None:
            raise BulletBankError(f"no tag {tag_id}")
        if "name" in changes:
            name = (changes["name"] or "").strip()
            if not name:
                raise BulletBankError("a tag needs a name")
            if _name_taken(session, name, except_id=tag_id):
                raise BulletBankError(f"a tag named {name!r} already exists")
            tag.name = name
        if "category" in changes:
            tag.category = _check_category(changes["category"])
        if "definition" in changes:
            tag.definition = (changes["definition"] or "").strip()
        session.flush()
        return _tag_dict(tag)


def delete_tag(tag_id: int) -> None:
    """Delete a tag and take it off every sentence. Explicit, not left to
    ON DELETE CASCADE, which SQLite only honours with a pragma on."""
    with session_scope() as session:
        tag = session.get(BulletTag, tag_id)
        if tag is None:
            raise BulletBankError(f"no tag {tag_id}")
        session.query(BulletTagging).filter(BulletTagging.tag_id == tag_id).delete()
        session.delete(tag)


def set_sentence_tags(text: str, tag_ids: list[int]) -> list[int]:
    """Replace the tags on one sentence. The sentence must exist in some
    resume; every tag must exist."""
    key = text_key(text)
    wanted = sorted(set(tag_ids))
    with session_scope() as session:
        # A full scan: ~1,300 rows, and stored text may differ from the key in
        # whitespace, so a SQL equality or LIKE prefix would miss real matches.
        if not any(text_key(t) == key for (t,) in session.execute(select(Bullet.text))):
            raise BulletBankError("no bullet with that text")
        existing_tags = set(session.execute(select(BulletTag.id).where(BulletTag.id.in_(wanted))).scalars())
        missing = [t for t in wanted if t not in existing_tags]
        if missing:
            raise BulletBankError(f"no tag(s) {missing}")
        session.query(BulletTagging).filter(BulletTagging.text_key == key).delete()
        for tag_id in wanted:
            session.add(BulletTagging(text_key=key, tag_id=tag_id))
    return wanted
