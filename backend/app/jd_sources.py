"""Fetching job descriptions from a posting source.

One class per source behind a shared interface (JobDescriptionSource):
Greenhouse, Ashby, Lever, Workday and Oracle here, all public job-board APIs.
LinkedIn's lives in app/linkedin_guest.py, kept separate because it uses an
undocumented guest endpoint and is optional — see jobs_service.
"""

from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable, Protocol

import requests
from bs4 import BeautifulSoup

# Anything older than a week collapses to a single bucket. LinkedIn stops being
# specific past that point anyway, and a reposted listing's date says when it
# was reposted, not when the role opened.
STALE_BUCKET_DAYS = 30


class JobDescriptionError(RuntimeError):
    """A single job could not be fetched. Never fatal to a batch."""


@dataclass
class FetchedJob:
    source: str
    job_id: str
    title: str
    company: str
    location: str = ""
    url: str = ""
    apply_url: str | None = None
    posted_at: date | None = None
    posted_at_is_approximate: bool = False
    description_raw: str = ""
    level_raw: str | None = None
    employment_type_raw: str | None = None
    workplace_raw: str | None = None
    department: str | None = None
    team: str | None = None
    job_function: str | None = None
    industries: str | None = None
    salary_text: str | None = None


class JobDescriptionSource(Protocol):
    name: str

    def fetch(self, job_id: str) -> FetchedJob: ...


def resolve_posted_at(relative: str, today: date | None = None) -> tuple[date | None, bool]:
    """Turn LinkedIn's relative posting text into an absolute date.

    LinkedIn only ever says "1 day ago" or "2 weeks ago", so the date is
    derived rather than stated — the caller gets a flag saying so. Anything
    beyond a week, and anything reposted, lands in a single bucket rather than
    pretending to a precision the wording does not carry.
    """
    today = today or date.today()
    if not relative:
        return None, True

    text = relative.strip().lower()

    if "repost" in text:
        return today - timedelta(days=STALE_BUCKET_DAYS), True

    match = re.search(r"(\d+)\s*(minute|hour|day|week|month|year)", text)
    if not match:
        return today - timedelta(days=STALE_BUCKET_DAYS), True

    amount, unit = int(match.group(1)), match.group(2)

    if unit in ("minute", "hour"):
        return today - timedelta(days=1), True
    if unit == "day":
        return today - timedelta(days=min(amount, STALE_BUCKET_DAYS)), True
    if unit == "week" and amount == 1:
        return today - timedelta(days=7), True

    return today - timedelta(days=STALE_BUCKET_DAYS), True


def _strip_html(raw: str) -> str:
    if not raw:
        return ""
    soup = BeautifulSoup(html.unescape(raw), "lxml")
    return soup.get_text("\n", strip=True)


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def _parse_epoch_ms(value) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000).date()
    except (ValueError, OSError, OverflowError):
        return None


SALARY_PATTERN = re.compile(
    r"\$[\d,]{2,}(?:\.\d+)?\s*(?:K|k)?\s*(?:-|to|–|—)\s*\$?[\d,]{2,}(?:\.\d+)?\s*(?:K|k)?"
)


def _extract_salary_text(*texts: str | None) -> str | None:
    """A last-resort regex over free text. No board exposes pay as a clean
    structured field on its public listing endpoint, so this is all there is."""
    for text in texts:
        if not text:
            continue
        match = SALARY_PATTERN.search(text)
        if match:
            return match.group(0)
    return None


def _normalize_workplace(raw: str | None) -> str | None:
    """Case-fold a board's own workplace vocabulary onto the normalizer's
    enum. This is still the board's stated value, not an inference — just
    spelled consistently (Ashby says "OnSite", Lever says "onsite")."""
    if not raw:
        return None
    value = raw.strip().lower().replace("-", "").replace(" ", "")
    if value in ("onsite", "office"):
        return "onsite"
    if value == "remote":
        return "remote"
    if value == "hybrid":
        return "hybrid"
    return None


