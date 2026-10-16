"""Pin every test run to the fictional example profile.

Set before any app module is imported, so app.config resolves the same
profile in the private repo (which has a real profile/) and in a public
checkout (which does not) — tests behave identically in both. At backend/
so it also applies to the private tests under profile/tests/.
"""

import os
from pathlib import Path

# setdefault, so a deliberate run against another profile is still possible:
#   JOB_BOARD_PROFILE=profile pytest tests/test_something.py
os.environ.setdefault("JOB_BOARD_PROFILE", str(Path(__file__).resolve().parent / "profile.example"))
