"""Embedding a normalized job's Responsibilities and Qualifications.

Two vectors per job, kept separate rather than concatenated: "same duties" and
"same required background" are different signals when deciding whether to
apply and which resume to use, and blending them into one vector would hide
which one a match is actually about.

Uses OpenAI's REST API directly via requests rather than the openai package —
this app has no other OpenAI dependency, and a raw POST is simpler than adding
a whole SDK for one endpoint.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import requests

EMBEDDING_MODEL = "text-embedding-3-small"
# Published rate, input tokens only — embeddings have no output tokens.
PRICE_PER_MTOK = 0.02


class EmbeddingUnavailable(RuntimeError):
    """No usable OpenAI credentials, or nothing to embed."""


NO_CREDENTIALS = (
    "no OpenAI credentials found. Set OPENAI_API_KEY. Stored descriptions and "
    "normalization are unaffected; only the embedding is skipped."
)


def price(tokens: int | None) -> float | None:
    if tokens is None:
        return None
    return round(tokens * PRICE_PER_MTOK / 1_000_000, 6)


def render_field(items: list[str]) -> str:
    """Bullet-rendered, same convention as evaluator.py's _render_job."""
    return "\n".join(f"- {item}" for item in items) if items else "- none stated"


@dataclass
class EmbeddingResult:
    responsibilities_embedding: list[float]
    qualifications_embedding: list[float]
    input_tokens: int | None
    cost_usd: float | None


def embed_texts(texts: list[str]) -> tuple[list[list[float]], int | None]:
    """One call, one batch. Callers needing many texts should batch and pace
    it themselves — this function does not, since normalize-time usage is
    always exactly two texts."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise EmbeddingUnavailable(NO_CREDENTIALS)

    response = requests.post(
        "https://api.openai.com/v1/embeddings",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": EMBEDDING_MODEL, "input": texts},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    vectors = [item["embedding"] for item in data["data"]]
    total_tokens = data.get("usage", {}).get("total_tokens")
    return vectors, total_tokens


def embed_normalized_job(responsibilities: list[str], qualifications: list[str]) -> EmbeddingResult:
    texts = [render_field(responsibilities), render_field(qualifications)]
    vectors, tokens = embed_texts(texts)
    return EmbeddingResult(
        responsibilities_embedding=vectors[0],
        qualifications_embedding=vectors[1],
        input_tokens=tokens,
        cost_usd=price(tokens),
    )