class GreenhouseSource:
    """Greenhouse's public job-board API.

    The list endpoint (used by the scan step) omits descriptions unless
    `?content=true` is passed — but that flag applies to the whole list at
    once, so a company with hundreds of postings would balloon into one huge
    response. The per-job endpoint used here already includes full `content`
    by default, so fetching only the selected jobs individually avoids that
    entirely.
    """

    name = "greenhouse"

    def __init__(
        self,
        job_tokens: dict[str, str] | None = None,
        session: requests.Session | None = None,
        timeout: int = 25,
    ):
        self.job_tokens = job_tokens or {}
        self.session = session or requests.Session()
        self.timeout = timeout

    def fetch(self, job_id: str) -> FetchedJob:
        token = self.job_tokens.get(job_id)
        if not token:
            raise JobDescriptionError(f"no board token known for job {job_id}")

        url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{job_id}"
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise JobDescriptionError(f"could not reach Greenhouse: {exc}") from exc

        return self._parse(job_id, response.json())

    def _parse(self, job_id: str, data: dict) -> FetchedJob:
        title = data.get("title") or ""
        if not title:
            raise JobDescriptionError("posting has no title — expired or unavailable")

        departments = data.get("departments") or []
        offices = data.get("offices") or []
        apply_url = data.get("absolute_url") or ""

        return FetchedJob(
            source=self.name,
            job_id=job_id,
            title=title,
            # Greenhouse's own company_name is trusted here, unlike Ashby/Lever
            # below — the board API states it directly, so there's no need to
            # fall back to what was typed into Manage companies.
            company=data.get("company_name") or "",
            location=(data.get("location") or {}).get("name") or "",
            url=apply_url,
            apply_url=apply_url or None,
            posted_at=_parse_iso_date(data.get("first_published")),
            posted_at_is_approximate=False,
            description_raw=_strip_html(data.get("content") or ""),
            department=departments[0]["name"] if departments else None,
            team=offices[0]["name"] if offices else None,
            # Not exposed on Greenhouse's board API at all, structured or not.
            salary_text=None,
        )


class AshbySource:
    """Ashby's public job-board API.

    Unlike Greenhouse, the list endpoint already returns full description text
    for every job — there is no lighter "list only" mode to fall back to, so
    the scan step's title/location filter is what keeps volume down, not a
    cheaper first request. Fetching here re-requests that same list and picks
    out the one job wanted, rather than introducing a cache between the two
    steps.
    """

    name = "ashby"

    def __init__(
        self,
        job_tokens: dict[str, str] | None = None,
        job_companies: dict[str, str] | None = None,
        session: requests.Session | None = None,
        timeout: int = 25,
    ):
        self.job_tokens = job_tokens or {}
        self.job_companies = job_companies or {}
        self.session = session or requests.Session()
        self.timeout = timeout

    def fetch(self, job_id: str) -> FetchedJob:
        token = self.job_tokens.get(job_id)
        if not token:
            raise JobDescriptionError(f"no board token known for job {job_id}")

        url = f"https://api.ashbyhq.com/posting-api/job-board/{token}"
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise JobDescriptionError(f"could not reach Ashby: {exc}") from exc

        jobs = response.json().get("jobs") or []
        data = next((j for j in jobs if str(j.get("id")) == job_id), None)
        if data is None:
            raise JobDescriptionError("posting no longer listed on this board")

        return self._parse(job_id, data)

    def _parse(self, job_id: str, data: dict) -> FetchedJob:
        title = data.get("title") or ""
        if not title:
            raise JobDescriptionError("posting has no title")

        compensation = data.get("compensation") or {}
        salary_text = (
            data.get("compensationTierSummary")
            or compensation.get("summary")
            or _extract_salary_text(data.get("descriptionPlain"))
        )

        return FetchedJob(
            source=self.name,
            job_id=job_id,
            title=title,
            # Ashby's list has no company field of its own — a job is only
            # ever reached through a specific company's board, so the name
            # comes from Manage companies rather than the posting itself.
            company=self.job_companies.get(job_id, ""),
            location=data.get("location") or "",
            url=data.get("jobUrl") or "",
            apply_url=data.get("applyUrl"),
            posted_at=_parse_iso_date(data.get("publishedAt")),
            posted_at_is_approximate=False,
            description_raw=data.get("descriptionPlain") or "",
            employment_type_raw=data.get("employmentType"),
            workplace_raw=_normalize_workplace(data.get("workplaceType")),
            department=data.get("department"),
            team=data.get("team"),
            salary_text=salary_text,
        )


