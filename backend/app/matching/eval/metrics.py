"""Ranking metrics. Pure functions over ``(ranked_ids, grades)``; grades are graded relevance judgements 0..3."""

from __future__ import annotations

import math
from collections.abc import Sequence


def precision_at_k(ranked: Sequence[str], grades: dict[str, int], k: int, threshold: int = 2) -> float:
    top = ranked[:k]
    return sum(1 for r in top if grades.get(r, 0) >= threshold) / k if k else 0.0


def recall_at_k(ranked: Sequence[str], grades: dict[str, int], k: int, threshold: int = 2) -> float:
    relevant = {c for c, g in grades.items() if g >= threshold}
    if not relevant:
        return 0.0
    return len(relevant & set(ranked[:k])) / len(relevant)


def dcg(gains: Sequence[float]) -> float:
    return sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(gains))


def ndcg_at_k(ranked: Sequence[str], grades: dict[str, int], k: int) -> float:
    ideal = dcg(sorted(grades.values(), reverse=True)[:k])
    if ideal == 0:
        return 0.0
    return dcg([grades.get(r, 0) for r in ranked[:k]]) / ideal


def reciprocal_rank(ranked: Sequence[str], grades: dict[str, int], threshold: int = 2) -> float:
    for i, r in enumerate(ranked, start=1):
        if grades.get(r, 0) >= threshold:
            return 1.0 / i
    return 0.0


def average_precision(ranked: Sequence[str], grades: dict[str, int], threshold: int = 2) -> float:
    relevant = {c for c, g in grades.items() if g >= threshold}
    if not relevant:
        return 0.0
    hits, total = 0, 0.0
    for i, r in enumerate(ranked, start=1):
        if r in relevant:
            hits += 1
            total += hits / i
    return total / len(relevant)
