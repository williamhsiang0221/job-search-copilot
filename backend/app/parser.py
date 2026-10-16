"""Parse LinkedIn job-alert emails into structured role records.

LinkedIn sends a plaintext alternative alongside the HTML body, and it is far
more stable than the markup. Each job appears as a block separated by a run of
dashes:

    <title>
    <company>
    <location>
    [badge lines, e.g. "Top applicant", "1 school alum"]
    View job: https://www.linkedin.com/comm/jobs/view/<id>/?<tracking>

Both sender types (jobalerts-noreply@ for saved-search alerts, jobs-noreply@
for recommendations) use this same shape.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, replace

BLOCK_SEPARATOR = re.compile(r"^-{20,}\s*$", re.MULTILINE)
VIEW_JOB = re.compile(r"^View job:\s*(\S+)", re.MULTILINE)
JOB_ID = re.compile(r"/jobs/view/(\d+)")

# Fields we need before a block counts as a real job.
_REQUIRED = ("title", "company", "url")


@dataclass(frozen=True)
class Role:
    title: str
    company: str
    location: str
    url: str
    job_id: str
    source_subject: str = ""
    received_at: str = ""
    # How many alert emails carried this job. Overlapping saved searches mean
    # a strong match often arrives several times; the count is signal, not
    # just noise to be hidden.
    match_count: int = 1

    def as_dict(self) -> dict:
        return asdict(self)


def _line_groups(lines: list[str]) -> list[list[str]]:
    """Split lines into runs of contiguous non-blank lines."""
    groups: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if line.strip():
            current.append(line.strip())
        elif current:
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def _fields_before_view_job(block: str) -> list[str] | None:
    """Return the title/company/location lines preceding "View job:".

    Title, company and location are always three adjacent lines, but what
    surrounds them varies:

      - Badge lines ("Top applicant", "1 school alum") *trail* the location,
        sometimes with a blank line before them and sometimes not.
      - Section headers ("Your other saved jobs", the digest preamble) *lead*
        the title, likewise with or without a blank line.

    Splitting the block into runs of adjacent non-blank lines separates the two
    cases without needing a list of badge or header strings, which LinkedIn can
    extend at any time:

      - If three or more lines precede the link *within its own run*, the run
        starts at the title and any extras are trailing badges -> take the
        first three.
      - Otherwise the fields sit in an earlier run that may be led by a header
        -> take the three lines closest to the link.
    """
    groups = _line_groups(block.splitlines())

    for idx, group in enumerate(groups):
        view_at = next(
            (i for i, line in enumerate(group) if line.startswith("View job:")),
            None,
        )
        if view_at is None:
            continue

        preceding = group[:view_at]
        if len(preceding) >= 3:
            return preceding[:3]

        # Fields live in an earlier run. Accumulate backward until there are
        # enough lines, then keep the ones nearest the link.
        earlier: list[str] = []
        back = idx - 1
        while back >= 0 and len(earlier) < 3:
            earlier = groups[back] + earlier
            back -= 1

        return earlier[-3:] if len(earlier) >= 3 else None

    return None


def parse_email_body(
    body: str, *, subject: str = "", received_at: str = ""
) -> list[Role]:
    """Extract every job listed in one LinkedIn alert email."""
    roles: list[Role] = []

    for block in BLOCK_SEPARATOR.split(body):
        match = VIEW_JOB.search(block)
        if not match:
            continue

        raw_url = match.group(1)
        job_id_match = JOB_ID.search(raw_url)
        if not job_id_match:
            continue
        job_id = job_id_match.group(1)

        fields = _fields_before_view_job(block)
        if not fields:
            continue

        title, company, location = fields[0], fields[1], fields[2]
        if not title or not company:
            continue

        roles.append(
            Role(
                title=title,
                company=company,
                location=location,
                # Drop LinkedIn's tracking payload — the canonical URL resolves
                # to the same posting and is short enough to read in a table.
                url=f"https://www.linkedin.com/jobs/view/{job_id}/",
                job_id=job_id,
                source_subject=subject,
                received_at=received_at,
            )
        )

    return roles


def parse_messages(messages: list[dict]) -> list[Role]:
    """Flatten a list of Gmail message dicts into roles, in message order."""
    roles: list[Role] = []
    for message in messages:
        roles.extend(
            parse_email_body(
                message.get("body", ""),
                subject=message.get("subject", ""),
                received_at=message.get("received_at", ""),
            )
        )
    return roles


def dedupe_roles(roles: list[Role]) -> list[Role]:
    """Collapse repeats of the same posting, counting how often each appeared.

    Overlapping saved searches surface the same job repeatedly - across a week
    of real mail roughly a third of rows are repeats. The LinkedIn job id is a
    safe key: the same id never disagrees about its title or company.

    The first occurrence's fields are kept, with two exceptions. Location varies
    between copies ("New York" vs "New York, NY"), so the longest seen is
    preferred as the more specific of the two. received_at becomes the *latest*
    of the copies, so the column answers "when did this job last appear" rather
    than "when was it first noticed".
    """
    first_seen: dict[str, Role] = {}
    counts: dict[str, int] = {}
    locations: dict[str, str] = {}
    latest: dict[str, str] = {}

    for role in roles:
        if role.job_id not in first_seen:
            first_seen[role.job_id] = role
            counts[role.job_id] = 0
            locations[role.job_id] = role.location
            latest[role.job_id] = role.received_at
        counts[role.job_id] += 1
        if len(role.location) > len(locations[role.job_id]):
            locations[role.job_id] = role.location
        # Dates are normalised to UTC ISO upstream, so a string compare is a
        # chronological one. "Last seen" is the most recent alert to carry the
        # job, which is not necessarily the copy encountered first.
        if role.received_at > latest[role.job_id]:
            latest[role.job_id] = role.received_at

    return [
        replace(
            role,
            match_count=counts[job_id],
            location=locations[job_id],
            received_at=latest[job_id],
        )
        for job_id, role in first_seen.items()
    ]
