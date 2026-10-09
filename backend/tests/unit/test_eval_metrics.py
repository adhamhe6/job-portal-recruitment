"""Ranking metrics (hand-computed) and the offline evaluation of the production ranker."""

from __future__ import annotations

import math

import pytest

from app.matching.eval import dataset as ds
from app.matching.eval import metrics as M
from app.matching.eval.__main__ import evaluate

GRADES = {"a": 3, "b": 2, "c": 1, "d": 0}


def test_precision_at_k() -> None:
    assert M.precision_at_k(["a", "x", "b"], GRADES, 3) == pytest.approx(2 / 3)
    assert (
        M.precision_at_k(["c", "d", "x"], GRADES, 3) == 0.0
    )  # grade 1 is below the relevance threshold of 2
    assert M.precision_at_k(["c", "d", "x"], GRADES, 3, threshold=1) == pytest.approx(1 / 3)
    assert M.precision_at_k(["a"], GRADES, 5) == pytest.approx(
        1 / 5
    )  # k is the denominator even for short rankings
    assert M.precision_at_k(["a", "b"], GRADES, 0) == 0.0


def test_recall_at_k() -> None:
    assert M.recall_at_k(["a", "x", "y"], GRADES, 3) == 0.5  # relevant = {a, b}
    assert M.recall_at_k(["a", "b"], GRADES, 1) == 0.5
    assert M.recall_at_k(["a", "b"], GRADES, 2) == 1.0
    assert M.recall_at_k(["a"], {"a": 1}, 5) == 0.0  # nobody is relevant at threshold 2


def test_dcg_matches_the_formula() -> None:
    expected = (2**3 - 1) / math.log2(2) + (2**2 - 1) / math.log2(3) + 0 + (2**1 - 1) / math.log2(5)
    assert M.dcg([3, 2, 0, 1]) == pytest.approx(expected)
    assert M.dcg([]) == 0.0


def test_ndcg_perfect_ranking_is_one() -> None:
    assert M.ndcg_at_k(["a", "b", "c", "d"], GRADES, 4) == pytest.approx(1.0)
    assert M.ndcg_at_k(["a", "b", "c"], GRADES, 2) == pytest.approx(1.0)


def test_ndcg_imperfect_ranking_by_hand() -> None:
    ideal = (2**3 - 1) / math.log2(2) + (2**2 - 1) / math.log2(3)
    got = (2**2 - 1) / math.log2(2) + (2**3 - 1) / math.log2(3)  # b before a
    assert M.ndcg_at_k(["b", "a"], GRADES, 2) == pytest.approx(got / ideal)
    assert M.ndcg_at_k(["b", "a"], GRADES, 2) < 1.0


def test_ndcg_with_no_relevant_documents_or_unknown_ids() -> None:
    assert M.ndcg_at_k(["a"], {}, 3) == 0.0
    assert M.ndcg_at_k(["a"], {"a": 0}, 3) == 0.0
    assert M.ndcg_at_k(["x", "y"], GRADES, 2) == 0.0


def test_reciprocal_rank() -> None:
    assert M.reciprocal_rank(["a", "b"], GRADES) == 1.0
    assert M.reciprocal_rank(["c", "d", "b"], GRADES) == pytest.approx(1 / 3)
    assert M.reciprocal_rank(["c", "d"], GRADES) == 0.0


def test_average_precision() -> None:
    # relevant = {a, b}; ranking a, x, b -> precision at hits: 1/1 and 2/3 -> mean over |relevant|
    assert M.average_precision(["a", "x", "b"], GRADES) == pytest.approx((1 + 2 / 3) / 2)
    assert M.average_precision(["x", "y"], GRADES) == 0.0
    assert M.average_precision(["a"], GRADES) == pytest.approx(0.5)  # b was never retrieved
    assert M.average_precision(["a"], {}) == 0.0


def test_dataset_is_well_formed() -> None:
    jobs, cands = ds.all_jobs(), ds.all_candidates()
    assert len(jobs) == 12 and len(cands) == 16
    for job_key, grades in ds.LABELS.items():
        assert job_key in jobs
        assert set(grades) <= set(cands), f"unknown candidate in labels for {job_key}"
        assert all(g in (1, 2, 3) for g in grades.values())


@pytest.fixture(scope="module")
def report() -> dict:
    return evaluate()


def test_production_hybrid_beats_the_random_baseline(report: dict) -> None:
    results = report["results"]
    hybrid = next(v for k, v in results.items() if k.startswith("Hybrid score"))
    random_ = next(v for k, v in results.items() if k.startswith("Random"))
    for metric in ("P@1", "P@3", "R@3", "NDCG@5", "MRR", "MAP"):
        assert hybrid[metric] > random_[metric] + 0.1, metric
    assert hybrid["NDCG@5"] > random_["NDCG@5"] + 0.5


def test_production_hybrid_ndcg_at_5_meets_the_quality_bar(report: dict) -> None:
    hybrid = next(v for k, v in report["results"].items() if k.startswith("Hybrid score"))
    assert hybrid["NDCG@5"] >= 0.9
    assert hybrid["MRR"] >= 0.9
    assert hybrid["P@1"] >= 0.9


def test_hybrid_is_at_least_as_good_as_every_single_signal_baseline(report: dict) -> None:
    results = report["results"]
    hybrid = next(v for k, v in results.items() if k.startswith("Hybrid score"))
    for name in ("Keyword TF-IDF cosine", "Exact skill overlap"):
        assert hybrid["NDCG@5"] >= results[name]["NDCG@5"], name


def test_evaluation_covers_all_evaluable_jobs(report: dict) -> None:
    assert report["n_jobs"] == sum(1 for g in ds.LABELS.values() if any(v >= 2 for v in g.values())) == 12
    assert report["n_candidates"] == 16
    assert report["n_labels"] == sum(len(v) for v in ds.LABELS.values())


def test_cosine_distribution_orders_by_human_grade(report: dict) -> None:
    mean = {grade: stats[0] for grade, stats in report["cos_stats"].items()}
    assert mean[3] > mean[2] > mean[1] > mean[0], mean


def test_evaluation_is_deterministic() -> None:
    first, second = evaluate(), evaluate()
    assert first["results"] == second["results"]
    assert first["per_job"] == second["per_job"]
