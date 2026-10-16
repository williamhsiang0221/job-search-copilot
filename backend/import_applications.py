#!/usr/bin/env python
"""One-time import of the Notion Job Applications export.

    .venv/bin/python import_applications.py [--replace]

Reads docs/06_notion_applications.tsv. Safe to re-run: rows already present
are skipped rather than duplicated.
"""

import sys
from pathlib import Path

from app.applications_service import backfill_summary, import_from_tsv

DEFAULT = Path(__file__).resolve().parent.parent / "docs" / "06_notion_applications.tsv"


def main() -> int:
    path = DEFAULT
    if not path.exists():
        print(f"No export found at {path}", file=sys.stderr)
        return 1

    result = import_from_tsv(path, replace="--replace" in sys.argv)
    print(f"rows in file      : {result['rows_in_file']}")
    print(f"imported          : {result['imported']}")
    print(f"skipped (existing): {result['skipped_existing']}")

    summary = backfill_summary()
    print()
    print(f"outcome known for : {summary['known']} of {summary['total']}")
    print(f"needs backfill    : {summary['needs_backfill']}")
    if summary["needs_backfill"]:
        print()
        print("Rejected and withdrawn rows import with an unknown round on purpose:")
        print("Notion records only the final state, so a rejection that followed a")
        print("phone screen looks identical to one that followed silence.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
