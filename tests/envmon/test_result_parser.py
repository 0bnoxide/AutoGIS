"""parse_result_value / parse_excel_date behavior, per the spec rules."""

from datetime import date, datetime

import pytest

from autogis.core.envmon.result_parser import parse_excel_date, parse_result_value


@pytest.mark.parametrize("raw,expect", [
    # plain numerics, with thousands separators and floats from Excel
    ("150", dict(is_numeric=True, result_numeric=150.0, is_detected=True)),
    ("1,200", dict(is_numeric=True, result_numeric=1200.0)),
    (6.4, dict(is_numeric=True, result_numeric=6.4)),
    ("0.005 J", dict(is_numeric=True, result_numeric=0.005,
                     is_estimated=True, is_detected=True)),
    ("12 J", dict(is_numeric=True, result_numeric=12.0, is_estimated=True)),
    ("45 D", dict(is_numeric=True, result_numeric=45.0, is_diluted=True)),
    # nondetects — NEVER coerced to zero, RL preserved
    ("<1.0", dict(is_nondetect=True, reporting_limit=1.0,
                  result_numeric=None, is_detected=False)),
    ("<0.50 U", dict(is_nondetect=True, reporting_limit=0.5)),
    ("< 5", dict(is_nondetect=True, reporting_limit=5.0)),
    ("ND", dict(is_nondetect=True, reporting_limit=None)),
    # status codes
    ("NA", dict(is_not_analyzed=True, is_numeric=False)),
    ("NS", dict(is_not_sampled=True)),
    ("NM", dict(is_not_measured=True)),
    ("Dry", dict(is_dry=True)),
    ("dry", dict(is_dry=True)),
    ("--", dict(is_blank=True)),
    ("", dict(is_blank=True)),
    (None, dict(is_blank=True)),
    # formula errors
    ("#VALUE!", dict(status_code="INVALID")),
    ("#DIV/0!", dict(status_code="INVALID")),
])
def test_parse_result_value(raw, expect):
    p = parse_result_value(raw)
    for attr, want in expect.items():
        assert getattr(p, attr) == want, (raw, attr, getattr(p, attr))
    # raw text is always preserved
    assert p.raw_text == ("" if raw is None else str(raw))


def test_footnote_only_in_screening_context():
    blocked = parse_result_value("1,000 3")
    assert blocked.result_numeric is None
    assert blocked.status_code == "UNPARSED"
    assert "footnote" in blocked.parse_warning

    ok = parse_result_value("1,000 3", screening_context=True)
    assert ok.result_numeric == 1000.0
    assert "footnote" in ok.parse_warning  # still flagged, just permitted


def test_nondetect_is_not_zero():
    p = parse_result_value("<1.0")
    assert p.result_numeric is None          # the cardinal rule
    assert p.reporting_limit == 1.0
    assert not p.is_detected


def test_na_ambiguity_is_flagged():
    p = parse_result_value("NA")
    assert "verify" in p.parse_warning.lower() or "NA" in p.parse_warning


@pytest.mark.parametrize("raw,want", [
    (datetime(2026, 4, 15), date(2026, 4, 15)),
    (date(2026, 4, 15), date(2026, 4, 15)),
    ("4/15/2026", date(2026, 4, 15)),
    ("2026-04-15", date(2026, 4, 15)),
    ("15-Apr-2026", date(2026, 4, 15)),
    (46127, date(2026, 4, 15)),       # 1900-system Excel serial
    ("garbage", None),
    (None, None),
])
def test_parse_excel_date(raw, want):
    assert parse_excel_date(raw, "1900") == want
