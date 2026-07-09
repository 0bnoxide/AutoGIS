"""Tests for draft_lithology_from_scan.py — arcpy-free.

Model-backed steps (rasterize_pdf, extract_table_regions, recognize_structure,
the TrOCR call inside ocr_cells) are integration-only and gated behind
pytest.importorskip; everything else here runs with zero OCR dependencies
installed, matching the dev extras already used for Pillow/matplotlib-gated
tests elsewhere in tests/envmon/.
"""
from autogis.core.common.qa import QACollector, SEV_ERROR, SEV_WARNING, SEV_INFO
from autogis.core.common.schema.boring import LithologyInterval
from autogis.core.envmon.draft_lithology_from_scan import (
    CellResult, _flag_row_confidence, _row_to_lithology_interval, _to_float,
    map_columns, write_draft_csv,
)
from autogis.core.envmon.import_boring_logs import parse_lithology_csv


def test_map_columns_matches_known_aliases():
    header = ["Boring No", "Depth From", "Depth To", "USCS Symbol",
              "Soil Description", "Color", "Moisture Content", "Material"]
    result = map_columns(header)
    assert result == {
        0: "boring_id", 1: "top_depth", 2: "bottom_depth", 3: "uscs",
        4: "description", 5: "color", 6: "moisture", 7: "primary_material",
    }


def test_map_columns_ignores_unrecognized_header():
    header = ["Boring No", "Sample Type", "Blow Counts"]
    result = map_columns(header)
    assert result == {0: "boring_id"}


def test_map_columns_is_case_and_punctuation_insensitive():
    header = ["BORING-ID", "top depth (ft)", "bottom depth (ft)"]
    result = map_columns(header)
    assert result[0] == "boring_id"
    assert result[1] == "top_depth"
    assert result[2] == "bottom_depth"


def test_map_columns_anchors_short_aliases_and_maps_secondary_material():
    # "Total Depth" must NOT false-match the bare "to" alias; a genuine bare
    # "To"/"From" column still must; "Secondary Material" routes to
    # secondary_material, not primary_material.
    result = map_columns(["Total Depth", "Secondary Material", "To", "From"])
    assert 0 not in result
    assert result[1] == "secondary_material"
    assert result[2] == "bottom_depth"
    assert result[3] == "top_depth"


def test_to_float_parses_valid_number():
    assert _to_float("12.5") == 12.5


def test_to_float_returns_none_for_garbage():
    assert _to_float("illegible") is None
    assert _to_float("") is None


def test_flag_row_confidence_low_is_warning():
    qa = QACollector()
    _flag_row_confidence(qa, 0.4, page_number=1, row_number=3)
    assert qa.records[0].severity == SEV_WARNING
    assert "verify against scan" in qa.records[0].message


def test_flag_row_confidence_moderate_is_info():
    qa = QACollector()
    _flag_row_confidence(qa, 0.7, page_number=1, row_number=3)
    assert qa.records[0].severity == SEV_INFO
    assert "spot-check" in qa.records[0].message


def test_flag_row_confidence_high_is_unflagged():
    qa = QACollector()
    _flag_row_confidence(qa, 0.9, page_number=1, row_number=3)
    assert qa.records == []


def test_row_to_lithology_interval_builds_from_mapped_columns():
    qa = QACollector()
    field_to_index = {"boring_id": 0, "top_depth": 1, "bottom_depth": 2,
                       "uscs": 3, "description": 4}
    row = [CellResult("MW-1", 0.95), CellResult("2.0", 0.95),
           CellResult("4.0", 0.95), CellResult("CL", 0.95),
           CellResult("Lean clay, brown", 0.95)]
    interval = _row_to_lithology_interval(row, field_to_index, qa, 1, 1)
    assert interval.boring_id == "MW-1"
    assert interval.top_depth == 2.0
    assert interval.bottom_depth == 4.0
    assert interval.uscs == "CL"
    assert interval.description == "Lean clay, brown"
    assert qa.records == []  # confidence 0.95 -> no flag


def test_row_to_lithology_interval_drops_row_with_unparseable_depth():
    qa = QACollector()
    field_to_index = {"boring_id": 0, "top_depth": 1, "bottom_depth": 2}
    row = [CellResult("MW-1", 0.9), CellResult("illegible", 0.3),
           CellResult("4.0", 0.9)]
    interval = _row_to_lithology_interval(row, field_to_index, qa, 1, 2)
    assert interval is None
    assert qa.records[0].severity == SEV_WARNING
    assert qa.records[0].category == "row_dropped_unparseable_depth"


def test_row_to_lithology_interval_flags_missing_boring_id():
    qa = QACollector()
    field_to_index = {"top_depth": 0, "bottom_depth": 1}
    row = [CellResult("2.0", 0.9), CellResult("4.0", 0.9)]
    interval = _row_to_lithology_interval(row, field_to_index, qa, 1, 1)
    assert interval.boring_id == ""
    assert any(r.category == "boring_id_not_detected" for r in qa.records)


def test_write_draft_csv_round_trips_through_existing_parser(tmp_path):
    rows = [
        LithologyInterval(boring_id="MW-1", top_depth=0.0, bottom_depth=2.0,
                           uscs="ML", primary_material="Silt", color="Brown",
                           moisture="Moist", description="Sandy silt"),
        LithologyInterval(boring_id="MW-1", top_depth=2.0, bottom_depth=5.0,
                           uscs="CL", primary_material="Clay", color="Gray",
                           moisture="Wet", description="Lean clay"),
    ]
    out_path = write_draft_csv(rows, tmp_path / "lithology.csv")
    assert out_path.exists()

    parsed = parse_lithology_csv(out_path)
    assert len(parsed) == 2
    assert parsed[0].boring_id == "MW-1"
    assert parsed[0].top_depth == 0.0
    assert parsed[0].bottom_depth == 2.0
    assert parsed[0].uscs == "ML"
    assert parsed[0].description == "Sandy silt"
    assert parsed[1].color == "Gray"
