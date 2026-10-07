"""``python -m app.matching.eval [--write docs/matching-evaluation.md]`` — evaluate rankers on the labelled set.

Compares the production hybrid scorer with simpler baselines so the value of each component is measurable rather than asserted.
Nothing here is hard-coded: every number in the report is computed by this script from the dataset and the embedding model.
"""

from __future__ import annotations

import argparse
import math
import random
import re
import statistics
from collections import Counter
from collections.abc import Callable
from datetime import date

import numpy as np

from app.matching.embedder import get_embedder
from app.matching.eval import dataset as ds
from app.matching.eval import metrics as M
from app.matching.representation import CandidateFeatures, JobFeatures, embed_components_sync
from app.matching.scoring import (
    COSINE_HIGH,
    COSINE_LOW,
    MATCHING_VERSION,
    WEIGHTS,
    score_pair,
    skill_coverage,
)

TOKEN = re.compile(r"[a-z0-9+#.]{2,}")
Ranker = Callable[[str, JobFeatures, dict[str, CandidateFeatures]], list[str]]


def _text(components: dict[str, str]) -> str:
    return " ".join(components.values()).lower()


def _vecs(
    jobs: dict[str, JobFeatures], cands: dict[str, CandidateFeatures]
) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    emb = get_embedder()
    return (
        {k: embed_components_sync(j.components(), emb) for k, j in jobs.items()},
        {k: embed_components_sync(c.components(), emb) for k, c in cands.items()},
    )


def evaluate() -> dict:
    jobs, cands = ds.all_jobs(), ds.all_candidates()
    jv, cv = _vecs(jobs, cands)

    # TF-IDF baseline (fit on the same corpus)
    docs = {("j", k): _text(j.components()) for k, j in jobs.items()} | {
        ("c", k): _text(c.components()) for k, c in cands.items()
    }
    tok = {k: TOKEN.findall(v) for k, v in docs.items()}
    df = Counter(t for ts in tok.values() for t in set(ts))
    n = len(docs)
    idf = {t: math.log((1 + n) / (1 + d)) + 1 for t, d in df.items()}

    def tfidf(key: tuple[str, str]) -> dict[str, float]:
        c = Counter(tok[key])
        v = {t: (1 + math.log(f)) * idf[t] for t, f in c.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {t: x / norm for t, x in v.items()}

    tf = {k: tfidf(k) for k in docs}

    def tfidf_cos(jk: str, ck: str) -> float:
        a, b = tf[("j", jk)], tf[("c", ck)]
        return sum(w * b.get(t, 0.0) for t, w in a.items())

    def rank(scores: dict[str, float]) -> list[str]:
        return [c for c, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))]

    rng = random.Random(7)

    def skills_exact(jk: str, ck: str) -> float:
        j, c = jobs[jk], cands[ck]
        want = {s.skill_id for s in j.required} | {s.skill_id for s in j.preferred}
        have = {s.skill_id for s in c.skills}
        return len(want & have) / len(want) if want else 0.0

    rankers: dict[str, Callable[[str], list[str]]] = {
        "Random order (floor, mean of 200 shuffles)": lambda jk: [],  # handled specially
        "Keyword TF-IDF cosine": lambda jk: rank({ck: tfidf_cos(jk, ck) for ck in cands}),
        "Exact skill overlap": lambda jk: rank({ck: skills_exact(jk, ck) for ck in cands}),
        "Embedding cosine only": lambda jk: rank({ck: float(np.dot(jv[jk], cv[ck])) for ck in cands}),
        "Skill coverage (+related credit)": lambda jk: rank(
            {
                ck: (
                    (skill_coverage(jobs[jk].required, cands[ck].skills).score or 0) * 0.75
                    + (skill_coverage(jobs[jk].preferred, cands[ck].skills).score or 0) * 0.25
                )
                for ck in cands
            }
        ),
        f"Hybrid score (production, {MATCHING_VERSION})": lambda jk: rank(
            {ck: score_pair(jobs[jk], cands[ck], float(np.dot(jv[jk], cv[ck]))).overall for ck in cands}
        ),
    }

    ks = (1, 3, 5)
    results: dict[str, dict[str, float]] = {}
    per_job: dict[str, dict[str, list[str]]] = {}
    evaluable = [jk for jk, g in ds.LABELS.items() if any(v >= 2 for v in g.values())]
    for name, fn in rankers.items():
        agg: dict[str, list[float]] = (
            {f"P@{k}": [] for k in ks} | {f"R@{k}": [] for k in ks} | {"NDCG@5": [], "MRR": [], "MAP": []}
        )
        for jk in evaluable:
            g = ds.LABELS[jk]
            if name.startswith("Random"):
                vals: dict[str, list[float]] = {m: [] for m in agg}
                for _ in range(200):
                    order = list(cands)
                    rng.shuffle(order)
                    for k in ks:
                        vals[f"P@{k}"].append(M.precision_at_k(order, g, k))
                        vals[f"R@{k}"].append(M.recall_at_k(order, g, k))
                    vals["NDCG@5"].append(M.ndcg_at_k(order, g, 5))
                    vals["MRR"].append(M.reciprocal_rank(order, g))
                    vals["MAP"].append(M.average_precision(order, g))
                for m in agg:
                    agg[m].append(statistics.fmean(vals[m]))
                continue
            order = fn(jk)
            per_job.setdefault(name, {})[jk] = order
            for k in ks:
                agg[f"P@{k}"].append(M.precision_at_k(order, g, k))
                agg[f"R@{k}"].append(M.recall_at_k(order, g, k))
            agg["NDCG@5"].append(M.ndcg_at_k(order, g, 5))
            agg["MRR"].append(M.reciprocal_rank(order, g))
            agg["MAP"].append(M.average_precision(order, g))
        results[name] = {m: statistics.fmean(v) for m, v in agg.items()}

    # Cosine distribution by grade → justification for the calibration anchors
    by_grade: dict[int, list[float]] = {0: [], 1: [], 2: [], 3: []}
    for jk, g in ds.LABELS.items():
        for ck in cands:
            by_grade[g.get(ck, 0)].append(float(np.dot(jv[jk], cv[ck])))
    cos_stats = {gr: (statistics.fmean(v), min(v), max(v), len(v)) for gr, v in by_grade.items() if v}
    return {
        "results": results,
        "per_job": per_job,
        "cos_stats": cos_stats,
        "n_jobs": len(evaluable),
        "n_candidates": len(cands),
        "n_labels": sum(len(v) for v in ds.LABELS.values()),
    }


