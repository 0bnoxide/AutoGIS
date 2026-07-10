"""GW_ANALYTICAL sheets (analytes only, no MPE/DTW/GWE — the H272 Havre
layout) must flow through normalize_gw_table_2 producing analytical results
and NO water-level records or water-level QA noise."""

from datetime import datetime

from autogis.core.common.config import ParserProfile, SheetProfile
from autogis.core.common.qa import QACollector
from autogis.core.envmon.normalize_groundwater import normalize_gw_table_2

from conftest import InMemoryWorkbookReader

BATCH = "TESTBATCH"


def _profile():
    sheet = SheetProfile.from_dict({
        "sheet_name": "GW Quality", "data_type": "GW_ANALYTICAL",
        "analyte_header_row": 1, "units_row": 2, "screening_level_row": 3,
        "data_start_row": 4, "id_column": "A", "date_column": "B",
        "analyte_columns": {"from": "C", "to": "C"},
    })
    return ParserProfile(profile_id="T", data={}, sheets={sheet.sheet_name: sheet})


def test_gw_analytical_sheet_yields_results_and_no_water_levels():
    cells = {
        ("GW Quality", 1, 3): "Benzene",
        ("GW Quality", 2, 3): "ug/L",
        ("GW Quality", 3, 3): "5",
        ("GW Quality", 4, 1): "MW-1",
        ("GW Quality", 4, 2): datetime(2026, 4, 15),
        ("GW Quality", 4, 3): "6.4",          # exceeds RBSL 5
        ("GW Quality", 5, 1): "MW-2",
        ("GW Quality", 5, 2): datetime(2026, 4, 15),
        ("GW Quality", 5, 3): "<1.0",
    }
    reader = InMemoryWorkbookReader(cells)
    qa = QACollector()
    adict = {"Benzene": {"aliases": ["benzene"]}}

    wl, samples, results = normalize_gw_table_2(
        None, _profile(), "H272", BATCH, adict, {}, qa, reader=reader)

    assert wl == []                            # no water-level extraction
    by = {r.LocationID: r for r in results}
    assert by["MW-1"].ResultNumeric == 6.4
    assert by["MW-1"].ExceedsScreeningLevel == 1
    assert by["MW-2"].IsNonDetect == 1
    # no spurious per-row water-level QA (the pre-fix failure mode)
    assert not [r for r in qa.records
                if "water" in r.category or "unparsable" in r.category]
