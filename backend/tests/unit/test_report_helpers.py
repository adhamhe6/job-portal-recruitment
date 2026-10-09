"""Pure helpers of the reports module: CSV rendering, date windows and time buckets."""

from __future__ import annotations

from datetime import date

import pytest

from app.core.errors import ValidationFailure
from app.services.reports import (
    MAX_BUCKETS,
    Table,
    Window,
    bucket_starts,
    csv_cell,
    make_window,
    pick_granularity,
    render_csv,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("=1+1", "'=1+1"),
        ("+SUM(A1)", "'+SUM(A1)"),
        ("-2+3", "'-2+3"),
        ("@cmd", "'@cmd"),
        ("\t=1", "'\t=1"),
        ("\r=1", "'\r=1"),
        ("  =HYPERLINK()", "'  =HYPERLINK()"),  # leading spaces do not hide the formula
        ("safe = text", "safe = text"),
        ("name@example.com", "name@example.com"),
        ("", ""),
        (None, ""),
        (-3, "-3"),  # real numbers are not text
        (-0.5, "-0.5"),
        (3.14159265, "3.1416"),
        (2.0, "2"),
        (True, "true"),
        (False, "false"),
        (date(2026, 1, 2), "2026-01-02"),
    ],
)
def test_csv_cell(value, expected):
    assert csv_cell(value) == expected


def test_render_csv_quotes_commas_quotes_and_newlines():
    out = render_csv(Table("t", ["a", "b"], [['say "hi", ok', "line1\nline2"], ["=x", None]]))
    assert out.splitlines(keepends=True)[0] == "a,b\r\n"
    assert '"say ""hi"", ok"' in out and '"line1\nline2"' in out
    assert out.endswith("'=x,\r\n")


def test_make_window_validation_and_defaults():
    assert make_window(None, None) == Window(None, None)
    w = make_window(None, date(2026, 3, 31), default_days=30)
    assert w.start == date(2026, 3, 2) and w.end == date(2026, 3, 31)
    assert make_window(date(2026, 3, 1), None, default_days=30).start == date(2026, 3, 1)
    with pytest.raises(ValidationFailure) as e1:
        make_window(date(2026, 3, 2), date(2026, 3, 1))
    assert e1.value.code == "INVALID_DATE_RANGE"
    with pytest.raises(ValidationFailure) as e2:
        make_window(date(2010, 1, 1), date(2026, 1, 1))
    assert e2.value.code == "DATE_RANGE_TOO_LARGE"
    with pytest.raises(ValidationFailure) as e3:
        make_window(date(2030, 1, 1), date(2026, 1, 1), default_days=5)
    assert e3.value.code == "INVALID_DATE_RANGE"


def test_bucket_starts():
    assert bucket_starts(date(2026, 1, 30), date(2026, 2, 2), "day") == [
        date(2026, 1, 30),
        date(2026, 1, 31),
        date(2026, 2, 1),
        date(2026, 2, 2),
    ]
    weeks = bucket_starts(date(2026, 10, 7), date(2026, 10, 21), "week")  # 2026-10-07 is a Wednesday
    assert weeks == [date(2026, 10, 5), date(2026, 10, 12), date(2026, 10, 19)]
    assert bucket_starts(date(2025, 11, 20), date(2026, 2, 3), "month") == [
        date(2025, 11, 1),
        date(2025, 12, 1),
        date(2026, 1, 1),
        date(2026, 2, 1),
    ]
    assert bucket_starts(date(2026, 5, 5), date(2026, 5, 5), "month") == [date(2026, 5, 1)]


def test_pick_granularity():
    assert pick_granularity(Window(date(2026, 1, 1), date(2026, 1, 30)), None) == "day"
    assert pick_granularity(Window(date(2026, 1, 1), date(2026, 6, 30)), None) == "week"
    assert pick_granularity(Window(date(2024, 1, 1), date(2026, 6, 30)), None) == "month"
    assert pick_granularity(Window(date(2026, 1, 1), date(2026, 1, 30)), "month") == "month"
    with pytest.raises(ValidationFailure) as e:
        pick_granularity(Window(date(2024, 1, 1), date(2026, 6, 30)), "day")
    assert e.value.code == "GRANULARITY_TOO_FINE" and MAX_BUCKETS == 400
