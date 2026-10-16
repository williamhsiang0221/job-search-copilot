"""JD lookalike scoring: how similar is a job to what has already been applied to.

Compares a job's Responsibilities and Qualifications embeddings against every
past application that has its own embeddings, using cosine similarity after
mean-centering — raw cosine similarity on job-posting text compresses toward 1
regardless of role, because postings share so much boilerplate genre ("own the
roadmap", "partner cross-functionally") that it dominates the actual content.
Centering removes that shared component so the comparison reflects what is
actually distinctive about each posting.

Centered on a *balanced* mean — the average of each role category's own mean,
not a plain average of every application — so a category you have applied to
far more than others (in practice, Product Manager) does not define "generic"
for everyone else. Verified against the real data before this was built: see
BACKLOG.md.

Scores shown and combined are standardized (z-scores against the corpus'
own mean/stdev for that field), not raw cosine similarity — confirmed live
that the two fields cluster in different, narrow raw ranges for the same
query (responsibilities ~0.24-0.36, qualifications ~0.34-0.49), which would
both make the numbers hard to read at a glance (everything densely packed
near the top of a 0-1 scale) and make qualifications quietly dominate any
combination of the two, for no reason connected to actual relevance.
Standardizing turns each into "how many standard deviations above this
job's own average match," which is comparable across fields and spreads the
numbers out meaningfully.

Recomputed fresh on every call rather than cached or stored: the center and
the ranking both depend on the full set of applications with embeddings, which
changes every time a new application is added. At this scale (tens of rows)
the entire computation is sub-millisecond pure Python — cheaper to redo than
to keep correctly invalidated.
"""

from __future__ import annotations

import math
from collections import defaultdict

from app.db import session_scope
from app.models import Application, JobNormalized

# Below this many applications, a role category's own mean is too noisy to
# trust as a stable "generic" baseline for that category — surfaced to the
# caller rather than silently treated as equally reliable.
THIN_CATEGORY_THRESHOLD = 5

FIELDS = ("responsibilities", "qualifications")

# Equal by default — Responsibilities-similarity ("same kind of day-to-day
# work") and Qualifications-similarity ("does my background match") both
# matter for deciding whether to apply and which resume to use, and neither
# has as clear a reason to dominate as score_1/score_2 did in the evaluator.
OVERALL_WEIGHTS = {"responsibilities": 0.5, "qualifications": 0.5}


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _norm(a: list[float]) -> float:
    return math.sqrt(_dot(a, a))


def _cosine(a: list[float], b: list[float]) -> float:
    na, nb = _norm(a), _norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return _dot(a, b) / (na * nb)


def _subtract(a: list[float], b: list[float]) -> list[float]:
    return [x - y for x, y in zip(a, b)]


def _mean_vector(vectors: list[list[float]]) -> list[float]:
    n = len(vectors)
    dims = len(vectors[0])
    return [sum(v[d] for v in vectors) / n for d in range(dims)]


def _balanced_mean(vectors_by_role: dict[str, list[list[float]]]) -> list[float]:
    """Average of the per-category means, each category weighted equally
    regardless of how many times that role has been applied to."""
    category_means = [_mean_vector(vs) for vs in vectors_by_role.values()]
    return _mean_vector(category_means)


def _zscore_all(values: list[float]) -> list[float]:
    """Each value's distance from this list's own mean, in standard
    deviations. A zero-variance list (every value identical — only possible
    with a handful of rows) has nothing to standardize against, so every
    value gets 0 rather than dividing by zero."""
    n = len(values)
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / n
    stdev = math.sqrt(variance)
    if stdev == 0:
        return [0.0] * n
    return [(v - mean) / stdev for v in values]


def _corpus() -> list[dict]:
    """Every application with a job_id/source link and its own embeddings."""
    with session_scope() as session:
        apps = (
            session.query(Application)
            .filter(Application.job_id.isnot(None), Application.source.isnot(None))
            .all()
        )
        rows = []
        for a in apps:
            normalized = session.get(JobNormalized, (a.source, a.job_id))
            if normalized is None:
                continue
            if normalized.responsibilities_embedding is None or normalized.qualifications_embedding is None:
                continue
            rows.append(
                {
                    "application_id": a.id,
                    "source": a.source,
                    "job_id": a.job_id,
                    "company": a.company,
                    "title": a.title,
                    "role": a.role or "Unknown",
                    "status": a.status,
                    "highest_round": a.highest_round,
                    "responsibilities": normalized.responsibilities_embedding,
                    "qualifications": normalized.qualifications_embedding,
                }
            )
        return rows


def find_similar_applications(source: str, job_id: str, top_n: int = 5) -> dict:
    """Top-N most similar past applications, ranked separately for
    Responsibilities and Qualifications, plus a combined Overall ranking,
    with the outcome shown alongside each match.

    Returns {"responsibilities": [...], "qualifications": [...],
    "overall": [...], "thin_categories": [...]}. Every list is empty if the
    query job has no embeddings yet, or if there is no comparable history at
    all. Every score shown is a z-score against this corpus, not raw cosine
    similarity — see the module docstring for why.
    """
    with session_scope() as session:
        query_normalized = session.get(JobNormalized, (source, job_id))
        if query_normalized is None or query_normalized.responsibilities_embedding is None:
            query_embeddings = None
        else:
            # Extracted while the session is still open — the object itself
            # cannot be used after this block, since session_scope closes and
            # expires it on exit.
            query_embeddings = {
                "responsibilities": query_normalized.responsibilities_embedding,
                "qualifications": query_normalized.qualifications_embedding,
            }

    if query_embeddings is None:
        return {"responsibilities": [], "qualifications": [], "overall": [], "thin_categories": []}

    corpus = _corpus()
    # Exclude the query itself if it happens to already be a linked application.
    corpus = [row for row in corpus if not (row["source"] == source and row["job_id"] == job_id)]

    if not corpus:
        return {"responsibilities": [], "qualifications": [], "overall": [], "thin_categories": []}

    role_counts: dict[str, int] = defaultdict(int)
    for row in corpus:
        role_counts[row["role"]] += 1
    thin_categories = sorted(role for role, count in role_counts.items() if count < THIN_CATEGORY_THRESHOLD)

    # Raw cosine similarity per field, for every corpus row — kept separate
    # from ranking/display so both can be standardized before either happens.
    z_by_field: dict[str, list[float]] = {}
    for field in FIELDS:
        vectors_by_role: dict[str, list[list[float]]] = defaultdict(list)
        for row in corpus:
            vectors_by_role[row["role"]].append(row[field])

        mu = _balanced_mean(vectors_by_role)
        query_centered = _subtract(query_embeddings[field], mu)

        raw_scores = [_cosine(query_centered, _subtract(row[field], mu)) for row in corpus]
        z_by_field[field] = _zscore_all(raw_scores)

    def top_matches(scores: list[float]) -> list[dict]:
        ranked = sorted(zip(scores, corpus), key=lambda pair: pair[0], reverse=True)
        return [
            {
                "application_id": row["application_id"],
                "company": row["company"],
                "title": row["title"],
                "role": row["role"],
                "status": row["status"],
                "highest_round": row["highest_round"],
                "score": round(z, 4),
            }
            for z, row in ranked[:top_n]
        ]

    result: dict[str, list] = {"thin_categories": thin_categories}
    for field in FIELDS:
        result[field] = top_matches(z_by_field[field])

    overall_scores = [
        sum(OVERALL_WEIGHTS[field] * z_by_field[field][i] for field in FIELDS)
        for i in range(len(corpus))
    ]
    result["overall"] = top_matches(overall_scores)

    return result
