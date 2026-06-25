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


import yaml

from autogis.core.envmon.validate_units import validate_units_config
from autogis.core.common.qa import SEV_INFO


def _write(tmp_path, name, data):
    p = tmp_path / name
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


def test_orchestrator_flags_cross_dimension(tmp_path):
    analytes = _write(tmp_path, "analytes.yaml", {"analytes": {
        "Benzene": {"aliases": ["benzene"], "abbreviation": "B",
                    "default_units_by_matrix": {"GW": "ug/L"}}}})
    screening = _write(tmp_path, "screening.yaml", {"screening_levels": {
        "GW": {"Benzene": {"value": None, "units": "mg/kg"}}}})
    qa = validate_units_config(analytes, screening)
    cats = {(r.severity, r.category) for r in qa.records}
    assert (SEV_ERROR, "cross_dimension") in cats
    assert (SEV_INFO, "validation_complete") in cats


def test_orchestrator_bad_file_becomes_load_error(tmp_path):
    bad = tmp_path / "analytes.yaml"
    bad.write_text(": : not valid yaml : :", encoding="utf-8")
    screening = _write(tmp_path, "screening.yaml", {"screening_levels": {}})
    qa = validate_units_config(bad, screening)
    assert (SEV_ERROR, "load_error") in {(r.severity, r.category) for r in qa.records}
