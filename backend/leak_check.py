#!/usr/bin/env python
"""Scan the code that would be published for the candidate's personal data.

    .venv/bin/python leak_check.py            # scan this repo's tracked files
    .venv/bin/python leak_check.py PATH       # scan an exported tree instead

Two checks, both read-only:

1. Every term in profile/leak_denylist.txt (one per line, case-insensitive
   substring; blank lines and #-comments ignored) — the candidate's name,
   contact details, neighbourhood, employers, schools. The list is itself
   personal, so it lives in the profile and is never published.
2. Real resume wording: every 8-word run from every bullet stored in
   jobs.db. A test or comment that quotes a real bullet trips this even when
   no name is in it.

Paths that are never published (EXPORT_EXCLUDE) are skipped. Exits 1 if
anything is found, so an export can refuse to publish.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent
REPO = BACKEND.parent

# Never part of a public export (export_public.py copies everything else that
# git tracks): the candidate's profile and private tests, this project's
# internal working memory and machine-local helpers, and the LinkedIn
# guest-endpoint source with its tests and fixtures (undocumented endpoint).
EXPORT_EXCLUDE = (
    "backend/profile/",
    "BACKLOG.md",
    "LAUNCH.md",
    "launch.command",
    "authorize.command",
    ".claude/",
    "backend/app/linkedin_guest.py",
    "backend/tests/test_linkedin_guest.py",
    "backend/fixtures/linkedin_job_posting.html",
    "backend/fixtures/linkedin_job_expired.html",
)

NGRAM = 8
_WORD_RE = re.compile(r"[a-z0-9%$]+")


def _files(root: Path) -> list[Path]:
    """Tracked files when root is a git checkout, else every file under it."""
    try:
        listed = subprocess.run(
            ["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True
        ).stdout.splitlines()
        candidates = [root / p for p in listed]
    except (subprocess.CalledProcessError, FileNotFoundError):
        candidates = [p for p in root.rglob("*") if p.is_file() and ".git" not in p.parts]
    return [
        p for p in candidates
        if p.is_file() and not str(p.relative_to(root)).replace("\\", "/").startswith(EXPORT_EXCLUDE)
    ]


def _denylist(path: Path) -> list[str]:
    if not path.exists():
        return []
    terms = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            terms.append(line.lower())
    return terms


def _bullet_ngrams(db: Path) -> set[tuple[str, ...]]:
    if not db.exists():
        return set()
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
        texts = [t for (t,) in conn.execute("SELECT text FROM bullets")]
    grams: set[tuple[str, ...]] = set()
    for text in texts:
        words = _WORD_RE.findall(text.lower())
        grams.update(tuple(words[i : i + NGRAM]) for i in range(len(words) - NGRAM + 1))
    return grams


def scan(
    root: Path, denylist: list[str], grams: set[tuple[str, ...]], files: list[Path] | None = None
) -> list[tuple[str, int, str]]:
    """Findings as (path relative to root, line number, reason). `files`
    overrides the default selection (tracked files under root)."""
    hits = []
    for path in files if files is not None else _files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary
        rel = str(path.relative_to(root))
        for number, line in enumerate(text.splitlines(), start=1):
            lowered = line.lower()
            for term in denylist:
                if term in lowered:
                    hits.append((rel, number, f"term {term!r}"))
            words = _WORD_RE.findall(lowered)
            if any(tuple(words[i : i + NGRAM]) in grams for i in range(len(words) - NGRAM + 1)):
                hits.append((rel, number, "quotes a real resume bullet"))
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("root", nargs="?", type=Path, default=REPO, help="Tree to scan (default: this repo)")
    parser.add_argument("--denylist", type=Path, default=BACKEND / "profile" / "leak_denylist.txt")
    parser.add_argument("--db", type=Path, default=BACKEND / "jobs.db", help="Source of real bullets")
    args = parser.parse_args()

    denylist = _denylist(args.denylist)
    grams = _bullet_ngrams(args.db)
    if not denylist and not grams:
        print("Nothing to check against: no denylist and no bullets database. Refusing to report clean.")
        return 1

    hits = scan(args.root.resolve(), denylist, grams)
    for rel, number, why in hits:
        print(f"{rel}:{number}: {why}")
    files = len({rel for rel, _, _ in hits})
    print(f"{len(hits)} finding(s) in {files} file(s)." if hits else "Clean: no personal terms or real bullets found.")
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
