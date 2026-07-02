"""Unit tests for diff_schema / format_drift_report (headless, no arcgis)."""
import pytest

from autogis.core.agol.audit_schema import (
    diff_schema,
    format_drift_report,
    SchemaDriftReport,
    DriftItem,
    DRIFT_MISSING_FIELD,
    DRIFT_EXTRA_FIELD,
    DRIFT_TYPE_MISMATCH,
    DRIFT_DOMAIN_DRIFT,
    DRIFT_NULLABLE_MISMATCH,
)


# -- shared fixtures ------------------------------------------------------------

_BASE_SPEC = {
    "layer_name": "MonitoringWells",
    "fields": [
        {"name": "OBJECTID",   "type": "esriFieldTypeOID"},
        {"name": "LocationID", "type": "esriFieldTypeString", "nullable": True},
        {"name": "WellType",   "type": "esriFieldTypeString", "nullable": True,
         "domain": {
             "name": "WellTypeDomain",
             "coded_values": [
                 {"code": "MW", "name": "Monitoring Well"},
                 {"code": "SW", "name": "Surface Water"},
             ],
         }},
    ],
}

_BASE_AGOL = {
    "name": "MonitoringWells",
    "fields": [
        {"name": "OBJECTID",   "type": "esriFieldTypeOID",   "nullable": False, "domain": None},
        {"name": "LocationID", "type": "esriFieldTypeString", "nullable": True,  "domain": None},
        {"name": "WellType",   "type": "esriFieldTypeString", "nullable": True,
         "domain": {
             "type": "codedValue",
             "name": "WellTypeDomain",
             "codedValues": [
                 {"code": "MW", "name": "Monitoring Well"},
                 {"code": "SW", "name": "Surface Water"},
             ],
         }},
    ],
}


def _spec(**override) -> dict:
    return {**_BASE_SPEC, **override}


def _agol(**override) -> dict:
    return {**_BASE_AGOL, **override}


# -- clean / no drift -----------------------------------------------------------

def test_perfect_match_no_drift():
    report = diff_schema(_BASE_AGOL, _BASE_SPEC)
    assert not report.has_drift
    assert report.drift_items == []
    assert report.layer_name == "MonitoringWells"
    assert report.total_spec_fields == 3
    assert report.total_agol_fields == 3


# -- MISSING_FIELD ----------------------------------------------------------------

def test_missing_field_detected():
    spec = _spec(fields=_BASE_SPEC["fields"] + [
        {"name": "SampleDepth_ft", "type": "esriFieldTypeDouble"}
    ])
    report = diff_schema(_BASE_AGOL, spec)
    missing = [d for d in report.drift_items if d.drift_type == DRIFT_MISSING_FIELD]
    assert len(missing) == 1
    assert missing[0].field_name == "SampleDepth_ft"
    assert missing[0].agol_value is None
    assert missing[0].local_value == "esriFieldTypeDouble"


def test_missing_field_message_describes_problem():
    spec = _spec(fields=_BASE_SPEC["fields"] + [
        {"name": "SampleDepth_ft", "type": "esriFieldTypeDouble"}
    ])
    report = diff_schema(_BASE_AGOL, spec)
    missing = [d for d in report.drift_items if d.drift_type == DRIFT_MISSING_FIELD]
    assert "SampleDepth_ft" in missing[0].message


# -- EXTRA_FIELD ------------------------------------------------------------------

def test_extra_field_detected():
    agol = _agol(fields=_BASE_AGOL["fields"] + [
        {"name": "GlobalID", "type": "esriFieldTypeGlobalID",
         "nullable": False, "domain": None}
    ])
    report = diff_schema(agol, _BASE_SPEC)
    extra = [d for d in report.drift_items if d.drift_type == DRIFT_EXTRA_FIELD]
    assert len(extra) == 1
    assert extra[0].field_name == "GlobalID"
    assert extra[0].local_value is None
    assert extra[0].agol_value == "esriFieldTypeGlobalID"


# -- TYPE_MISMATCH ------------------------------------------------------------------

