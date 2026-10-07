"""Guards the query shapes that the measured indexes depend on (see docs/performance.md)."""

from sqlalchemy.dialects import postgresql

from app.search.jobs import JobFilters, JobSort, build_job_query


def _sql(public: bool, **kw) -> str:
    stmt, _ = build_job_query(JobFilters(**kw), public=public)
    return str(stmt.compile(dialect=postgresql.dialect()))


def test_public_newest_ordering_matches_the_partial_index() -> None:
    """ix_jobs_published is `published_at DESC` (NULLS FIRST by default). Ordering with NULLS LAST cannot use it and forces a
    sort of every published row (measured: 60 ms instead of 2 ms on 18k published jobs)."""
    sql = _sql(True, sort=JobSort.NEWEST)
    order_by = sql.split("ORDER BY", 1)[1]
    assert "jobs.published_at DESC" in order_by
    assert "NULLS LAST" not in order_by.split("jobs.id")[0]


def test_keyword_search_uses_fts_and_trigram_operators() -> None:
    sql = _sql(True, q="python developer", sort=JobSort.RELEVANCE)
    assert "websearch_to_tsquery" in sql and "@@" in sql  # GIN full-text index
    assert "%%" in sql or " % " in sql  # pg_trgm similarity operator (typo tolerance)
