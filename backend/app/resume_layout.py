"""The candidate's resume layout, from the profile's resume_layout.json.

What the resume parser needs to recognize a section (each employer's anchor
text, and for an employer with several roles the employment years that tell
them apart; each school's anchor), what each section is called (a short label
for the UI, a longer employer-context line for the scanners), which sections
count as experience, the print order, and the PDF filename pattern.

Personal, so it lives in the profile rather than in code — see config.py.
Validated on load: a layout that names a slot it never defines fails here,
at startup, rather than by misfiling a resume later.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from app import config

# Slots the parser itself creates from generic headings ("PROFESSIONAL
# SUMMARY", "ADDITIONAL DATA"), so every layout must define them.
REQUIRED_SLOTS = ("summary", "additional")


class ResumeLayoutError(ValueError):
    pass


@dataclass(frozen=True)
class ResumeLayout:
    filename_re: re.Pattern
    filename_example: str
    # Employers in the order their anchors are tried, each with its roles.
    employers: list[dict]
    education_anchors: dict[str, str]
    slot_display_order: list[str]
    slot_labels: dict[str, str]
    slot_context: dict[str, str]
    non_experience_slots: frozenset[str]


def load(path: Path) -> ResumeLayout:
    """Read and validate one resume_layout.json."""
    layout = json.loads(path.read_text(encoding="utf-8"))
    defined = [s["slot"] for s in layout["slots"]]
    if len(set(defined)) != len(defined):
        raise ResumeLayoutError(f"{path}: a slot is defined twice")
    named = [r["slot"] for e in layout["employers"] for r in e["roles"]] + [e["slot"] for e in layout["education"]]
    missing = [s for s in [*named, *REQUIRED_SLOTS] if s not in defined]
    if missing:
        raise ResumeLayoutError(f"{path}: slots used but not defined under 'slots': {missing}")
    for employer in layout["employers"]:
        roles = employer["roles"]
        dated = [r for r in roles if r.get("years")]
        if len(roles) > 1 and len(dated) != len(roles):
            raise ResumeLayoutError(f"{path}: {employer['anchor']!r} has several roles, so each needs 'years'")
    return ResumeLayout(
        filename_re=re.compile(layout["filename_pattern"]),
        filename_example=layout["filename_example"],
        employers=layout["employers"],
        education_anchors={e["anchor"]: e["slot"] for e in layout["education"]},
        slot_display_order=defined,
        slot_labels={s["slot"]: s["label"] for s in layout["slots"]},
        slot_context={s["slot"]: s["context"] for s in layout["slots"]},
        non_experience_slots=frozenset(s["slot"] for s in layout["slots"] if not s["experience"]),
    )


# The active profile's layout, used everywhere unless a caller passes another
# (the real-PDF tests do: they parse the owner's resumes with the owner's
# layout even though the rest of the suite runs on the example profile).
DEFAULT = load(config.PROFILE_DIR / "resume_layout.json")

FILENAME_RE = DEFAULT.filename_re
FILENAME_EXAMPLE = DEFAULT.filename_example
EMPLOYERS = DEFAULT.employers
EDUCATION_ANCHORS = DEFAULT.education_anchors
SLOT_DISPLAY_ORDER = DEFAULT.slot_display_order
SLOT_LABELS = DEFAULT.slot_labels
SLOT_CONTEXT = DEFAULT.slot_context
NON_EXPERIENCE_SLOTS = DEFAULT.non_experience_slots