def test_type_mismatch_detected():
    agol = _agol(fields=[
        {"name": "OBJECTID",   "type": "esriFieldTypeOID",     "nullable": False, "domain": None},
        {"name": "LocationID", "type": "esriFieldTypeInteger",  "nullable": True,  "domain": None},
        {"name": "WellType",   "type": "esriFieldTypeString",   "nullable": True,
         "domain": {"type": "codedValue", "name": "WellTypeDomain",
                    "codedValues": [{"code": "MW", "name": "Monitoring Well"},
                                    {"code": "SW", "name": "Surface Water"}]}},
    ])
    report = diff_schema(agol, _BASE_SPEC)
    mismatches = [d for d in report.drift_items if d.drift_type == DRIFT_TYPE_MISMATCH]
    assert len(mismatches) == 1
    assert mismatches[0].field_name == "LocationID"
    assert mismatches[0].local_value == "esriFieldTypeString"
    assert mismatches[0].agol_value  == "esriFieldTypeInteger"


# -- NULLABLE_MISMATCH ------------------------------------------------------------

def test_nullable_mismatch_detected():
    agol = _agol(fields=[
        {"name": "OBJECTID",   "type": "esriFieldTypeOID",    "nullable": False, "domain": None},
        {"name": "LocationID", "type": "esriFieldTypeString",  "nullable": False, "domain": None},
        {"name": "WellType",   "type": "esriFieldTypeString",  "nullable": True,
         "domain": {"type": "codedValue", "name": "WellTypeDomain",
                    "codedValues": [{"code": "MW", "name": "Monitoring Well"},
                                    {"code": "SW", "name": "Surface Water"}]}},
    ])
    report = diff_schema(agol, _BASE_SPEC)
    nullables = [d for d in report.drift_items if d.drift_type == DRIFT_NULLABLE_MISMATCH]
    assert len(nullables) == 1
    assert nullables[0].field_name == "LocationID"


def test_nullable_not_checked_when_not_in_spec():
    """Fields without 'nullable' in spec should not produce NULLABLE_MISMATCH."""
    spec = _spec(fields=[
        {"name": "OBJECTID",   "type": "esriFieldTypeOID"},        # no nullable key
        {"name": "LocationID", "type": "esriFieldTypeString"},      # no nullable key
        {"name": "WellType",   "type": "esriFieldTypeString",
         "domain": {"name": "WellTypeDomain",
                    "coded_values": [{"code": "MW", "name": "Monitoring Well"},
                                     {"code": "SW", "name": "Surface Water"}]}},
    ])
    report = diff_schema(_BASE_AGOL, spec)
    nullables = [d for d in report.drift_items if d.drift_type == DRIFT_NULLABLE_MISMATCH]
    assert nullables == []


# -- DOMAIN_DRIFT: spec has domain, AGOL has none ---------------------------------

def test_domain_drift_spec_has_domain_agol_has_none():
    agol = _agol(fields=[
        {"name": "OBJECTID",   "type": "esriFieldTypeOID",   "nullable": False, "domain": None},
        {"name": "LocationID", "type": "esriFieldTypeString", "nullable": True,  "domain": None},
        {"name": "WellType",   "type": "esriFieldTypeString", "nullable": True,  "domain": None},
    ])
    report = diff_schema(agol, _BASE_SPEC)
    domain_items = [d for d in report.drift_items if d.drift_type == DRIFT_DOMAIN_DRIFT]
    assert len(domain_items) == 1
    assert domain_items[0].field_name == "WellType"
    assert domain_items[0].local_value == "WellTypeDomain"
    assert domain_items[0].agol_value is None


# -- DOMAIN_DRIFT: AGOL has domain, spec has none ---------------------------------

def test_domain_drift_agol_has_domain_spec_has_none():
    spec = _spec(fields=[
        {"name": "OBJECTID",   "type": "esriFieldTypeOID"},
        {"name": "LocationID", "type": "esriFieldTypeString", "nullable": True},
        {"name": "WellType",   "type": "esriFieldTypeString", "nullable": True},
    ])
    report = diff_schema(_BASE_AGOL, spec)
    domain_items = [d for d in report.drift_items if d.drift_type == DRIFT_DOMAIN_DRIFT]
    assert len(domain_items) == 1
    assert domain_items[0].field_name == "WellType"
    assert domain_items[0].agol_value == "WellTypeDomain"
    assert domain_items[0].local_value is None


