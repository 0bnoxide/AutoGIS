"""Tests for label_expression_common module (shared by arcade + python label generators)."""
from autogis.core.envmon.label_expression_common import (
    LabelExpressionType,
    LabelFields,
    derive_label_fields,
)


def test_derive_label_fields_returns_label_fields_instance():
    result = derive_label_fields("Benzene")
    assert isinstance(result, LabelFields)


def test_derive_label_fields_value_field():
    result = derive_label_fields("Benzene")
    assert result.value_field == "Benzene_Value"


def test_derive_label_fields_units_field():
    result = derive_label_fields("Benzene")
    assert result.units_field == "Benzene_Units"


def test_derive_label_fields_sl_field():
    result = derive_label_fields("Benzene")
    assert result.sl_field == "Benzene_SL"


def test_derive_label_fields_id_field_no_prefix():
    result = derive_label_fields("Benzene")
    assert result.id_field == "LocationID"


def test_derive_label_fields_layer_base():
    result = derive_label_fields("Benzene")
    assert result.layer_base == "Benzene"


def test_derive_label_fields_with_field_prefix():
    result = derive_label_fields("Benzene", field_prefix="Env_")
    assert result.value_field == "Env_Benzene_Value"
    assert result.units_field == "Env_Benzene_Units"
    assert result.sl_field == "Env_Benzene_SL"
    assert result.id_field == "Env_LocationID"


def test_derive_label_fields_sanitizes_spaces_commas_slashes():
    result = derive_label_fields("cis-1,2-DCE/PCE")
    assert " " not in result.layer_base
    assert "," not in result.layer_base
    assert "/" not in result.layer_base


def test_label_expression_type_constants():
    assert LabelExpressionType.RESULT_WITH_UNITS == "RESULT_WITH_UNITS"
    assert LabelExpressionType.EXCEEDANCE_CALLOUT == "EXCEEDANCE_CALLOUT"
    assert LabelExpressionType.ND_CALLOUT == "ND_CALLOUT"
    assert LabelExpressionType.WELL_ID_ONLY == "WELL_ID_ONLY"
