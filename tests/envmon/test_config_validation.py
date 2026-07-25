from autogis.core.common import config_validation as cv
from autogis.core.common.qa import SEV_ERROR, SEV_WARNING


def _cats(records):
    return {(r.severity, r.category) for r in records}


def test_validate_site_flags_missing_keys_and_todos():
    data = {"site_id": "H281", "map_units": "feet",
            "coordinate_system": "_TODO verify", "plausible_gwe_range_ft": [1900, 2400]}
    records = cv.validate_site(data)
    cats = _cats(records)
    # missing required keys (site_name etc.) -> ERROR / missing_key
    assert (SEV_ERROR, "missing_key") in cats
    # _TODO value -> WARNING / placeholder
    assert (SEV_WARNING, "placeholder") in cats


def test_validate_site_bad_map_units_and_gwe_range():
    data = {k: "x" for k in cv._SITE_MIN}  # minimal so missing_key doesn't dominate
    data["map_units"] = "furlongs"
    data["plausible_gwe_range_ft"] = [2400, 1900]  # descending
    records = cv.validate_site(data)
    cats = _cats(records)
    assert (SEV_ERROR, "bad_map_units") in cats
    assert (SEV_ERROR, "bad_gwe_range") in cats


def test_validate_figure_spec_unknown_matrix_is_error_unknown_maptype_is_warning():
    data = {k: "x" for k in cv._FIGURE_MIN}
    data["matrix"] = "AIR"
    data["map_type"] = "GW_BRAND_NEW"
    records = cv.validate_figure_spec(data)
    cats = _cats(records)
    assert (SEV_ERROR, "bad_matrix") in cats
    assert (SEV_WARNING, "unknown_map_type") in cats


def test_validate_parser_profile_bad_column_ref():
    data = {"profile_id": "P", "sheets": [
        {"sheet_name": "S", "data_type": "METALS", "data_start_row": 2,
         "id_column": "not-a-column"}]}
    records = cv.validate_parser_profile(data)
    assert (SEV_ERROR, "bad_column_ref") in _cats(records)


def test_validate_parser_profile_flags_draft_profile_id():
    """#78: draft-parser-profile output must surface as an active QA
    finding, not just a silent _TODO marker a reviewer could miss."""
    data = {"profile_id": "DRAFT", "sheets": []}
    records = cv.validate_parser_profile(data)
    assert (SEV_WARNING, "draft_profile") in _cats(records)


def test_validate_parser_profile_reviewed_profile_not_flagged():
    data = {"profile_id": "H281_Reviewed_v2", "sheets": []}
    records = cv.validate_parser_profile(data)
    assert "draft_profile" not in {r.category for r in records}


def test_validate_parser_profile_gw_water_level_only_is_known():
    """Regression: GW_WATER_LEVEL_ONLY is a shipped, actively-dispatched
    data_type (normalize_groundwater.py, H272_Havre_GW_Elevation.yaml) but
    was missing from KNOWN_SHEET_DATA_TYPES, so a legitimate production
    profile spuriously triggered unknown_data_type."""
    data = {"profile_id": "P", "sheets": [
        {"sheet_name": "S", "data_type": "GW_WATER_LEVEL_ONLY",
         "data_start_row": 2}]}
    records = cv.validate_parser_profile(data)
    assert "unknown_data_type" not in {r.category for r in records}


def test_h272_elevation_profile_has_no_unknown_data_type_warning():
    from pathlib import Path
    import autogis
    from autogis.core.common.config import load_config

    profile_path = (Path(autogis.__file__).resolve().parent / "config" /
                    "parser_profiles" / "H272_Havre_GW_Elevation.yaml")
    records = cv.validate_parser_profile(load_config(profile_path))
    assert "unknown_data_type" not in {r.category for r in records}


def test_validate_figure_spec_flags_draft_note():
    """#78: a figure spec's DraftNote convention (e.g. draft contour maps)
    must surface as an active QA finding."""
    data = {k: "x" for k in cv._FIGURE_MIN}
    data["DraftNote"] = "CONTOURS ARE DRAFT -- PROFESSIONAL REVIEW REQUIRED"
    records = cv.validate_figure_spec(data)
    assert (SEV_WARNING, "draft_figure_spec") in _cats(records)


def test_validate_figure_spec_without_draft_note_not_flagged():
    data = {k: "x" for k in cv._FIGURE_MIN}
    records = cv.validate_figure_spec(data)
    assert "draft_figure_spec" not in {r.category for r in records}


def test_validate_screening_levels_entry_missing_units():
    data = {"GW": {"Benzene": {"value": 5.0}}}  # no units
    records = cv.validate_screening_levels(data)
    assert (SEV_ERROR, "screening_missing_field") in _cats(records)


def test_validate_analyte_dictionary_detects_alias_collision_and_dup_order():
    analytes = {
        "Benzene": {"aliases": ["benzene", "B"], "abbreviation": "B",
                    "display_order": 10},
        "Toluene": {"aliases": ["toluene", "b"], "abbreviation": "T",
                    "display_order": 10},  # 'b' collides w/ Benzene; order dup
    }
    records = cv.validate_analyte_dictionary(analytes)
    cats = {(r.severity, r.category) for r in records}
    assert (SEV_ERROR, "alias_collision") in cats
    assert (SEV_WARNING, "duplicate_display_order") in cats


