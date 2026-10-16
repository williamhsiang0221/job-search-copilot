# Setup

How to run the app, connect Gmail, and what to know about security. For what
the project is and why, see the [README](README.md).

## Try the demo first

The demo runs the whole app on a fictional candidate's job search — no API
keys, no Gmail, no cost:

```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && cd ..
cd frontend && npm install && cd ..
backend/demo/run_demo.sh        # builds backend/demo.db, then serves it
```

Open http://localhost:5174. Everything model-generated in the demo database
was produced by the app's own code running against a scripted model (see
`backend/demo/seed_demo.py`).

## Your own profile

Everything about the candidate — the evaluator rubric, the ICP resume
prompt, salary floor, target locations, and how their resume PDFs are laid
out — lives in `backend/profile/`. Without one, the app runs on
`backend/profile.example/` (a fictional candidate). Copy that folder to
`backend/profile/` and edit it to make the app yours.

## Running it


Two processes. Backend:

```bash
cd backend && .venv/bin/python -m uvicorn app.main:app --port 8000 --reload
```

Frontend:

```bash
cd frontend && npm run dev
```

Then open http://localhost:5173. Vite proxies `/api` to port 8000.

Out of the box it serves **sample data** from `backend/fixtures/` (real emails,
saved to disk) so the dashboard works before Gmail is connected. A "Sample data"
chip shows when that's what you're looking at.

## Connecting Gmail

This follows Google's official Python quickstart —
<https://developers.google.com/workspace/gmail/api/quickstart/python> — with the
same packages and the same credential handling. If you ever want to check this
project's setup against the source of truth, that page is it.


Capture reads mail with the `gmail.readonly` scope — it cannot send, delete, or
modify anything.

