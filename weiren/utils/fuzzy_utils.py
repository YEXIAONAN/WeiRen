from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from rapidfuzz import fuzz


@dataclass(slots=True)
class FuzzyMatch:
    text: str
    score: float
    payload: object | None = None


def composite_similarity(left: str, right: str) -> float:
    """Combine several RapidFuzz scorers into a single stable score."""
    left_text = (left or "").strip()
    right_text = (right or "").strip()
    if not left_text or not right_text:
        return 0.0

    scores = [
        float(fuzz.ratio(left_text, right_text)),
        float(fuzz.partial_ratio(left_text, right_text)),
        float(fuzz.token_sort_ratio(left_text, right_text)),
        float(fuzz.token_set_ratio(left_text, right_text)),
    ]
    return round((scores[0] * 0.30) + (scores[1] * 0.35) + (scores[2] * 0.15) + (scores[3] * 0.20), 2)


def best_similarity(text: str, candidates: Iterable[str]) -> float:
    best = 0.0
    for candidate in candidates:
        score = composite_similarity(text, candidate)
        if score > best:
            best = score
    return best


def rank_similar_texts(
    query: str,
    entries: Sequence[tuple[str, object]],
    extra_queries: Sequence[str] | None = None,
    limit: int = 8,
    threshold: float = 35.0,
) -> list[FuzzyMatch]:
    prompts = [query.strip()]
    if extra_queries:
        prompts.extend(item.strip() for item in extra_queries if item and item.strip())

    matches: list[FuzzyMatch] = []
    for text, payload in entries:
        content = (text or "").strip()
        if not content:
            continue
        score = best_similarity(content, prompts)
        if score < threshold:
            continue
        matches.append(FuzzyMatch(text=content, score=score, payload=payload))

    matches.sort(key=lambda item: item.score, reverse=True)
    return matches[:limit]