class LeverSource:
    """Lever's public postings API.

    Like Ashby, the list response already carries the full description — split
    across several fields (an opening paragraph, a body, and labeled bullet
    sections) that need concatenating into one string for the normalizer.
    """

    name = "lever"

    def __init__(
        self,
        job_tokens: dict[str, str] | None = None,
        job_companies: dict[str, str] | None = None,
        session: requests.Session | None = None,
        timeout: int = 25,
    ):
        self.job_tokens = job_tokens or {}
        self.job_companies = job_companies or {}
        self.session = session or requests.Session()
        self.timeout = timeout

    def fetch(self, job_id: str) -> FetchedJob:
        token = self.job_tokens.get(job_id)
        if not token:
            raise JobDescriptionError(f"no board token known for job {job_id}")

        url = f"https://api.lever.co/v0/postings/{token}?mode=json"
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise JobDescriptionError(f"could not reach Lever: {exc}") from exc

        postings = response.json() or []
        data = next((p for p in postings if str(p.get("id")) == job_id), None)
        if data is None:
            raise JobDescriptionError("posting no longer listed on this board")

        return self._parse(job_id, data)

    def _description(self, data: dict) -> str:
        parts: list[str] = []
        seen: set[str] = set()

        def add(text: str | None) -> None:
            text = (text or "").strip()
            if text and text not in seen:
                seen.add(text)
                parts.append(text)

        # openingPlain and descriptionPlain are frequently identical; `seen`
        # collapses the duplicate rather than repeating it in the output.
        add(data.get("descriptionPlain") or data.get("openingPlain"))
        add(data.get("descriptionBodyPlain"))
        for section in data.get("lists") or []:
            heading = (section.get("text") or "").strip()
            body = _strip_html(section.get("content") or "")
            add(f"{heading}\n{body}".strip() if heading else body)
        add(data.get("additionalPlain"))

        return "\n\n".join(parts)

    def _parse(self, job_id: str, data: dict) -> FetchedJob:
        title = data.get("text") or ""
        if not title:
            raise JobDescriptionError("posting has no title")

        categories = data.get("categories") or {}
        salary_range = data.get("salaryRange") or {}
        salary_text = None
        if salary_range:
            salary_text = (
                f"{salary_range.get('min', '')}-{salary_range.get('max', '')} "
                f"{salary_range.get('currency', '')}"
            ).strip()
        if not salary_text:
            salary_text = _extract_salary_text(
                data.get("additionalPlain"), data.get("descriptionPlain")
            )

        return FetchedJob(
            source=self.name,
            job_id=job_id,
            # Same reasoning as Ashby: Lever's postings carry no company field,
            # since a job is only ever reached via one company's board.
            company=self.job_companies.get(job_id, ""),
            title=title,
            location=categories.get("location") or "",
            url=data.get("hostedUrl") or "",
            apply_url=data.get("applyUrl"),
            posted_at=_parse_epoch_ms(data.get("createdAt")),
            posted_at_is_approximate=False,
            description_raw=self._description(data),
            employment_type_raw=categories.get("commitment"),
            workplace_raw=_normalize_workplace(data.get("workplaceType")),
            department=categories.get("department"),
            team=categories.get("team"),
            salary_text=salary_text,
        )


