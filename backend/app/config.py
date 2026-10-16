"""Runtime configuration.

USE_FIXTURES controls which email source the API serves from. It stays on
until Gmail OAuth is set up (see README), so the dashboard is fully usable
before any Google Cloud work happens.
"""

import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# The candidate this instance serves. Everything personal — the evaluator
# rubric, the ICP resume prompt, the salary floor, target locations — lives in
# backend/profile/, never in code. A checkout without one (the public demo)
# falls back to profile.example/, a fictional candidate, so the app and the
# tests run unchanged. JOB_BOARD_PROFILE overrides both (tests pin the example).
PROFILE_DIR = Path(
    os.getenv("JOB_BOARD_PROFILE")
    or (BASE_DIR / "profile" if (BASE_DIR / "profile").is_dir() else BASE_DIR / "profile.example")
)
PROFILE = json.loads((PROFILE_DIR / "settings.json").read_text(encoding="utf-8"))
SALARY_FLOOR: int = PROFILE["salary_floor"]
TARGET_LOCATIONS: list[str] = PROFILE["locations"]


def _load_env_file(path: Path) -> None:
    """Read KEY=VALUE lines into the environment, if the file exists.

    Secrets live in ~/.config/job-board/ rather than the repo, and the app
    reads them itself so that starting the backend never depends on having
    sourced something first — a forgotten `source` looks like a broken
    normalizer, which is a bad way to spend an afternoon.

    Real environment variables win. Exporting a key for one run should override
    the file rather than be silently ignored.
    """
    if not path.exists():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        # Tolerate quotes, since an editor or a copied snippet may add them.
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


SECRETS_DIR = Path(os.getenv("JOB_BOARD_SECRETS_DIR", Path.home() / ".config" / "job-board"))

# Must run before anything below reads os.getenv.
_load_env_file(SECRETS_DIR / ".env")

USE_FIXTURES = os.getenv("USE_FIXTURES", "1") == "1"

# Credentials live outside the repo so they cannot be committed by accident and
# do not ride along in a copy or backup of the project directory.
#
# Downloaded from Google Cloud Console; see README.
GMAIL_CREDENTIALS_PATH = Path(
    os.getenv("GMAIL_CREDENTIALS_PATH", SECRETS_DIR / "credentials.json")
)
# Written automatically after the first OAuth consent. This one is the live
# credential — it grants read access to the mailbox until revoked.
GMAIL_TOKEN_PATH = Path(os.getenv("GMAIL_TOKEN_PATH", SECRETS_DIR / "token.json"))

# Stored job descriptions. Lives beside the app, gitignored.
DB_PATH = Path(os.getenv("JOB_BOARD_DB", BASE_DIR / "jobs.db"))

# Model for normalizing job descriptions. Extraction, not judgement, so the
# cheapest capable model is the right one — about $0.006 per description.
NORMALIZER_MODEL = os.getenv("NORMALIZER_MODEL", "claude-haiku-4-5")

# Which prompt file under data/prompts/normalizer/ to run. Stamped onto every
# normalized row, same reasoning as EVALUATOR_RUBRIC_VERSION.
NORMALIZER_PROMPT_VERSION = os.getenv("NORMALIZER_PROMPT_VERSION", "v3")

# Which prompt under the profile's prompts/resume/ to run. Same reasoning as
# EVALUATOR_RUBRIC_VERSION — version control was built in before the first
# real generation, not retrofitted after, the way the normalizer's had to be.
RESUME_PROMPT_VERSION = os.getenv("RESUME_PROMPT_VERSION", PROFILE["resume_prompt_version"])

# Model for evaluating a role against the rubric. Starting on Haiku: the rubric
# states every scale explicitly, so the model reads a scale and picks a number
# rather than deriving anything. Roughly $0.006 per role. Raise it to Opus if
# the sub-scores turn out to need more judgement than that.
EVALUATOR_MODEL = os.getenv("EVALUATOR_MODEL", "claude-haiku-4-5")