# -- DOMAIN_DRIFT: domain name mismatch -------------------------------------------

def test_domain_drift_name_mismatch():
    agol = _agol(fields=[
        {"name": "OBJECTID",   "type": "esriFieldTypeOID",   "nullable": False, "domain": None},
        {"name": "LocationID", "type": "esriFieldTypeString", "nullable": True,  "domain": None},
        {"name": "WellType",   "type": "esriFieldTypeString", "nullable": True,
         "domain": {"type": "codedValue", "name": "WellType_RENAMED",
                    "codedValues": [{"code": "MW", "name": "Monitoring Well"},
                                    {"code": "SW", "name": "Surface Water"}]}},
    ])
    report = diff_schema(agol, _BASE_SPEC)
    domain_items = [d for d in report.drift_items if d.drift_type == DRIFT_DOMAIN_DRIFT]
    name_mismatches = [d for d in domain_items
                       if d.local_value == "WellTypeDomain"
                       and d.agol_value == "WellType_RENAMED"]
    assert len(name_mismatches) == 1


# -- DOMAIN_DRIFT: coded value missing from AGOL ----------------------------------

def test_domain_drift_coded_value_missing_from_agol():
    agol = _agol(fields=[
        {"name": "OBJECTID",   "type": "esriFieldTypeOID",   "nullable": False, "domain": None},
        {"name": "LocationID", "type": "esriFieldTypeString", "nullable": True,  "domain": None},
        {"name": "WellType",   "type": "esriFieldTypeString", "nullable": True,
         "domain": {"type": "codedValue", "name": "WellTypeDomain",
                    "codedValues": [{"code": "MW", "name": "Monitoring Well"}]}},
    ])
    report = diff_schema(agol, _BASE_SPEC)
    domain_items = [d for d in report.drift_items if d.drift_type == DRIFT_DOMAIN_DRIFT]
    missing_code = [d for d in domain_items
                    if "SW" in (d.message or "") and d.agol_value is None]
    assert len(missing_code) == 1
    assert missing_code[0].local_value is not None


# -- DOMAIN_DRIFT: coded value extra in AGOL --------------------------------------

def test_domain_drift_coded_value_extra_in_agol():
    agol = _agol(fields=[
        {"name": "OBJECTID",   "type": "esriFieldTypeOID",   "nullable": False, "domain": None},
        {"name": "LocationID", "type": "esriFieldTypeString", "nullable": True,  "domain": None},
        {"name": "WellType",   "type": "esriFieldTypeString", "nullable": True,
         "domain": {"type": "codedValue", "name": "WellTypeDomain",
                    "codedValues": [{"code": "MW", "name": "Monitoring Well"},
                                    {"code": "SW", "name": "Surface Water"},
                                    {"code": "EW", "name": "Extraction Well"}]}},
    ])
    report = diff_schema(agol, _BASE_SPEC)
    domain_items = [d for d in report.drift_items if d.drift_type == DRIFT_DOMAIN_DRIFT]
    extra_code = [d for d in domain_items
                  if "EW" in (d.message or "") and d.local_value is None]
    assert len(extra_code) == 1
    assert extra_code[0].agol_value is not None


# -- DOMAIN_DRIFT: coded value label mismatch -------------------------------------

def test_domain_drift_coded_value_label_mismatch():
    agol = _agol(fields=[
        {"name": "OBJECTID",   "type": "esriFieldTypeOID",   "nullable": False, "domain": None},
        {"name": "LocationID", "type": "esriFieldTypeString", "nullable": True,  "domain": None},
        {"name": "WellType",   "type": "esriFieldTypeString", "nullable": True,
         "domain": {"type": "codedValue", "name": "WellTypeDomain",
                    "codedValues": [{"code": "MW", "name": "Monitor Well"},
                                    {"code": "SW", "name": "Surface Water"}]}},
    ])
    report = diff_schema(agol, _BASE_SPEC)
    domain_items = [d for d in report.drift_items if d.drift_type == DRIFT_DOMAIN_DRIFT]
    label_mismatches = [d for d in domain_items
                        if "MW" in (d.message or "") and "name" in (d.message or "")]
    assert len(label_mismatches) == 1