class WorkdaySource:
    """Workday's CXS API — a shared multi-tenant platform, like Greenhouse/
    Ashby/Lever, just with a three-part identifier instead of one slug.

    board_token encodes all three pieces the URL needs as one delimited
    string: "{tenant}/{wd_number}/{site}" — e.g. "nba/wd108/nbacareers". The
    site segment must have any locale prefix stripped (a browser URL like
    "ms.wd5.myworkdayjobs.com/en-US/External" calls its API at ".../External",
    not ".../en-US/External" — confirmed live, the locale-prefixed path 405s).

    No numeric job id is stable across a whole board's pagination, so unlike
    Greenhouse this does not fetch by URL directly: it searches by the
    requisition id (an exact, cheap match regardless of how large the board
    is) to find the one posting's externalPath, then fetches that.
    """

    name = "workday"

    def __init__(
        self,
        job_tokens: dict[str, str] | None = None,
        job_companies: dict[str, str] | None = None,
        session: requests.Session | None = None,
        timeout: int = 25,
    ):
        self.job_tokens = job_tokens or {}
        self.job_companies = job_companies or {}
        self.session = session or requests.Session()
        self.timeout = timeout

    def fetch(self, job_id: str) -> FetchedJob:
        token = self.job_tokens.get(job_id)
        if not token:
            raise JobDescriptionError(f"no board token known for job {job_id}")
        tenant, wd, site = token.split("/", 2)
        base = f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}"

        try:
            search = self.session.post(
                f"{base}/jobs",
                json={"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": job_id},
                timeout=self.timeout,
            )
            search.raise_for_status()
        except requests.RequestException as exc:
            raise JobDescriptionError(f"could not reach Workday: {exc}") from exc

        postings = search.json().get("jobPostings") or []
        match = next((p for p in postings if job_id in (p.get("bulletFields") or [])), None)
        if match is None:
            raise JobDescriptionError("posting no longer listed on this board")

        try:
            detail = self.session.get(f"{base}{match['externalPath']}", timeout=self.timeout)
            detail.raise_for_status()
        except requests.RequestException as exc:
            raise JobDescriptionError(f"could not reach Workday: {exc}") from exc

        return self._parse(job_id, detail.json().get("jobPostingInfo") or {})

    def _parse(self, job_id: str, data: dict) -> FetchedJob:
        title = data.get("title") or ""
        if not title:
            raise JobDescriptionError("posting has no title")

        return FetchedJob(
            source=self.name,
            job_id=job_id,
            # Same reasoning as Ashby/Lever: reached only via one company's
            # board, and Workday's own postings carry no company field.
            company=self.job_companies.get(job_id, ""),
            title=title,
            location=data.get("location") or "",
            url=data.get("externalUrl") or "",
            apply_url=data.get("externalUrl") or None,
            posted_at=_parse_iso_date(data.get("startDate")),
            posted_at_is_approximate=False,
            description_raw=_strip_html(data.get("jobDescription") or ""),
            employment_type_raw=data.get("timeType"),
            workplace_raw=_normalize_workplace(data.get("remoteType")),
            # Not exposed structurally — the normalizer already extracts
            # compensation straight from description text when it is stated,
            # confirmed against real postings before this was built.
            salary_text=None,
        )


def parse_oracle_token(token: str) -> tuple[str, str, str]:
    """Oracle board_token -> (host, site_number, category_ids).

    Format: "{host}/{site}" or "{host}/{site}/{id;id;...}", e.g.
    "jpmc.fa.oraclecloud.com/CX_1001/300000086251864;300000086153149". The
    optional third part is the board's own job-category facet ids, copied
    from a careers-page URL's selectedCategoriesFacet — a large board like
    JPMC posts ~900 US roles a week, so narrowing by category server-side
    matters more than on any other source.
    """
    parts = token.split("/", 2)
    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise ValueError(f"bad Oracle board token: {token!r}")
    return parts[0], parts[1], parts[2] if len(parts) == 3 else ""


def oracle_job_url(host: str, site: str, job_id: str) -> str:
    return f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{job_id}"


