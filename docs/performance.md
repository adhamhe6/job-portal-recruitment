# Performance notes

Everything here was **measured**, not assumed: the scripts live in `backend/scripts/perf/` and can be re-run.

* `generate_bulk.py` builds a synthetic dataset *inside PostgreSQL* (`generate_series`), with **real embeddings** computed from each row's own text.
* `explain.py` takes the **actual SQLAlchemy statements the API builds**, compiles them, and runs `EXPLAIN (ANALYZE, BUFFERS)`; each scenario is also run with the relevant index dropped inside a rolled-back transaction, to show what the index buys.

```bash
createdb talentlens_perf && DATABASE_URL=postgresql+asyncpg://…/talentlens_perf alembic upgrade head
DATABASE_URL=… PYTHONPATH=backend python -m app.scripts.bootstrap
DATABASE_URL=… PYTHONPATH=backend python backend/scripts/perf/generate_bulk.py --jobs 30000 --candidates 50000
DATABASE_URL=… PYTHONPATH=backend python backend/scripts/perf/explain.py
```

Environment: PostgreSQL 16.15 + pgvector 0.6.0, single local instance, 4 vCPU / 15 GB, default `shared_buffers`, data fully cached
(best of 3 runs). Dataset: **30 000 jobs (18 000 published), 180 000 job-skill rows, 50 000 candidates (≈ 90 % marketplace-visible),
350 000 candidate-skill rows, 150 000 applications**. Numbers are execution time of the page query (`LIMIT 20`) in milliseconds; they
show relative effects, not a production SLA.

## Results

| Scenario (real API query) | With index (ms) | Index dropped (ms) | Plan with index |
|---|---:|---:|---|
| Job search: keyword `python developer` (FTS + title trigram, relevance sort) | 14.9 | 91.4 | Bitmap Heap Scan on `jobs` (GIN `ix_jobs_search_tsv` ∪ `ix_jobs_title_trgm`) |
| Job search: typo `pyton developr` (trigram fallback) | 8.7 | 87.9 | Bitmap Heap Scan (GIN `ix_jobs_title_trgm`) |
| Job search: newest first, no keyword | **2.0** | 75.6 | Index Scan `ix_jobs_published` → Incremental Sort (partial index, `WHERE status='PUBLISHED'`) |
| Job search: skills ALL of {Python, PostgreSQL} | 0.6 | 19.9 | Nested Loop with `ix_job_skills_skill_job` |
| Job search: location contains `berlin` (ILIKE) | 12.2 | 61.7 | Bitmap Heap Scan (GIN `ix_jobs_location_trgm`) |
| Candidate search: keyword `kubernetes terraform` (FTS) | 0.7 | 585.7 | Bitmap Heap Scan (GIN `ix_candidate_profiles_search_tsv`) |
| Candidate search: skills ALL of {Python, PostgreSQL}, ≥ 3 yrs | 5.1 | 48.6 | Nested Loop / Index Scan (`ix_candidate_skills_skill_candidate`) |
| Candidate search: name fragment | 0.1 | 583.4 | Bitmap Heap Scan (GIN `ix_candidate_profiles_display_name_trgm`) |
| Vector retrieval: 300 nearest eligible candidates for a job | 5.1 | 122.2 | Index Scan (HNSW `ix_candidate_profiles_embedding_hnsw`, `hnsw.ef_search=200`) |
| Applications of one candidate, newest first | < 0.1 | 11.9 | Bitmap Index Scan (`ix_applications_candidate_applied`) |
| Dashboard: applications per status for a company | 1.0 | 0.9 | Aggregate over `ix_jobs_company_status` → `ix_applications_job_status` (index-only) |

Rows where the two numbers are equal (e.g. applications of one *job* by status, the dashboard aggregate) are honest "no change":
the data touched is small enough that another existing index or a scan does as well — the index is there for growth, not for this
dataset size, and it is cheap to keep.

## Findings that changed the code

1. **A one-word ordering bug cost 30×.** The first measurement of "newest first" took 60 ms with a sequential scan although a partial
   index `ix_jobs_published (published_at DESC) WHERE status='PUBLISHED'` existed. The query said `ORDER BY published_at DESC NULLS LAST`;
   a `DESC` index is `NULLS FIRST`, so the planner could not use it and sorted all 18 000 published rows. Published rows can never have
   a null `published_at`, so plain `DESC` is correct — **60.7 ms → 2.0–2.7 ms**. A unit test (`tests/unit/test_job_search_sql.py`)
   now pins the ordering so it cannot regress silently (it did regress once when two edits raced; the measurement caught it).
2. **Trigram + FTS together.** `websearch_to_tsquery` finds stems ("developer" ⇄ "developers") but not typos; `pg_trgm` covers typos and
   name fragments. They are OR'd in one `WHERE`, each served by its own GIN index (a `BitmapOr`), and ranking combines `ts_rank_cd` with
   `similarity()`. Without the GIN indexes candidate keyword and name search degrade to 0.6 s on 50 k rows — the indexes are not optional.
3. **pgvector with a SQL eligibility filter.** HNSW returns approximate neighbours *before* the `WHERE` filter, so a selective filter can
   return fewer rows than `LIMIT`. Retrieval therefore sets `hnsw.ef_search = 200` for the transaction and asks for 300 candidates,
   then re-scores them exactly; applicants are always added by a separate exact query so they can never be missed.
4. **Skills as a join table** (`job_skills`, `candidate_skills`) with a *reversed* composite index `(skill_id, job_id|candidate_id)`:
   "who has Python **and** PostgreSQL" becomes two index probes instead of a JSON/array scan.
5. **Pagination.** `LIMIT/OFFSET` with a separate `COUNT(*)` over the same filters. Deep offsets are bounded by `page ≤ 100 000` and
   `page_size ≤ 100`; for the data sizes here offset pagination is fine. If candidate search grew to millions of rows, keyset pagination
   on `(sort key, id)` would be the next step — not built, because it is not needed yet.

## Application-level performance

* **No N+1**: relationships are `lazy="raise"`, so any accidental lazy load fails loudly in tests; list endpoints load children with
  `selectinload` or a second `IN (…)` query for the page only. Match pages load candidate features for the *page* (≤ 100 rows) in
  batches.
* **Embeddings are not computed on read.** Recruiter pages read persisted `candidate_job_matches`. Embedding a document with the bundled
  model takes well under a millisecond (200 embeds ≈ 9 ms), so the cost that matters is database round trips, not inference.
* **Matching a job** scores ≤ 300 retrieved candidates plus applicants with pure-Python scoring (no I/O per pair) and upserts them in
  chunks of 500; the nightly sweep queues one deduplicated task per published job.
* **Caching** (Redis, namespace-versioned; see `architecture.md` §11): anonymous job search (60 s), skill autocomplete (10 min),
  candidate recommendations (5 min), dashboards. Personalised responses are not cached in the shared namespace. A circuit breaker avoids
  paying the Redis connect timeout on every request during an outage.
* **Connection pool**: 10 + 10 overflow per API process, `pool_pre_ping`; the worker uses its own pool.

## What was *not* optimised (deliberately)

* No materialised views or read replicas: aggregates are index-backed and cached; nothing measured was slow enough to justify them.
* No sharding / partitioning of `candidate_job_matches`: it holds at most (retrieval limit × live jobs) rows.
* HNSW parameters (`m=16`, `ef_construction=64`) are pgvector defaults; recall was not tuned because retrieval is followed by exact
  scoring of a generous candidate set, and the evaluation shows no ranking loss on the labelled data.