def test_validate_analyte_dictionary_flags_todo_source():
    analytes = {"Arsenic": {"aliases": ["as"], "abbreviation": "As",
                            "display_order": 200,
                            "screening_level_source": "_TODO MCL/DEQ-7"}}
    records = cv.validate_analyte_dictionary(analytes)
    assert (SEV_WARNING, "placeholder") in {(r.severity, r.category) for r in records}


def test_validate_analyte_dictionary_flags_todo_in_any_field():
    """A _TODO anywhere in an analyte entry is surfaced, not only in
    screening_level_source — the dictionary is scanned with the shared
    scan_todos so coverage is consistent with the other config validators."""
    analytes = {"Lead": {"aliases": ["pb"], "abbreviation": "Pb",
                         "display_order": 300,
                         "default_units_by_matrix": {"GW": "_TODO ug/L"}}}
    records = cv.validate_analyte_dictionary(analytes)
    placeholders = [r for r in records if r.category == "placeholder"]
    assert placeholders, "expected a placeholder warning for _TODO in default_units_by_matrix"
    # structured per-analyte context is preserved on the shared-scanner record
    assert placeholders[0].analyte_name == "Lead"


def test_validate_analyte_dictionary_skips_underscore_meta_entries():
    """Underscore-prefixed meta/template entries are not scanned for _TODO."""
    analytes = {"_template": {"screening_level_source": "_TODO fill me"},
                "Benzene": {"aliases": ["b"], "abbreviation": "Bz",
                            "display_order": 10}}
    records = cv.validate_analyte_dictionary(analytes)
    assert not [r for r in records if r.category == "placeholder"]


def test_validate_analyte_dictionary_9999_sentinel_not_flagged():
    analytes = {
        "A": {"aliases": [], "abbreviation": "A", "display_order": 9999},
        "B": {"aliases": [], "abbreviation": "Bb", "display_order": 9999},
    }
    records = cv.validate_analyte_dictionary(analytes)
    assert (SEV_WARNING, "duplicate_display_order") not in {
        (r.severity, r.category) for r in records}


def test_validate_bundle_flags_unknown_figure_and_screening_analytes():
    analytes = {"Benzene": {"aliases": ["benzene", "B"], "abbreviation": "B",
                            "display_order": 10,
                            "default_units_by_matrix": {"GW": "ug/L"}}}
    figure_specs = [{"figure_spec_id": "F1", "analytes": ["Benzene", "Xylenes"]}]
    screening = {"GW": {"Benzene": {"value": 5, "units": "mg/L"},  # unit mismatch
                        "Lead": {"value": 15, "units": "ug/L"}}}   # not in dict
    records = cv.validate_bundle(figure_specs, screening, analytes)
    cats = {(r.severity, r.category) for r in records}
    assert (SEV_ERROR, "figure_analyte_not_in_dictionary") in cats   # Xylenes
    assert (SEV_ERROR, "screening_analyte_not_in_dictionary") in cats  # Lead
    assert (SEV_WARNING, "units_mismatch") in cats                     # Benzene mg/L vs ug/L


def test_validate_parser_profile_rejects_nonpositive_int_column():
    data = {"profile_id": "P", "sheets": [
        {"sheet_name": "S", "data_type": "METALS", "data_start_row": 2,
         "id_column": 0}]}
    records = cv.validate_parser_profile(data)
    assert (SEV_ERROR, "bad_column_ref") in {(r.severity, r.category)
                                             for r in records}


# --- output_filename_pattern validation ---

_FIGURE_BASE = {
    "figure_spec_id": "FS-001",
    "map_type": "GW_ANALYTICAL",
    "matrix": "GW",
    "layout_name": "Standard",
    "figure_title": "Groundwater",
    "callout_template": "default",
    "output_filename_pattern": "{SiteID}_{EventDate}",
}


def test_valid_filename_pattern_passes():
    recs = cv.validate_figure_spec(_FIGURE_BASE)
    cats = [r.category for r in recs]
    assert "invalid_filename_pattern" not in cats


def test_empty_filename_pattern_errors():
    spec = {**_FIGURE_BASE, "output_filename_pattern": ""}
    recs = cv.validate_figure_spec(spec)
    assert any(r.category == "invalid_filename_pattern" for r in recs)


def test_unsafe_chars_in_pattern_errors():
    spec = {**_FIGURE_BASE, "output_filename_pattern": "{SiteID}; rm -rf /"}
    recs = cv.validate_figure_spec(spec)
    assert any(r.category == "invalid_filename_pattern" for r in recs)


def test_unbalanced_braces_in_pattern_errors():
    spec = {**_FIGURE_BASE, "output_filename_pattern": "{SiteID_EventDate"}
    recs = cv.validate_figure_spec(spec)
    assert any(r.category == "invalid_filename_pattern" for r in recs)


def test_missing_filename_pattern_is_warned():
    spec = {k: v for k, v in _FIGURE_BASE.items() if k != "output_filename_pattern"}
    recs = cv.validate_figure_spec(spec)
    warn = [r for r in recs if r.category == "missing_filename_pattern"]
    assert len(warn) == 1
    assert warn[0].severity == SEV_WARNING
