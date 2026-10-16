"""Tracked companies, and scanning their boards for open roles.

Mirrors the existing n8n pipeline's own filtering (same keyword and location
lists, same posted-within-3-days cutoff), since that list was already tuned
against real postings — this isn't a from-scratch redesign, just the same
workflow run from inside the dashboard instead of n8n, feeding this app's own
normalizer and evaluator instead of n8n's separate title-only scoring.

Like Capture, scanning is stateless: nothing is written to the database until
a role is selected and fetched.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import requests
from sqlalchemy import select

from app import config
from app.db import session_scope
from app.jd_sources import oracle_job_url, parse_oracle_token
from app.models import ATS_SOURCES, TrackedCompany

TIMEOUT = 25

# Started as a copy of the n8n workflow's Trim & Filter list, which leaned
# almost entirely towards PM: "product manager" alone caught every PM title,
# while marketing, analytics and AI strategy relied on exact phrasings boards
# rarely use. Re-tuned against a 14-day dry scan of every tracked board.
# All matching is whole-word and case-insensitive.

# Any of these in a title is enough on its own.
TITLE_KEYWORDS = [
    # Product
    "product manager", "product management", "product lead", "senior pm",
    "growth pm", "product operations", "product strategy",
    # Bank-style product titles (JPMC): an associate/owner/director ladder
    # rather than "product manager".
    "product associate", "product owner", "product director",
    # Marketing
    "product marketing", "growth marketing", "lifecycle marketing", "lifecycle",
    "retention marketing", "performance marketing", "integrated marketing",
    "user acquisition", "marketing analytics", "marketing science",
    "marketing sciences", "marketing ai", "growth strategy",
    "marketing strategy", "customer engagement marketing", "acquisition strategy",
    # Analytics
    "product analyst", "product data analyst", "senior analyst, product",
    "growth analyst", "business analyst", "data analyst", "marketing analyst",
    "analytics lead", "analytics manager", "manager, analytics",
    "director, analytics", "product analytics", "insights",
    # AI strategy
    "ai strategist", "ai strategy", "ai transformation", "agent strategist",
    "strategist, agent", "agent pm", "solutions pm", "ai deployment",
    "ai deployments", "ai solutions", "ai enablement", "ai adoption",
    "forward deployed", "forward-deployed",
]

# These pass only when the title also names one of the qualifiers — generic
# Strategy & Operations and data science are too broad on their own.
QUALIFIED_TITLE_KEYWORDS = [
    (
        ["strategy & operations", "strategy and operations", "strategy/operations",
         "strategy & ops", "business operations", "bizops"],
        ["growth", "gtm", "go-to-market", "marketing", "ai"],
    ),
    (
        ["data scientist", "data science"],
        ["growth", "marketing", "product", "experimentation"],
    ),
]

# A job-type word here rules a title out even when a keyword matched, e.g.
# "Forward Deployed Engineer" or "Staff Product Designer, Growth".
TITLE_EXCLUDE = [
    "engineer", "engineering manager", "engineering lead", "designer",
    "architect", "account executive", "recruiter", "sourcer", "counsel",
    "intern", "fellows",
]

# The candidate's target locations, from the profile (settings.json).
LOCATION_KEYWORDS = config.TARGET_LOCATIONS


def _whole_words(phrases: list[str]) -> re.Pattern:
    return re.compile(r"\b(?:" + "|".join(re.escape(p) for p in phrases) + r")\b")


# Whole-word match: a bare substring check let short keywords like "la" pass
# Atlanta, Dallas, Portland, Philadelphia, and so on.
_LOCATION_RE = _whole_words(LOCATION_KEYWORDS)
_TITLE_RE = _whole_words(TITLE_KEYWORDS)
_QUALIFIED_TITLE_RES = [
    (_whole_words(phrases), _whole_words(qualifiers))
    for phrases, qualifiers in QUALIFIED_TITLE_KEYWORDS
]
_TITLE_EXCLUDE_RE = _whole_words(TITLE_EXCLUDE)


def _title_matches(title: str) -> bool:
    # Collapse runs of whitespace — real titles carry double spaces
    # ("Card Acquisition  Strategy") that would break a phrase match.
    title_l = " ".join(title.lower().split())
    if _TITLE_EXCLUDE_RE.search(title_l):
        return False
    if _TITLE_RE.search(title_l):
        return True
    return any(
        phrase.search(title_l) and qualifier.search(title_l)
        for phrase, qualifier in _QUALIFIED_TITLE_RES
    )

# Roles older than this are assumed already seen on a prior scan. Matches
# n8n's own cadence assumption; a board never scanned within this window will
# miss anything posted before it.
POSTED_CUTOFF_DAYS = 3


@dataclass
class Candidate:
    """A role found on a scan, before any description has been fetched."""

    source: str
    job_id: str
    board_token: str
    title: str
    company: str
    location: str = ""
    url: str = ""
    posted_at: str | None = None

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "job_id": self.job_id,
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "url": self.url,
            "posted_at": self.posted_at,
        }


@dataclass
class ScanReport:
    candidates: list[Candidate] = field(default_factory=list)
    companies_scanned: int = 0
    companies_failed: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "candidates": [c.as_dict() for c in self.candidates],
            "companies_scanned": self.companies_scanned,
            "companies_failed": self.companies_failed,
        }


def _passes_filter(title: str, location: str, posted_at: date | None, cutoff: date) -> bool:
    if posted_at and posted_at < cutoff:
        return False
    if not _title_matches(title):
        return False
    location_l = location.lower()
    # An unstated location is not excluded — filtering it out would silently
    # drop remote-first boards that just don't fill the field in.
    if location_l and not _LOCATION_RE.search(location_l):
        return False
    return True


def _list_greenhouse(token: str) -> list[dict]:
    response = requests.get(
        f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs", timeout=TIMEOUT
    )
    response.raise_for_status()
    jobs = response.json().get("jobs") or []
    results = []
    for job in jobs:
        posted = None
        if job.get("updated_at"):
            try:
                posted = datetime.fromisoformat(job["updated_at"]).date()
            except ValueError:
                posted = None
        results.append(
            {
                "job_id": str(job.get("id") or ""),
                "title": job.get("title") or "",
                "location": (job.get("location") or {}).get("name") or "",
                "url": job.get("absolute_url") or "",
                "posted_at": posted,
            }
        )
    return results


def _list_ashby(token: str) -> list[dict]:
    response = requests.get(
        f"https://api.ashbyhq.com/posting-api/job-board/{token}", timeout=TIMEOUT
    )
    response.raise_for_status()
    jobs = response.json().get("jobs") or []
    results = []
    for job in jobs:
        if job.get("isListed") is False:
            continue
        posted = None
        if job.get("publishedAt"):
            try:
                posted = datetime.fromisoformat(job["publishedAt"]).date()
            except ValueError:
                posted = None
        results.append(
            {
                "job_id": str(job.get("id") or ""),
                "title": job.get("title") or "",
                "location": job.get("location") or "",
                "url": job.get("jobUrl") or "",
                "posted_at": posted,
            }
        )
    return results


def _list_lever(token: str) -> list[dict]:
    response = requests.get(
        f"https://api.lever.co/v0/postings/{token}?mode=json", timeout=TIMEOUT
    )
    response.raise_for_status()
    postings = response.json() or []
    results = []
    for job in postings:
        posted = None
        if job.get("createdAt"):
            try:
                posted = datetime.fromtimestamp(int(job["createdAt"]) / 1000).date()
            except (ValueError, OSError, OverflowError):
                posted = None
        categories = job.get("categories") or {}
        results.append(
            {
                "job_id": str(job.get("id") or ""),
                "title": job.get("text") or "",
                "location": categories.get("location") or "",
                "url": job.get("hostedUrl") or "",
                "posted_at": posted,
            }
        )
    return results


def _parse_workday_relative_date(text: str | None, today: date) -> date | None:
    """Workday's list endpoint gives "Posted Today"/"Posted N Days Ago" —
    relative text, not a timestamp like the other three ATSes. Approximate on
    purpose: this only feeds the posted-within-3-days cutoff filter, so
    "N+ days ago" being off by a day or two still filters the same way."""
    if not text:
        return None
    normalized = text.strip().lower()
    if normalized == "posted today":
        return today
    if normalized == "posted yesterday":
        return today - timedelta(days=1)
    match = re.match(r"posted (\d+)\+? days? ago", normalized)
    if match:
        return today - timedelta(days=int(match.group(1)))
    return None


def _workday_us_facet_id(base: str) -> str | None:
    """This tenant's own facet id for United States, or None if it can't be
    found. Facet ids are per-tenant configuration, not portable across
    companies — confirmed live that an id which worked on one company 400'd
    on another — so each company needs its own cheap lookup (one request,
    limit=1) rather than a hardcoded constant. Failure here is never fatal:
    the caller falls back to an unfiltered search."""
    try:
        response = requests.post(
            f"{base}/jobs",
            json={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""},
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        facets = response.json().get("facets") or []
    except requests.RequestException:
        return None

    for facet in facets:
        if facet.get("facetParameter") != "Location_Country":
            continue
        for value in facet.get("values") or []:
            if value.get("descriptor") == "United States of America":
                return value.get("id")
    return None


_WORKDAY_MULTI_LOCATION_RE = re.compile(r"^\d+ locations$", re.I)


def _workday_location(text: str | None) -> str:
    """Workday's list shows "2 Locations" instead of the place names when a
    role has several, and the names are only on the detail page. Treated as
    unstated (blank), which the location filter lets through, rather than as
    a real location that matches nothing. Workday only: no other board here
    uses this placeholder."""
    text = (text or "").strip()
    return "" if _WORKDAY_MULTI_LOCATION_RE.match(text) else text


def _list_workday(token: str) -> list[dict]:
    """Paginated, unlike the other three — Workday caps each page at 20
    results (confirmed live; 50 and above are rejected with a 400). Two
    optimizations on top of plain pagination, both confirmed live rather than
    assumed, since a large global company's full board is enormous otherwise
    (Morgan Stanley: 1,342 postings):

    - Filtered to Location_Country=United States server-side, since every
      keyword this app filters for afterward is US-specific anyway. Cuts
      Morgan Stanley to 932 — real but modest, since it is a US-headquartered
      company; would help more for a board with a bigger non-US presence.
    - Stopped as soon as a page contains a posting older than the same
      POSTED_CUTOFF_DAYS the caller filters to anyway. Confirmed live across
      four independent companies that results come back newest-first by
      default with no sort parameter needed, so the first stale posting
      guarantees everything after it is stale too. This is the bigger win —
      turns a scan proportional to the whole board into one proportional to
      just its last few days, regardless of total board size.

    `total` is only trustworthy on the first page — confirmed live that it
    degrades to 0 on later pages of a large board while `jobPostings` keeps
    returning data, and that data itself starts cycling back through
    already-seen postings rather than ending cleanly: stopping on an empty
    page alone ran for 200 pages (the hard cap) and returned 3,982 entries
    for only 1,342 unique job ids. So the first page's total is frozen as the
    real target, job ids are de-duplicated on the way in as a second line of
    defense, and the iteration cap stays as a last resort.
    """
    tenant, wd, site = token.split("/", 2)
    base = f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}"
    today = date.today()
    cutoff = today - timedelta(days=POSTED_CUTOFF_DAYS)
    limit = 20
    max_pages = 200  # 4,000 postings — far beyond any real board seen so far

    us_facet_id = _workday_us_facet_id(base)
    applied_facets = {"Location_Country": [us_facet_id]} if us_facet_id else {}

    results = []
    seen_ids: set[str] = set()
    offset = 0
    total = None
    for page in range(max_pages):
        if page:
            time.sleep(0.3)

        response = requests.post(
            f"{base}/jobs",
            json={"appliedFacets": applied_facets, "limit": limit, "offset": offset, "searchText": ""},
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        if total is None:
            total = data.get("total") or 0
        postings = data.get("jobPostings") or []

        hit_stale = False
        for job in postings:
            bullets = job.get("bulletFields") or []
            job_id = bullets[0] if bullets else ""
            posted = _parse_workday_relative_date(job.get("postedOn"), today)
            if job_id and job_id in seen_ids:
                continue
            if job_id:
                seen_ids.add(job_id)
            results.append(
                {
                    "job_id": job_id,
                    "title": job.get("title") or "",
                    "location": _workday_location(job.get("locationsText")),
                    "url": f"https://{tenant}.{wd}.myworkdayjobs.com/{site}{job.get('externalPath', '')}",
                    "posted_at": posted,
                }
            )
            if posted and posted < cutoff:
                hit_stale = True

        offset += limit
        if not postings or hit_stale or offset >= total:
            break

    return results


def _oracle_requisitions(host: str, finder: str) -> dict:
    response = requests.get(
        f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
        f"?onlyData=true&expand=requisitionList.secondaryLocations&finder=findReqs;{finder}",
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    items = response.json().get("items") or []
    return items[0] if items else {}


def _oracle_us_location_id(host: str, site: str) -> str | None:
    """This tenant's own location facet id for United States, or None. Like
    Workday, facet ids are per-tenant (JPMC's and AmEx's differ, confirmed
    live), so each scan looks it up with one cheap request. Failure here is
    never fatal: the caller falls back to an unfiltered search."""
    try:
        data = _oracle_requisitions(host, f"siteNumber={site},facetsList=LOCATIONS,limit=1")
    except requests.RequestException:
        return None
    for location in data.get("locationsFacet") or []:
        if location.get("Name") == "United States":
            return str(location.get("Id"))
    return None


def _list_oracle(token: str) -> list[dict]:
    """Oracle Recruiting Cloud (JPMC, American Express). Same two
    optimizations as Workday, both confirmed live: filtered to the tenant's
    United States location server-side, and sorted newest-first so paging
    stops at the first posting older than the cutoff. A board token's
    optional category ids (see parse_oracle_token) narrow it further —
    JPMC drops from ~900 US postings a week to ~65 with four categories.

    Secondary locations are folded into the location text, so a role whose
    primary location is elsewhere but which also lists New York still passes
    the location filter.
    """
    host, site, categories = parse_oracle_token(token)
    cutoff = date.today() - timedelta(days=POSTED_CUTOFF_DAYS)
    limit = 100
    max_pages = 50

    finder = f"siteNumber={site},sortBy=POSTING_DATES_DESC,limit={limit}"
    us_location_id = _oracle_us_location_id(host, site)
    if us_location_id:
        finder += f",locationId={us_location_id}"
    if categories:
        finder += f",selectedCategoriesFacet={categories}"

    results = []
    for page in range(max_pages):
        if page:
            time.sleep(0.3)
        data = _oracle_requisitions(host, f"{finder},offset={page * limit}")
        postings = data.get("requisitionList") or []

        hit_stale = False
        for job in postings:
            posted = None
            try:
                posted = date.fromisoformat(job.get("PostedDate") or "")
            except ValueError:
                pass
            locations = [job.get("PrimaryLocation") or ""] + [
                loc.get("Name") or "" for loc in job.get("secondaryLocations") or []
            ]
            results.append(
                {
                    "job_id": str(job.get("Id") or ""),
                    "title": job.get("Title") or "",
                    "location": "; ".join(loc for loc in locations if loc),
                    "url": oracle_job_url(host, site, str(job.get("Id") or "")),
                    "posted_at": posted,
                }
            )
            if posted and posted < cutoff:
                hit_stale = True

        if len(postings) < limit or hit_stale:
            break

    return results


LISTERS = {
    "greenhouse": _list_greenhouse,
    "ashby": _list_ashby,
    "lever": _list_lever,
    "workday": _list_workday,
    "oracle": _list_oracle,
}


def scan_companies(delay_seconds: float = 0.5) -> ScanReport:
    """Scan every enabled tracked company, sequentially.

    Sequential on purpose, same as description fetching: politeness towards
    APIs this app doesn't control, and one company's failure (a renamed board
    token, a board taken offline) never aborts the rest.
    """
    report = ScanReport()
    cutoff = date.today() - timedelta(days=POSTED_CUTOFF_DAYS)

    with session_scope() as session:
        # Extracted as plain tuples while the session is open — the ORM rows
        # themselves can't be touched once it closes.
        companies = [
            (c.company, c.source, c.board_token)
            for c in session.execute(
                select(TrackedCompany).where(TrackedCompany.enabled.is_(True))
            ).scalars()
        ]

    for index, (company, source, board_token) in enumerate(companies):
        if index:
            time.sleep(delay_seconds)

        lister = LISTERS.get(source)
        if lister is None:
            report.companies_failed[company] = f"unknown source: {source}"
            continue

        try:
            jobs = lister(board_token)
        except requests.RequestException as exc:
            report.companies_failed[company] = str(exc)
            continue
        except Exception as exc:  # one bad board never aborts the scan
            report.companies_failed[company] = f"unexpected error: {exc}"
            continue

        report.companies_scanned += 1

        for job in jobs:
            if not job["job_id"] or not job["title"]:
                continue
            if not _passes_filter(job["title"], job["location"], job["posted_at"], cutoff):
                continue
            report.candidates.append(
                Candidate(
                    source=source,
                    job_id=job["job_id"],
                    board_token=board_token,
                    title=job["title"],
                    company=company,
                    location=job["location"],
                    url=job["url"],
                    posted_at=job["posted_at"].isoformat() if job["posted_at"] else None,
                )
            )

    return report


def list_companies() -> list[dict]:
    with session_scope() as session:
        rows = session.execute(
            select(TrackedCompany).order_by(TrackedCompany.company)
        ).scalars().all()
        return [
            {
                "id": c.id,
                "company": c.company,
                "source": c.source,
                "board_token": c.board_token,
                "enabled": c.enabled,
            }
            for c in rows
        ]


def add_company(company: str, source: str, board_token: str) -> dict:
    if source not in ATS_SOURCES:
        raise ValueError(f"unknown source: {source}")

    with session_scope() as session:
        # A duplicate (source, board_token) would scan the same board twice
        # and produce duplicate candidates in the results table.
        existing = session.execute(
            select(TrackedCompany).where(
                TrackedCompany.source == source, TrackedCompany.board_token == board_token
            )
        ).scalar_one_or_none()
        if existing:
            raise ValueError(
                f"{source}/{board_token} is already tracked as {existing.company!r}"
            )

        row = TrackedCompany(company=company, source=source, board_token=board_token)
        session.add(row)
        session.flush()
        return {"id": row.id, "company": row.company, "source": row.source}


def remove_company(company_id: int) -> bool:
    with session_scope() as session:
        row = session.get(TrackedCompany, company_id)
        if row is None:
            return False
        session.delete(row)
        return True


def set_company_enabled(company_id: int, enabled: bool) -> dict | None:
    with session_scope() as session:
        row = session.get(TrackedCompany, company_id)
        if row is None:
            return None
        row.enabled = enabled
        session.flush()
        return {"id": row.id, "enabled": row.enabled}


def resolve_job_context(source: str, companies: list[str]) -> dict[str, str]:
    """company -> board_token, for the given source. Used to hand the right
    board tokens to a JobDescriptionSource before it fetches."""
    if not companies:
        return {}
    with session_scope() as session:
        rows = session.execute(
            select(TrackedCompany.company, TrackedCompany.board_token).where(
                TrackedCompany.source == source, TrackedCompany.company.in_(companies)
            )
        ).all()
        return {company: token for company, token in rows}
