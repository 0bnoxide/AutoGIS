from autogis.core.common.config_validation import validate_units
from autogis.core.common.qa import SEV_ERROR, SEV_WARNING


def _cats(records):
    return {(r.severity, r.category) for r in records}


def _analytes(units_by_matrix):
    return {"Benzene": {"aliases": ["benzene"], "abbreviation": "B",
                        "default_units_by_matrix": units_by_matrix}}


def test_unknown_screening_unit_is_error():
    analytes = _analytes({"GW": "ug/L"})
    screening = {"GW": {"Benzene": {"value": None, "units": "qg/L"}}}
    assert (SEV_ERROR, "unknown_unit") in _cats(validate_units(analytes, screening))


def test_unknown_dictionary_unit_is_error():
    analytes = _analytes({"GW": "ppb"})
    assert (SEV_ERROR, "unknown_unit") in _cats(validate_units(analytes, {}))


def test_cross_dimension_is_error():
    analytes = _analytes({"GW": "ug/L"})
    screening = {"GW": {"Benzene": {"value": None, "units": "mg/kg"}}}
    assert (SEV_ERROR, "cross_dimension") in _cats(validate_units(analytes, screening))


def test_convertible_mismatch_is_warning():
    analytes = _analytes({"GW": "ug/L"})
    screening = {"GW": {"Benzene": {"value": None, "units": "mg/L"}}}
    cats = _cats(validate_units(analytes, screening))
    assert (SEV_WARNING, "convertible_mismatch") in cats
    assert (SEV_ERROR, "cross_dimension") not in cats


def test_matching_units_emit_nothing():
    analytes = _analytes({"GW": "ug/L"})
    screening = {"GW": {"Benzene": {"value": None, "units": "ug/L"}}}
    assert validate_units(analytes, screening) == []


def test_missing_screening_units_skipped():
    analytes = _analytes({"GW": "ug/L"})
    screening = {"GW": {"Benzene": {"value": None}}}
    assert validate_units(analytes, screening) == []
