#!/usr/bin/env python
"""Re-run the current normalizer prompt over postings already stored.

    .venv/bin/python renormalize.py SOURCE/JOB_ID [SOURCE/JOB_ID ...]
    .venv/bin/python renormalize.py --assembled
    .venv/bin/python renormalize.py --missing-summary --limit 20

Works from the stored raw description, so nothing is refetched. Each row is
overwritten and stamped with the new normalizer_version. Costs one
normalizer call per job (~$0.005 on Haiku) plus a fraction of a cent to
re-embed.

--assembled picks every job that has a Resume Assembler run;
--missing-summary picks jobs normalized before role_summary existed.
"""

import argparse

from sqlalchemy import select

from app.db import session_scope
from app.jobs_service import renormalize
from app.models import AssemblyRun, JobNormalized


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("jobs", nargs="*", help="SOURCE/JOB_ID, e.g. linkedin/4465301126")
    parser.add_argument("--assembled", action="store_true", help="Every job with an assembly run")
    parser.add_argument("--missing-summary", action="store_true", help="Jobs never asked for a role_summary")
    parser.add_argument("--limit", type=int, default=None, help="At most this many jobs")
    args = parser.parse_args()

    keys = [tuple(j.split("/", 1)) for j in args.jobs]
    with session_scope() as session:
        if args.assembled:
            keys += session.execute(select(AssemblyRun.source, AssemblyRun.job_id).distinct()).all()
        if args.missing_summary:
            keys += session.execute(
                select(JobNormalized.source, JobNormalized.job_id).where(JobNormalized.role_summary.is_(None))
            ).all()
    keys = list(dict.fromkeys(tuple(k) for k in keys))[: args.limit]
    if not keys:
        print("Nothing to re-normalize.")
        return 1

    report = renormalize(keys)
    print(f"Re-normalized {len(report.normalized)} of {len(keys)} job(s), ${report.cost_usd:.4f} in normalizer calls.")
    for job_id, error in {**report.failures, **report.normalize_failures}.items():
        print(f"  failed {job_id}: {error}")
    for job_id, sentences in report.role_summary_rejected.items():
        print(f"  {job_id}: dropped {len(sentences)} role_summary sentence(s) not found in the posting")
    return 0 if not (report.failures or report.normalize_failures) else 1


if __name__ == "__main__":
    raise SystemExit(main())
