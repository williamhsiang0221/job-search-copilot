#!/usr/bin/env python
"""One-time Gmail authorization.

Run this once from a terminal:

    .venv/bin/python authorize.py

It opens a browser for consent and writes the token. The API never runs this
flow itself — a blocking OAuth handshake inside a web request gives the
dashboard an endless spinner and prints its URL somewhere nobody is looking.
"""

import sys

from google_auth_oauthlib.flow import InstalledAppFlow

from app import config
from app.sources import GMAIL_SCOPES


def main() -> int:
    if not config.GMAIL_CREDENTIALS_PATH.exists():
        print(f"No credentials at {config.GMAIL_CREDENTIALS_PATH}", file=sys.stderr)
        print("Download the Desktop OAuth client JSON — see README.", file=sys.stderr)
        return 1

    if config.GMAIL_TOKEN_PATH.exists():
        answer = input(f"{config.GMAIL_TOKEN_PATH} already exists. Replace it? [y/N] ")
        if answer.strip().lower() not in {"y", "yes"}:
            print("Left the existing token alone.")
            return 0

    flow = InstalledAppFlow.from_client_secrets_file(
        str(config.GMAIL_CREDENTIALS_PATH), GMAIL_SCOPES
    )

    print("\nA browser window will open for Google consent.")
    print('You will see "Google hasn\'t verified this app" — that is this app.')
    print("Click Advanced, then \"Go to ... (unsafe)\".\n")
    print("If no browser opens, copy the URL printed below into one manually.\n")

    creds = flow.run_local_server(port=0, open_browser=True)

    config.GMAIL_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.GMAIL_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    config.GMAIL_TOKEN_PATH.chmod(0o600)

    print(f"\nAuthorized. Token written to {config.GMAIL_TOKEN_PATH}")
    print("Start the backend with USE_FIXTURES=0 and run a capture.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
