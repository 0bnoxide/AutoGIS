"""Targeted unit tests for normalize_matrix_table's config-sourced screening
level path (autogis/core/envmon/table_normalizer.py), using the in-memory
reader so no workbook file is needed.
"""

from autogis.core.common.config import SheetProfile
from autogis.core.common.qa import QACollector
from autogis.core.envmon.table_normalizer import normalize_matrix_table

from conftest import InMemoryWorkbookReader

BATCH = "TESTBATCH"


def _sheet():
    return SheetProfile.from_dict({
        "sheet_name": "S", "data_type": "TEST", "data_start_row": 3,
        "analyte_header_row": 1, "units_row": 2,
        "id_column": "A", "analyte_columns": {"from": "B", "to": "B"},
    })


def test_config_screening_level_unit_is_carried_through():
    """A result reported in mg/L must be converted before comparing against
    a config-sourced screening level given in ug/L (regression for the
    cfg.get('unit') vs cfg.get('units') key mismatch — the workbook has no
    screening_level_row of its own, forcing the config fallback path)."""
    cells = {
        ("S", 1, 2): "Benzene",
        ("S", 2, 2): "mg/L",
        ("S", 3, 1): "MW-1",
        ("S", 3, 2): "0.01",   # 0.01 mg/L == 10 ug/L
    }
    reader = InMemoryWorkbookReader(cells)
    adict = {"Benzene": {"aliases": ["benzene"]}}
    slevels = {"GW": {"Benzene": {"value": 5, "units": "ug/L", "source": "test"}}}
    qa = QACollector()

    _, results = normalize_matrix_table(
        reader, _sheet(), matrix="GW", analytical_group="TEST",
        site_id="TEST", batch_id=BATCH, analyte_dictionary=adict,
        screening_levels=slevels, qa=qa)

    r = results[0]
    assert r.ScreeningLevel == 5
    assert r.Units == "mg/L"
    # 10 ug/L > 5 ug/L screening level -> exceeds, only correct if the mg/L
    # result was converted to ug/L before comparison.
    assert r.ExceedsScreeningLevel == 1
