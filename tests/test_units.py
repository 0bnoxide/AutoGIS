import pytest

from autogis.core.common.units import (
    UnitError, normalize_unit, dimension_of, same_dimension, convert)


def test_normalize_handles_micro_case_and_whitespace():
    assert normalize_unit(" ug/l ") == "ug/L"
    assert normalize_unit("UG/L") == "ug/L"
    assert normalize_unit("µg/L") == "ug/L"   # U+00B5 micro sign
    assert normalize_unit("μg/L") == "ug/L"   # U+03BC greek mu


def test_normalize_unknown_and_ambiguous_return_none():
    assert normalize_unit("ppb") is None
    assert normalize_unit("ppm") is None
    assert normalize_unit("qg/L") is None
    assert normalize_unit(None) is None


def test_dimension_and_same_dimension():
    assert dimension_of("mg/L") == "aqueous"
    assert dimension_of("mg/kg") == "soil"
    assert same_dimension("ug/L", "mg/L") is True
    assert same_dimension("mg/L", "mg/kg") is False
    assert same_dimension("ppb", "mg/L") is False


def test_convert_within_dimension_both_directions():
    assert convert(1.0, "mg/L", "ug/L") == 1000.0
    assert convert(1000.0, "ug/L", "mg/L") == 1.0
    assert convert(2.0, "mg/kg", "ug/kg") == 2000.0


def test_convert_unknown_unit_raises():
    with pytest.raises(UnitError):
        convert(1.0, "ppb", "ug/L")


def test_convert_cross_dimension_raises():
    with pytest.raises(UnitError):
        convert(1.0, "mg/L", "mg/kg")