class OracleSource:
    """Oracle Recruiting Cloud's Candidate Experience REST API — a shared
    multi-tenant platform like Workday, identified by host + site number
    (see parse_oracle_token). Verified on JPMC and American Express.

    The description is split across up to three HTML fields (AmEx fills all
    three; JPMC puts everything in the first), concatenated here. The
    corporate and organization blurbs are skipped — they are the same
    company boilerplate on every posting.
    """

    name = "oracle"

    def __init__(
        self,
        job_tokens: dict[str, str] | None = None,
        job_companies: dict[str, str] | None = None,
        session: requests.Session | None = None,
        timeout: int = 25,
    ):
        self.job_tokens = job_tokens or {}
        self.job_companies = job_companies or {}
        self.session = session or requests.Session()
        self.timeout = timeout

    def fetch(self, job_id: str) -> FetchedJob:
        token = self.job_tokens.get(job_id)
        if not token:
            raise JobDescriptionError(f"no board token known for job {job_id}")
        host, site, _ = parse_oracle_token(token)

        url = (
            f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
            f'?expand=all&onlyData=true&finder=ById;Id="{job_id}",siteNumber={site}'
        )
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise JobDescriptionError(f"could not reach Oracle: {exc}") from exc

        items = response.json().get("items") or []
        if not items:
            raise JobDescriptionError("posting no longer listed on this board")
        return self._parse(job_id, host, site, items[0])

    def _parse(self, job_id: str, host: str, site: str, data: dict) -> FetchedJob:
        title = data.get("Title") or ""
        if not title:
            raise JobDescriptionError("posting has no title")

        description = "\n\n".join(
            text
            for text in (
                _strip_html(data.get(field) or "")
                for field in (
                    "ExternalDescriptionStr",
                    "ExternalResponsibilitiesStr",
                    "ExternalQualificationsStr",
                )
            )
            if text
        )

        # Pay sits in a tenant-defined flex field, labeled differently per
        # company ("Base Pay/Salary" at JPMC, "Salary Range" at AmEx).
        salary_text = next(
            (
                str(flex.get("Value"))
                for flex in data.get("requisitionFlexFields") or []
                if re.search(r"salary|pay", flex.get("Prompt") or "", re.I) and flex.get("Value")
            ),
            None,
        ) or _extract_salary_text(description)

        posted = data.get("ExternalPostedStartDate")
        return FetchedJob(
            source=self.name,
            job_id=job_id,
            # Same reasoning as Ashby/Lever/Workday: reached only via one
            # company's board, and the posting itself names no company.
            company=self.job_companies.get(job_id, ""),
            title=title,
            location=data.get("PrimaryLocation") or "",
            url=oracle_job_url(host, site, job_id),
            apply_url=oracle_job_url(host, site, job_id),
            posted_at=_parse_iso_date(posted),
            posted_at_is_approximate=False,
            description_raw=description,
            employment_type_raw=data.get("JobSchedule"),
            workplace_raw=_normalize_workplace(data.get("WorkplaceType")),
            department=data.get("Category") or data.get("JobFunction"),
            salary_text=salary_text,
        )


def fetch_many(
    source: JobDescriptionSource,
    job_ids: list[str],
    delay_seconds: float = 1.0,
    on_progress: Callable[[str], None] | None = None,
) -> tuple[list[FetchedJob], dict[str, str]]:
    """Fetch sequentially, pausing between requests.

    Deliberately not concurrent. These are undocumented guest endpoints, and
    firing a few hundred parallel requests is the reliable way to lose access
    to them. One failure never stops the batch.

    on_progress, if given, is called with each job_id right after its fetch
    attempt resolves (success or failure) — the hook a caller polls to show
    live "N of M" progress.
    """
    fetched: list[FetchedJob] = []
    failures: dict[str, str] = {}

    for index, job_id in enumerate(job_ids):
        if index:
            time.sleep(delay_seconds)
        try:
            fetched.append(source.fetch(job_id))
        except JobDescriptionError as exc:
            failures[job_id] = str(exc)
        except Exception as exc:  # never let one posting abort the rest
            failures[job_id] = f"unexpected error: {exc}"
        if on_progress:
            on_progress(job_id)

    return fetched, failures