1. Go to the [Google Cloud Console](https://console.cloud.google.com/) and create
   a project (any name).
2. **APIs & Services → Library** → search "Gmail API" → **Enable**.
3. **APIs & Services → OAuth consent screen** → choose **External** → fill in the
   required name/email fields → under **Test users**, add your own Gmail address.
   (Leaving the app unpublished is fine; test users can still authorize it.)
4. **APIs & Services → Credentials → Create credentials → OAuth client ID** →
   application type **Desktop app**.
5. Download the JSON and save it as `~/.config/job-board/credentials.json`:

   ```bash
   mkdir -p ~/.config/job-board && chmod 700 ~/.config/job-board
   mv ~/Downloads/client_secret_*.apps.googleusercontent.com.json ~/.config/job-board/credentials.json
   chmod 600 ~/.config/job-board/credentials.json
   ```

6. Authorize once, from the `backend` directory:

   ```bash
   .venv/bin/python authorize.py
   ```

7. Start the backend with fixtures off:

   ```bash
   USE_FIXTURES=0 .venv/bin/python -m uvicorn app.main:app --port 8000
   ```

Consent is a separate CLI step on purpose. Running the OAuth handshake inside
the capture request blocks a request thread and prints its authorization URL to
the server's stdout, which shows up in the dashboard as a spinner that never
resolves. `authorize.py` puts that interaction in a terminal you're looking at.

Running `authorize.py` opens a browser consent screen.

Two things to expect there:

- **"Google hasn't verified this app"** — that is your own app. Click **Advanced**
  → **Go to (your app name) (unsafe)** to continue.
- **Consent fails unless your address is a test user** (step 3). Easy to skip.

After you approve, the token is cached in `backend/token.json` and refreshes
itself.

### If capture starts asking for consent every week

Google expires refresh tokens after 7 days while an OAuth app's publishing status
is **Testing**. Capture handles this — it discards the dead token and re-runs
consent instead of erroring — but you'll be clicking through the screen weekly.

To stop it, go to **APIs & Services → OAuth consent screen** and set publishing
status to **In production**. For a personal, single-user app this needs no
verification review; you'll still see the unverified-app warning at consent, and
the token stops expiring.

### Where the credentials live, and which one matters

Both files sit in `~/.config/job-board/`, outside the repo, so they can't be
committed by accident or ride along in a copy of the project directory. Override
with `JOB_BOARD_SECRETS_DIR` if you want them elsewhere.

| File | What it is | Sensitivity |
|---|---|---|
| `credentials.json` | Desktop OAuth client id + secret | **Low.** Google does not treat a Desktop client secret as confidential — an installed app can't hide it from whoever runs it. Security comes from the consent screen and the localhost redirect. |
| `token.json` | Access + refresh token, written after consent | **High.** This is a live credential: it reads your mail until revoked. |

There's no value in moving these into a `.env` — `google-auth` wants a file path,
and the risk was never the file format. It's whether the file is in git and who
can read it on disk. Both are `chmod 600` in a `chmod 700` directory.

To revoke access at any time: [myaccount.google.com/permissions](https://myaccount.google.com/permissions)
→ find the app → Remove access. Then delete `token.json`.

## How the parser works

LinkedIn sends a plaintext alternative alongside the HTML body, and it is much
more stable than the markup — so the parser never touches HTML or the DOM. Each
job appears as a dash-separated block:

```
Senior Product Manager, Notifications
Duolingo
New York, NY
Fast growing                                  <- optional badge lines
View job: https://www.linkedin.com/comm/jobs/view/4459031392/?trackingId=...
```

Two details the parser has to get right, both covered by tests:

- **The first block also contains the email header** ("Your job alert for martech
  in New York"). Taking the first three lines of each block would put the header
  in row one.
- **Badge lines vary** in count and position ("Top applicant", "1 school alum",
  "Apply with resume & profile"), sometimes with a blank line before them and
  sometimes not.

So fields are read *backward* from the `View job:` line by contiguous line-group,
which handles both without a hardcoded list of badge strings LinkedIn can add to.

Tracking parameters are stripped: the ~900-character alert URL becomes
`https://www.linkedin.com/jobs/view/<id>/`, which resolves to the same posting.

### Senders

Both LinkedIn job senders are read, and they share the same plaintext layout:

| Sender | What it is |
|---|---|
| `jobalerts-noreply@linkedin.com` | Your saved-search alerts |
| `jobs-noreply@linkedin.com` | LinkedIn's recommendations and saved-job nudges |

To capture only your own saved searches, drop the second entry from
`LINKEDIN_SENDERS` in `backend/app/sources.py`.

### Date ranges

Presets are **calendar days**, not rolling 24-hour windows — so "Yesterday" means
yesterday, not 24-48 hours ago. "Past 3 days" is today plus the two prior days.

## Security notes

- **The API has no authentication** and binds to `127.0.0.1`. That's fine for a
  local tool. Do not start it with `--host 0.0.0.0`: anything on your network
  could then read your captured roles without a credential.
- **CORS** allows only `localhost:5173`, GET only.
- **The scope is `gmail.readonly`.** Capture cannot send, delete, or modify mail.
- **Fixtures are sanitized.** They came from real alert emails; names, `midToken`,
  `savedSearchId`, `refId`, and `trackingId` values were replaced with
  same-shaped fakes. Keep it that way if you add fixtures — the parser only
  depends on structure, so real values buy nothing and would publish your
  account identifiers.

## Tests

```bash
cd backend && .venv/bin/python -m pytest -q
```

Parser tests run against the saved real emails in `fixtures/`, so they exercise
the actual format rather than a synthetic one.

## Layout

```
backend/
  app/                FastAPI app: capture, job boards, normalizer, evaluator,
                      applications, resume storage, Resume Assembler, Bullet Bank
  data/prompts/       versioned prompts shared by every candidate
  profile.example/    a fictional candidate's profile (rubric, layout, settings)
  demo/               the demo database: content, seed script, runner
  fixtures/           sanitized LinkedIn alert emails for tests and sample mode
  tests/
frontend/
  src/components/     one view per sidebar page
  scripts/            README screenshots, captured from the demo
```

