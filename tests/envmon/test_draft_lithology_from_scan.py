"""Tests for draft_lithology_from_scan.py — arcpy-free.

Model-backed steps (rasterize_pdf, extract_table_regions, recognize_structure,
the TrOCR call inside ocr_cells) are integration-only and gated behind
pytest.importorskip; everything else here runs with zero OCR dependencies
installed, matching the dev extras already used for Pillow/matplotlib-gated
tests elsewhere in tests/envmon/.
"""
from autogis.core.envmon.draft_lithology_from_scan import map_columns


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