def render(report: dict) -> str:
    emb = get_embedder()
    lines = [
        "# Matching evaluation",
        "",
        "> Generated by `python -m app.matching.eval` — **do not edit by hand**. Every number below is computed from the labelled dataset "
        "in `backend/app/matching/eval/dataset.py` and the embedding model, on the date shown.",
        "",
        f"* Date: {date.today().isoformat()}  ·  embedding model: `{emb.name}` ({emb.version}, {emb.dim}-d)  ·  matching version: `{MATCHING_VERSION}`",
        f"* Evaluated jobs: {report['n_jobs']} (those with ≥1 candidate labelled ≥ 2)  ·  candidates: {report['n_candidates']}  ·  graded judgements listed: {report['n_labels']} "
        "(unlisted pairs = grade 0)",
        "* Relevant for P@K / R@K / MRR / MAP = grade ≥ 2. NDCG uses graded gains 2^g − 1.",
        "",
        "## Ranking quality (mean over jobs)",
        "",
        "| Method | P@1 | P@3 | R@3 | R@5 | NDCG@5 | MRR | MAP |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, r in report["results"].items():
        lines.append(
            f"| {name} | {r['P@1']:.2f} | {r['P@3']:.2f} | {r['R@3']:.2f} | {r['R@5']:.2f} | {r['NDCG@5']:.2f} | {r['MRR']:.2f} | {r['MAP']:.2f} |"
        )
    lines += [
        "",
        "## Raw cosine similarity by human grade (job text vs. candidate text)",
        "",
        "| Grade | mean | min | max | pairs |",
        "|---|---|---|---|---|",
    ]
    names = {0: "0 unrelated", 1: "1 adjacent", 2: "2 plausible", 3: "3 strong"}
    for gr, (mean, lo, hi, n) in sorted(report["cos_stats"].items()):
        lines.append(f"| {names[gr]} | {mean:.2f} | {lo:.2f} | {hi:.2f} | {n} |")
    lines += [
        "",
        f"Calibration used by the scorer: `semantic = clip((cosine − {COSINE_LOW}) / ({COSINE_HIGH} − {COSINE_LOW}), 0, 1)`. "
        "It is a monotone rescale, so it cannot change an embedding-only ranking; it only controls how semantic similarity mixes with the other components.",
        "",
        f"Component weights: {', '.join(f'{k} {v:.2f}' for k, v in WEIGHTS.items())}.",
        "",
        "## Top-3 per job (hybrid score)",
        "",
        "| Job | Top 3 (grade) |",
        "|---|---|",
    ]
    hybrid = next(k for k in report["per_job"] if k.startswith("Hybrid"))
    for jk, order in report["per_job"][hybrid].items():
        g = ds.LABELS[jk]
        lines.append(f"| {jk} | " + ", ".join(f"{c} ({g.get(c, 0)})" for c in order[:3]) + " |")
    lines += [
        "",
        "## How to read this honestly",
        "",
        "* The dataset is small (synthetic profiles, hand-labelled by the team that built the system), so the numbers are optimistic and "
        "indicate *sensible behaviour*, not real-world accuracy.",
        "* The comparison shows what each ingredient buys: keyword matching misses synonyms/adjacency, exact skill overlap ignores related skills "
        "and seniority, embeddings alone ignore hard requirements; the hybrid combines them and explains the result.",
        "* No protected attribute (name, gender, age, nationality, photo …) is an input to any method; the labels judge job-relevant qualifications only. "
        "Fairness across demographic groups has **not** been measured and would need real, consented data.",
        "* The score ranks candidates for human review; it is not a hiring decision.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", help="write the markdown report to this path")
    args = parser.parse_args()
    text = render(evaluate())
    if args.write:
        with open(args.write, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"wrote {args.write}")
    else:
        print(text)


if __name__ == "__main__":
    main()