# -- mixed drift --------------------------------------------------------------------

def test_mixed_drift_types():
    """MISSING_FIELD + EXTRA_FIELD + TYPE_MISMATCH all in one pass."""
    spec = _spec(fields=[
        {"name": "OBJECTID",    "type": "esriFieldTypeOID"},
        {"name": "SampleDepth", "type": "esriFieldTypeDouble"},   # absent from AGOL
        {"name": "WellType",    "type": "esriFieldTypeInteger",   # type mismatch
         "domain": {"name": "WellTypeDomain",
                    "coded_values": [{"code": "MW", "name": "Monitoring Well"},
                                     {"code": "SW", "name": "Surface Water"}]}},
    ])
    agol = _agol(fields=[
        {"name": "OBJECTID", "type": "esriFieldTypeOID",     "nullable": False, "domain": None},
        {"name": "WellType", "type": "esriFieldTypeString",   "nullable": True,   # type mismatch vs spec
         "domain": {"type": "codedValue", "name": "WellTypeDomain",
                    "codedValues": [{"code": "MW", "name": "Monitoring Well"},
                                    {"code": "SW", "name": "Surface Water"}]}},
        {"name": "GlobalID", "type": "esriFieldTypeGlobalID", "nullable": False, "domain": None},
    ])
    report = diff_schema(agol, spec)
    types_found = {d.drift_type for d in report.drift_items}
    assert DRIFT_MISSING_FIELD in types_found
    assert DRIFT_EXTRA_FIELD   in types_found
    assert DRIFT_TYPE_MISMATCH in types_found


# -- SchemaDriftReport helpers ------------------------------------------------------

def test_drift_by_type_grouping():
    spec = _spec(fields=[
        {"name": "OBJECTID", "type": "esriFieldTypeOID"},
        {"name": "FieldA",   "type": "esriFieldTypeString"},
        {"name": "FieldB",   "type": "esriFieldTypeDouble"},
    ])
    agol = _agol(fields=[
        {"name": "OBJECTID", "type": "esriFieldTypeOID",     "nullable": False, "domain": None},
        {"name": "FieldA",   "type": "esriFieldTypeInteger",  "nullable": True,  "domain": None},
        {"name": "GlobalID", "type": "esriFieldTypeGlobalID", "nullable": False, "domain": None},
    ])
    report = diff_schema(agol, spec)
    by_type = report.drift_by_type
    assert len(by_type[DRIFT_MISSING_FIELD]) == 1
    assert len(by_type[DRIFT_EXTRA_FIELD])   == 1
    assert len(by_type[DRIFT_TYPE_MISMATCH]) == 1


def test_has_drift_false_when_clean():
    report = diff_schema(_BASE_AGOL, _BASE_SPEC)
    assert report.has_drift is False


def test_has_drift_true_when_dirty():
    spec = _spec(fields=_BASE_SPEC["fields"] + [
        {"name": "Missing", "type": "esriFieldTypeString"}
    ])
    assert diff_schema(_BASE_AGOL, spec).has_drift is True


# -- format_drift_report -------------------------------------------------------------

def test_format_report_clean():
    report = diff_schema(_BASE_AGOL, _BASE_SPEC)
    text = format_drift_report(report)
    assert "CLEAN" in text
    assert "No schema drift detected." in text
    assert "DRIFT DETECTED" not in text


def test_format_report_drift_detected():
    spec = _spec(fields=_BASE_SPEC["fields"] + [
        {"name": "SampleDepth_ft", "type": "esriFieldTypeDouble"}
    ])
    report = diff_schema(_BASE_AGOL, spec)
    text = format_drift_report(report)
    assert "DRIFT DETECTED" in text
    assert "MISSING_FIELD"   in text
    assert "SampleDepth_ft"  in text
    assert "CLEAN" not in text


def test_format_report_contains_layer_name():
    report = diff_schema(_BASE_AGOL, _BASE_SPEC)
    assert "MonitoringWells" in format_drift_report(report)


def test_format_report_shows_field_counts():
    report = diff_schema(_BASE_AGOL, _BASE_SPEC)
    text = format_drift_report(report)
    assert "3" in text   # 3 fields in both spec and AGOL