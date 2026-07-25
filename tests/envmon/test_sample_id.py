"""Contract tests for the lifecycle SampleID single owner (sample_id.py)."""
import re
from datetime import datetime

import pytest

from autogis.core.envmon.sample_id import (
    QC_SUFFIXES, SampleIdParts, build_sample_id, parse_sample_id,
    xform_sample_id_calc,
)


def test_build_primary_from_datetime_and_compact_string_agree():
    dt = datetime(2026, 7, 15)
    assert build_sample_id("MW-1", dt, "GW") == "MW-1-20260715-GW"
    assert build_sample_id("MW-1", "20260715", "GW") == "MW-1-20260715-GW"


def test_build_rejects_non_compact_date_string():
    with pytest.raises(ValueError):
        build_sample_id("MW-1", "2026-07-15", "GW")


def test_build_parse_round_trip_across_matrices_and_qc():
    for matrix in ("GW", "SOIL", "SW", "SEDIMENT"):
        for suffix in QC_SUFFIXES:
            qc = suffix[1:].upper()
            sid = build_sample_id("MW-1", "20260715", matrix, qc=qc)
            assert parse_sample_id(sid) == SampleIdParts(
                "MW-1", "20260715", matrix, qc)


def test_every_qc_suffix_parses_to_its_declared_type():
    from autogis.core.envmon.qc_sample_summary import _infer_qc_type
    for suffix, qtype in QC_SUFFIXES.items():
        sid = build_sample_id("MW-1", "20260715", "GW", qc=suffix[1:].upper())
        assert _infer_qc_type(sid, "") == qtype


def test_nodate_form_shape_and_uniqueness():
    a = build_sample_id("MW-01", None, "GW")
    b = build_sample_id("MW-01", None, "GW")
    assert re.fullmatch(r"MW-01-NODATE-[0-9A-F]{6}-GW", a)
    assert a != b


def test_nodate_parses_with_empty_date_and_qc_populated():
    sid = build_sample_id("MW-01", None, "GW", qc="FD")
    parts = parse_sample_id(sid)
    assert parts is not None
    assert parts.date_compact == ""
    assert parts.matrix == "GW"
    assert parts.qc == "FD"


def test_primary_parse_has_empty_qc():
    assert parse_sample_id("MW-1-20260715-GW").qc == ""


def test_non_lifecycle_identities_return_none():
    # sampling_plan form: {site}-{loc}-{event}-{group}
    assert parse_sample_id("H281-MW-1-2026Q3-VOCs") is None
    # legacy_migrator form: {loc}_{date_raw}_{row_idx}
    assert parse_sample_id("MW-1_2026-07-15_3") is None
    assert parse_sample_id("") is None


def test_xform_calc_matches_lifecycle_field_order():
    calc = xform_sample_id_calc()
    assert calc == (
        'concat(${WellID}, "-", '
        'format-date(${SamplingDate}, "%Y%m%d"), '
        '"-", ${Matrix}, '
        'if(selected(${IsFieldDup}, "yes"), "-FD", ""))'
    )
