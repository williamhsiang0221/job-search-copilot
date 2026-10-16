#!/usr/bin/env python
"""One-off ingest of a tailored resume PDF into the resumes/sections/bullets
data layer (see app/resume_ingest_service.py for the parsing rules).

    .venv/bin/python ingest_resume.py <path-to-pdf> [--company X] [--title Y]

--company/--title override the values parsed from the filename, for the two
known filenames that don't parse cleanly (a literal "&" or an accented
letter mangled on save). Safe to re-run: an already-ingested filename is a
no-op, not a duplicate.
"""

import argparse
from pathlib import Path

from app.db import session_scope
from app.resume_ingest_service import ResumeIngestError, ingest_resume


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf_path", type=Path)
    parser.add_argument("--company", default=None, help="Override the company parsed from the filename")
    parser.add_argument("--title", default=None, help="Override the title parsed from the filename")
    args = parser.parse_args()

    if not args.pdf_path.exists():
        print(f"No file at {args.pdf_path}")
        return 1

    try:
        with session_scope() as session:
            result = ingest_resume(
                args.pdf_path,
                session=session,
                company_override=args.company,
                title_override=args.title,
            )
    except ResumeIngestError as exc:
        print(f"Ingest failed: {exc}")
        return 1

    if result["status"] == "already_ingested":
        print(f"Already ingested as {result['resume_id']}")
    else:
        print(f"Ingested {result['resume_id']}: {result['sections']} sections, {result['bullets']} bullets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
