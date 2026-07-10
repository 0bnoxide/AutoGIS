from __future__ import annotations

import datetime as dt

from autogis.core.envmon.gdb_schema import UNIQUE_KEYS, compute_unique_key


def _result_dict(**overrides) -> dict:
    d = {
        "SiteID": "S1", "Matrix": "GW", "LocationID": "MW-1",
        "SampleID": "MW-1-0626", "SampleDate": dt.date(2026, 6, 26),
        "AnalyteCanonicalName": "Benzene", "DepthIntervalText": "",
        "SourceCell": "",
    }
    d.update(overrides)
    return d


def test_compute_unique_key_matches_key_fields_order():
    key = compute_unique_key(_result_dict(), "Env_AnalyticalResults")
    assert len(key) == len(UNIQUE_KEYS["Env_AnalyticalResults"])


def test_compute_unique_key_normalizes_like_append():
    # str strip+upper, date -> YYYY-MM-DD string: identical rows re-imported
    # from differently-cased sources must collide.
    a = compute_unique_key(_result_dict(SampleID=" mw-1-0626 "),
                           "Env_AnalyticalResults")
    b = compute_unique_key(_result_dict(SampleID="MW-1-0626"),
                           "Env_AnalyticalResults")
    assert a == b
    assert "2026-06-26" in a


def test_compute_unique_key_missing_field_yields_none_part():
    # d.get(k) semantics preserved: absent key -> None passes through.
    d = _result_dict()
    del d["SourceCell"]
    key = compute_unique_key(d, "Env_AnalyticalResults")
    assert None in key


def test_record_to_row_is_gone():
    import autogis.core.envmon.gdb_schema as gs
    assert not hasattr(gs, "record_to_row")
