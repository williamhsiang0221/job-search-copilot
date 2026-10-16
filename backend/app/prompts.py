"""Loading versioned prompt files off disk.

Shared by every prompted workflow — each keeps its own reasoning about *what*
to prompt and *which exception* to raise on failure; this is only the *how* of
finding and reading the right file. A kind lives either in the profile
(candidate-specific: the evaluator rubric, the ICP resume prompt) or in
data/prompts/ (everything else); see config.PROMPT_DIRS.
"""

from __future__ import annotations

from functools import lru_cache

from app import config


class PromptUnavailable(RuntimeError):
    """No prompt file at the requested kind/version."""


@lru_cache(maxsize=32)
def load_prompt(kind: str, version: str) -> str:
    """Read a prompt version off disk. Cached — it does not change at runtime."""
    for directory in config.PROMPT_DIRS:
        path = directory / kind / f"{version}.md"
        if path.is_file():
            return path.read_text(encoding="utf-8")
    raise PromptUnavailable(f"no {kind} prompt {version} under {[str(d) for d in config.PROMPT_DIRS]}")


def available_versions(kind: str) -> list[str]:
    """Every version on disk for this kind, alphabetical."""
    versions = {p.stem for d in config.PROMPT_DIRS if (d / kind).is_dir() for p in (d / kind).glob("*.md")}
    return sorted(versions)