# Model for writing ICP resume bullets. Raised to Sonnet after a pilot found
# Haiku couldn't hold two simultaneous numeric/selection constraints at once
# (include exactly 2 of 3 minor experiences, summing to 5 bullets) — it
# consistently satisfied one at the expense of the other, while Sonnet held
# both across both test postings.
RESUME_MODEL = os.getenv("RESUME_MODEL", "claude-sonnet-5")

# Model for the Resume Assembler agent itself. Piloted on Sonnet (two real
# runs passed, $0.17 and $0.39), then moved to Haiku to cut cost. Unlike the
# ICP resume — where Haiku failed to hold two numeric constraints at once —
# the assembler's hard rules are enforced by the harness, not the prompt, so
# the model only has to judge which line is stronger. Set back to
# claude-sonnet-5 if Haiku's swaps turn out weaker.
ASSEMBLER_MODEL = os.getenv("ASSEMBLER_MODEL", "claude-haiku-4-5")
ASSEMBLER_PROMPT_VERSION = os.getenv("ASSEMBLER_PROMPT_VERSION", "v1")

# Caps for one run. A "round" is one distinct draft sent to the scanners; a
# "turn" is one call to the assembler model. The cost ceiling is the backstop
# over both. Whichever hits first ends the run as hit_cap. Raised from 3/20
# once prompt caching cut a 10-turn Haiku run to ~$0.08; a full 30-turn run
# is estimated at $0.25-0.30, still under the unchanged cost cap.
ASSEMBLER_MAX_ROUNDS = int(os.getenv("ASSEMBLER_MAX_ROUNDS", "5"))
ASSEMBLER_MAX_TURNS = int(os.getenv("ASSEMBLER_MAX_TURNS", "30"))
ASSEMBLER_MAX_COST_USD = float(os.getenv("ASSEMBLER_MAX_COST_USD", "0.50"))
# Output limit per assembler turn. At 2048, Haiku's long pre-move analysis
# hit the limit mid-sentence on 3 of its first 9 runs.
ASSEMBLER_MAX_TOKENS = int(os.getenv("ASSEMBLER_MAX_TOKENS", "4096"))

# Model for the Resume Assembler's two prompted scanners and the ATS criteria
# they share. Each is a bounded, structured judgement (a checklist, a pairwise
# pick) rather than open-ended writing, and a single run can call them
# several times — the cheapest capable model fits. The hard gate is code.
SCANNER_MODEL = os.getenv("SCANNER_MODEL", "claude-haiku-4-5")

# Prompt versions for each scanner, under data/prompts/{kind}/. Stamped onto
# every assembly run, same reasoning as EVALUATOR_RUBRIC_VERSION.
ATS_CRITERIA_PROMPT_VERSION = os.getenv("ATS_CRITERIA_PROMPT_VERSION", "v1")
ATS_SCANNER_PROMPT_VERSION = os.getenv("ATS_SCANNER_PROMPT_VERSION", "v1")
RECRUITER_SCANNER_PROMPT_VERSION = os.getenv("RECRUITER_SCANNER_PROMPT_VERSION", "v2")

# Which rubric under the profile's prompts/evaluator/ to run. Stamped onto
# every evaluation row, because a rubric change makes old verdicts
# incomparable.
EVALUATOR_RUBRIC_VERSION = os.getenv("EVALUATOR_RUBRIC_VERSION", PROFILE["evaluator_rubric_version"])

# Searched in order: the profile's own prompts (the candidate-specific ones —
# evaluator, ICP resume) first, then the shared, non-personal ones.
PROMPT_DIRS = [PROFILE_DIR / "prompts", BASE_DIR / "data" / "prompts"]

FRONTEND_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

# Bullet Bank tag suggester: proposes tags for experience bullets from each
# tag's definition. Matching a sentence to a definition is a reading task,
# so the cheapest model; ~$0.05 for every bullet in the bank.
BULLET_TAGGER_MODEL = os.getenv("BULLET_TAGGER_MODEL", "claude-haiku-4-5")
BULLET_TAGGER_PROMPT_VERSION = os.getenv("BULLET_TAGGER_PROMPT_VERSION", "v1")
