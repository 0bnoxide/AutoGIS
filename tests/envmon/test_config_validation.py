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


def test_validate_analyte_dictionary_9999_sentinel_not_flagged():
    analytes = {
        "A": {"aliases": [], "abbreviation": "A", "display_order": 9999},
        "B": {"aliases": [], "abbreviation": "Bb", "display_order": 9999},
    }
    records = cv.validate_analyte_dictionary(analytes)
    assert (SEV_WARNING, "duplicate_display_order") not in {
        (r.severity, r.category) for r in records}
