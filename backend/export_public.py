#!/usr/bin/env python
"""Build the public repository from this private one.

    .venv/bin/python export_public.py --dry-run # build and check only
    .venv/bin/python export_public.py           # build and commit locally
    .venv/bin/python export_public.py --push    # ...then push to its remote

Copies every git-tracked file except leak_check.EXPORT_EXCLUDE into
public-export/ (a separate git repository with its own history), strips
`<!-- private-only -->` ... `<!-- /private-only -->` blocks from Markdown,
then runs every gate inside the exported tree. Nothing is committed unless
all of them pass:

1. leak check — no personal term, no real resume sentence
2. links — every relative link in a Markdown file points at a file that exists
3. backend tests, run in the export
4. frontend type check (tsc -b), run in the export
5. the demo builds from scratch in the export

Each export is one commit, "Update from private repo (date)", authored as
profile/settings.json's export_author — never this repository's history.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

import leak_check

BACKEND = Path(__file__).resolve().parent
REPO = BACKEND.parent
EXPORT = REPO / "public-export"
PYTHON = BACKEND / ".venv" / "bin" / "python"

_PRIVATE_BLOCK_RE = re.compile(r"\n?<!-- private-only -->.*?<!-- /private-only -->\n?", re.S)
_MD_LINK_RE = re.compile(r"\]\(([^)\s#]+)(?:#[^)]*)?\)|<img [^>]*src=\"([^\"]+)\"")


def run(cmd: list[str], cwd: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, env={**os.environ, **(env or {})}, capture_output=True, text=True)


def tracked_files(dry_run: bool) -> list[str]:
    dirty = run(["git", "status", "--porcelain", "--untracked-files=no"], REPO).stdout.strip()
    if dirty and not dry_run:
        sys.exit(f"Refusing to export uncommitted changes:\n{dirty}")
    listed = run(["git", "ls-files"], REPO).stdout.splitlines()
    return [p for p in listed if not p.startswith(leak_check.EXPORT_EXCLUDE)]


def copy_tree(files: list[str]) -> None:
    EXPORT.mkdir(exist_ok=True)
    for child in EXPORT.iterdir():  # keep only the export's own .git
        if child.name != ".git":
            shutil.rmtree(child) if child.is_dir() else child.unlink()
    for rel in files:
        src, dst = REPO / rel, EXPORT / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if rel.endswith(".md"):
            dst.write_text(_PRIVATE_BLOCK_RE.sub("\n", src.read_text(encoding="utf-8")), encoding="utf-8")
        else:
            shutil.copy2(src, dst)


def broken_links() -> list[str]:
    broken = []
    for md in EXPORT.rglob("*.md"):
        if ".git" in md.parts or "node_modules" in md.parts:
            continue
        for match in _MD_LINK_RE.finditer(md.read_text(encoding="utf-8")):
            target = match.group(1) or match.group(2)
            if re.match(r"^[a-z]+:", target):  # http:, https:, mailto:
                continue
            if not (md.parent / target).resolve().exists():
                broken.append(f"{md.relative_to(EXPORT)} -> {target}")
    return broken


def gates() -> list[str]:
    failures = []

    denylist = leak_check._denylist(BACKEND / "profile" / "leak_denylist.txt")
    grams = leak_check._bullet_ngrams(BACKEND / "jobs.db")
    if not denylist or not grams:
        failures.append("leak check has nothing to check against (no denylist or no bullets)")
    # Every file in the export, explicitly: it is not committed yet, so
    # leak_check's default (git-tracked files) would see nothing.
    exported = [p for p in EXPORT.rglob("*") if p.is_file() and ".git" not in p.relative_to(EXPORT).parts]
    hits = leak_check.scan(EXPORT, denylist, grams, files=exported)
    failures += [f"leak: {rel}:{line}: {why}" for rel, line, why in hits]

    failures += [f"broken link: {b}" for b in broken_links()]

    with tempfile.TemporaryDirectory() as tmp:
        tests = run([str(PYTHON), "-m", "pytest", "-q"], EXPORT / "backend", {"JOB_BOARD_DB": f"{tmp}/test.db"})
        if tests.returncode != 0:
            failures.append("backend tests failed:\n" + tests.stdout[-2000:])

    node_modules = EXPORT / "frontend" / "node_modules"
    node_modules.symlink_to(REPO / "frontend" / "node_modules")
    try:
        tsc = run(["npx", "tsc", "-b"], EXPORT / "frontend")
        if tsc.returncode != 0:
            failures.append("frontend type check failed:\n" + (tsc.stdout + tsc.stderr)[-2000:])
    finally:
        node_modules.unlink()

    demo = run([str(PYTHON), "demo/seed_demo.py"], EXPORT / "backend")
    (EXPORT / "backend" / "demo.db").unlink(missing_ok=True)
    if demo.returncode != 0:
        failures.append("demo seed failed:\n" + (demo.stdout + demo.stderr)[-2000:])

    return failures


def commit(push: bool) -> None:
    author = json.loads((BACKEND / "profile" / "settings.json").read_text())["export_author"]
    if not (EXPORT / ".git").exists():
        run(["git", "init", "-b", "main"], EXPORT)
    identity = ["-c", f"user.name={author['name']}", "-c", f"user.email={author['email']}"]
    run(["git", "add", "-A"], EXPORT)
    if not run(["git", "status", "--porcelain"], EXPORT).stdout.strip():
        print("No changes since the last export.")
    else:
        result = run(["git", *identity, "commit", "-q", "-m", f"Update from private repo ({date.today():%Y-%m-%d})"], EXPORT)
        if result.returncode != 0:
            sys.exit("commit failed:\n" + result.stderr)
        print(run(["git", "log", "--oneline", "-1"], EXPORT).stdout.strip())
    if push:
        result = run(["git", "push", "-u", "origin", "main"], EXPORT)
        print(result.stdout + result.stderr)
        if result.returncode != 0:
            sys.exit("push failed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--push", action="store_true", help="push to the export repo's origin after committing")
    parser.add_argument("--dry-run", action="store_true", help="build and run the gates; no clean-tree check, no commit")
    args = parser.parse_args()

    files = tracked_files(args.dry_run)
    copy_tree(files)
    print(f"Copied {len(files)} files to {EXPORT}")
    failures = gates()
    if failures:
        print("Export blocked — nothing committed:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("All gates passed: leak check, links, backend tests, frontend type check, demo seed.")
    if args.dry_run:
        print("Dry run: nothing committed.")
        return 0
    commit(args.push)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
