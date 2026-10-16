"""Email sources for the capture workflow.

Two implementations behind one interface:

  FixtureSource - reads saved emails off disk. Needs no credentials, so the
                  whole pipeline is runnable and testable before Gmail OAuth
                  is set up.
  GmailSource   - the real thing, via the Gmail API with a read-only scope.

Which one runs is decided in config.py.
"""

from __future__ import annotations

import base64
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Protocol

# LinkedIn splits job mail across two senders. Both use the same plaintext
# layout, so the parser handles them identically.
#   jobalerts-noreply@ - saved-search alerts (the ones you configured)
#   jobs-noreply@      - LinkedIn's own recommendations and saved-job nudges
LINKEDIN_SENDERS = (
    "jobalerts-noreply@linkedin.com",
    "jobs-noreply@linkedin.com",
)

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


class NotAuthorizedError(RuntimeError):
    """Gmail has no usable token; the user must run authorize.py."""


class EmailSource(Protocol):
    def fetch(self, start: date, end: date) -> list[dict]:
        """Return message dicts with body/subject/received_at, inclusive of both dates."""
        ...


def build_query(start: date, end: date) -> str:
    """Gmail search query for LinkedIn job mail within an inclusive date range.

    Gmail's `before:` is exclusive, so the end date is bumped by a day to make
    the range inclusive on both ends the way the UI's dropdown implies.
    """
    senders = " OR ".join(f"from:{s}" for s in LINKEDIN_SENDERS)
    after = start.strftime("%Y/%m/%d")
    before = (end + timedelta(days=1)).strftime("%Y/%m/%d")
    return f"({senders}) after:{after} before:{before}"


class FixtureSource:
    """Serves saved emails, ignoring the date range."""

    def __init__(self, fixtures_dir: Path | None = None):
        self.fixtures_dir = fixtures_dir or Path(__file__).resolve().parent.parent / "fixtures"

    def fetch(self, start: date, end: date) -> list[dict]:
        messages = []
        for path in sorted(self.fixtures_dir.glob("*.txt")):
            messages.append(
                {
                    "body": path.read_text(encoding="utf-8"),
                    "subject": f"[fixture] {path.stem}",
                    "received_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        return messages


class GmailSource:
    """Reads LinkedIn job mail from Gmail, following Google's Python quickstart.

    https://developers.google.com/workspace/gmail/api/quickstart/python

    The one deliberate difference: this never runs the interactive consent flow.
    The quickstart is a CLI script, so doing consent inline is fine there. Here
    it would run inside a web request — blocking a request thread and printing
    its authorization URL to a terminal nobody is watching. Consent is a
    separate one-time step; see authorize.py.
    """

    def __init__(self, credentials_path: Path, token_path: Path):
        self.credentials_path = credentials_path
        self.token_path = token_path
        self._service = None

    def _build_service(self):
        # Checked before the Google imports so an unauthorized capture fails
        # fast with a message that says what to do.
        if not self.token_path.exists():
            raise NotAuthorizedError(
                "Gmail is not authorized yet. Run this once, from the backend "
                "directory:\n\n    .venv/bin/python authorize.py"
            )

        from google.auth.exceptions import RefreshError
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = Credentials.from_authorized_user_file(str(self.token_path), GMAIL_SCOPES)

        if not creds.valid:
            if creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    self.token_path.write_text(creds.to_json(), encoding="utf-8")
                except RefreshError as exc:
                    # Google expires refresh tokens after 7 days while the OAuth
                    # app's publishing status is "Testing".
                    raise NotAuthorizedError(
                        "Gmail authorization expired. Re-run:\n\n"
                        "    .venv/bin/python authorize.py\n\n"
                        "To stop this recurring, set the OAuth consent screen's "
                        "publishing status to 'In production'."
                    ) from exc
            else:
                raise NotAuthorizedError(
                    "Stored Gmail token is unusable. Re-run:\n\n"
                    "    .venv/bin/python authorize.py"
                )

        return build("gmail", "v1", credentials=creds)

    @property
    def service(self):
        if self._service is None:
            self._service = self._build_service()
        return self._service

    def fetch(self, start: date, end: date) -> list[dict]:
        query = build_query(start, end)
        api = self.service.users().messages()

        message_ids: list[str] = []
        request = api.list(userId="me", q=query, maxResults=100)
        while request is not None:
            response = request.execute()
            message_ids.extend(m["id"] for m in response.get("messages", []))
            request = api.list_next(request, response)

        messages = []
        for message_id in message_ids:
            raw = api.get(userId="me", id=message_id, format="full").execute()
            payload = raw.get("payload", {})
            body = _extract_plaintext(payload)
            if not body:
                continue
            headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
            messages.append(
                {
                    "body": body,
                    "subject": headers.get("subject", ""),
                    "received_at": normalize_date(headers.get("date", "")),
                }
            )
        return messages


def normalize_date(raw: str) -> str:
    """Turn an email Date header into a UTC ISO-8601 string.

    Headers arrive as "Wed, 26 Aug 2026 17:51:12 +0000" with varying offsets.
    Normalising to UTC ISO means the values sort correctly as plain strings,
    both when picking the most recent copy of a job and in the dashboard.
    Unparseable headers return "" rather than raising - a malformed date is not
    a reason to drop a job.
    """
    if not raw:
        return ""
    try:
        return parsedate_to_datetime(raw).astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        return ""


def _extract_plaintext(payload: dict) -> str:
    """Walk a MIME tree and return the first text/plain part, decoded."""
    if payload.get("mimeType") == "text/plain":
        data = payload.get("body", {}).get("data")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    for part in payload.get("parts", []):
        text = _extract_plaintext(part)
        if text:
            return text

    return ""
