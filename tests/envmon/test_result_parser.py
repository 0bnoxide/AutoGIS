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


def test_na_on_screening_row_reads_as_no_criterion():
    """A real Montana DEQ RBSL table uses 'na' for bulk TPH/TEH (no criterion
    set, screened via fractions instead) -- the same 'NA' token means
    something different on a screening-level row than on a data row, so the
    message must not claim NOT_ANALYZED there."""
    p = parse_result_value("na", screening_context=True)
    assert p.is_not_analyzed  # status code itself is unchanged
    assert "not applicable" in p.parse_warning.lower()
    assert "not_analyzed" not in p.parse_warning.lower()


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


def test_apply_qualifiers_public_alias():
    from autogis.core.envmon.result_parser import apply_qualifiers, ParsedResult
    p = ParsedResult(raw_text="0.5")
    apply_qualifiers(p, "U")
    assert p.is_nondetect is True
    assert p.qualifier == "U"


from autogis.core.envmon.result_parser import evaluate_screening


def _det(value: float):
    p = parse_result_value(str(value))
    assert p.is_detected
    return p


def test_evaluate_screening_same_unit_no_conversion():
    assert evaluate_screening(_det(5.0), 3.0,
                              result_unit="ug/L", screening_unit="ug/L") is True


def test_evaluate_screening_converts_mg_to_ug():
    # 0.005 mg/L == 5 ug/L, threshold 3 ug/L -> exceeds
    assert evaluate_screening(_det(0.005), 3.0,
                              result_unit="mg/L", screening_unit="ug/L") is True


def test_evaluate_screening_converts_ug_to_mg():
    # 5 ug/L == 0.005 mg/L, threshold 0.003 mg/L -> exceeds
    assert evaluate_screening(_det(5.0), 0.003,
                              result_unit="ug/L", screening_unit="mg/L") is True


def test_evaluate_screening_different_dimension_returns_none():
    # ug/L (aqueous) vs mg/kg (soil) -> can't compare
    assert evaluate_screening(_det(5.0), 3.0,
                              result_unit="ug/L", screening_unit="mg/kg") is None


def test_evaluate_screening_unknown_unit_falls_through():
    # unknown unit: fallthrough, compare raw value (backward compat)
    assert evaluate_screening(_det(5.0), 3.0,
                              result_unit="ppm", screening_unit="ug/L") is True


def test_evaluate_screening_none_units_falls_through():
    assert evaluate_screening(_det(5.0), 3.0) is True
    assert evaluate_screening(_det(1.0), 3.0) is False


def test_normalize_analyte_name_collapses_embedded_newline():
    """Regression for a real wrapped Excel header cell (confirmed against a
    real client workbook's analyte header row): the cell's own text contains
    a literal embedded newline, e.g. 'C11-C22\\nAromatics', not just visual
    column-width wrapping. normalize_analyte_name must still resolve it."""
    from pathlib import Path

    import autogis
    from autogis.core.common.config import load_analyte_dictionary
    from autogis.core.envmon.result_parser import normalize_analyte_name

    adict = load_analyte_dictionary(
        Path(autogis.__file__).resolve().parent / "config" / "analytes"
        / "analyte_dictionary.yaml")
    assert normalize_analyte_name("C11-C22\nAromatics", adict) == "C11-C22 Aromatics"
