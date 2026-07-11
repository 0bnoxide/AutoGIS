"""Tests for wqx_reader.py — WQX Step-2 load-time transforms + end-to-end.

Loads the SHIPPED autogis/config/lab_profiles/wqx.yaml so the artifact users
run with is what's tested. arcpy-free.
"""
from __future__ import annotations

import csv
import dataclasses
from datetime import date
from pathlib import Path

import autogis
from autogis.core.common.qa import QACollector
from autogis.core.envmon.edd_importer import normalize_edd_rows, read_edd_file
from autogis.core.envmon.edd_profile import LabEDDProfile, validate_edd_profile
from autogis.core.envmon.gdb_schema import compute_unique_key
from autogis.core.envmon.wqx_reader import transform_wqx_rows

PROFILE_PATH = (Path(autogis.__file__).parent / "config" / "lab_profiles"
                / "wqx.yaml")
PROFILE = LabEDDProfile.load(PROFILE_PATH)


def _row(**over) -> dict:
    """One WQP result row with sane routine defaults."""
    base = {
        "ActivityIdentifier": "ACT-1",
        "MonitoringLocationIdentifier": "MW-1",
        "ActivityStartDate": "2026-06-15",
        "ActivityTypeCode": "Sample-Routine",
        "ActivityMediaName": "Water",
        "ActivityMediaSubdivisionName": "Groundwater",
        "CharacteristicName": "Benzene",
        "MethodSpeciationName": "",
        "ResultSampleFractionText": "Total",
        "ResultMeasureValue": "5.0",
        "ResultMeasure/MeasureUnitCode": "ug/L",
        "ResultDetectionConditionText": "",
        "ResultStatusIdentifier": "Final",
        "MeasureQualifierCode": "",
        "DetectionQuantitationLimitTypeName": "",
        "DetectionQuantitationLimitMeasure/MeasureValue": "",
        "DetectionQuantitationLimitMeasure/MeasureUnitCode": "",
        "SubstanceDilutionFactor": "",
        "StatisticalBaseCode": "",
        "ResultWeightBasisText": "",
        "ResultAnalyticalMethod/MethodIdentifier": "EPA 8260D",
        "ResultAnalyticalMethod/MethodName": "VOC by GC/MS",
        "AnalysisStartDate": "2026-06-20",
        "LaboratoryName": "Acme Labs",
        "LabSamplePreparationMethod/MethodIdentifier": "EPA 5030C",
        "PreparationStartDate": "2026-06-18",
        "SampleContainerLabelName": "LAB-001",
    }
    base.update(over)
    return base


def _transform(row: dict):
    qa = QACollector()
    out = transform_wqx_rows([row], PROFILE, qa)
    return out, qa


def _categories(qa: QACollector) -> list[str]:
    return [r.category for r in qa.records]


# ---------------------------------------------------------------------------
# Profile itself
# ---------------------------------------------------------------------------

def test_shipped_profile_validates():
    qa = QACollector()
    validate_edd_profile(PROFILE, qa)
    assert qa.records == []
    assert PROFILE.format == "wqx_csv"


# ---------------------------------------------------------------------------
# Non-detect synthesis (D3)
# ---------------------------------------------------------------------------

def test_nd_condition_synthesizes_nd():
    out, qa = _transform(_row(ResultMeasureValue="",
                              ResultDetectionConditionText="Not Detected"))
    assert out[0]["__wqx_result"] == "ND"
    assert _categories(qa) == []


def test_unmapped_condition_empty_value_warns():
    out, qa = _transform(_row(ResultMeasureValue="",
                              ResultDetectionConditionText="Systematic Contamination"))
    assert out[0]["__wqx_result"] == ""
    assert "wqx_unmapped_detection_condition" in _categories(qa)


def test_value_vs_nd_condition_conflict_condition_wins():
    out, qa = _transform(_row(ResultMeasureValue="5.0",
                              ResultDetectionConditionText="Not Detected"))
    assert out[0]["__wqx_result"] == "ND"
    assert "wqx_result_condition_conflict" in _categories(qa)


def test_detected_not_quantified_is_a_detection():
    out, qa = _transform(_row(ResultMeasureValue="0.3",
                              ResultDetectionConditionText="Detected Not Quantified"))
    assert out[0]["__wqx_result"] == "0.3"
    assert _categories(qa) == []


def test_mapped_non_nd_condition_with_empty_value_warns():
    # DNQ (a detection) with an EMPTY value imports as not-analyzed — that must
    # never be silent (cold review F2).
    out, qa = _transform(_row(ResultMeasureValue="",
                              ResultDetectionConditionText="Detected Not Quantified"))
    assert out[0]["__wqx_result"] == ""
    assert "wqx_condition_without_result" in _categories(qa)


# ---------------------------------------------------------------------------
# Limit routing + unit policy (D4)
# ---------------------------------------------------------------------------

def test_limit_routes_to_reporting_limit():
    out, qa = _transform(_row(
        **{"DetectionQuantitationLimitTypeName": "Practical Quantitation Limit",
           "DetectionQuantitationLimitMeasure/MeasureValue": "1.0",
           "DetectionQuantitationLimitMeasure/MeasureUnitCode": "ug/L"}))
    assert out[0]["__wqx_reporting_limit"] == "1.0"
    assert out[0]["__wqx_detection_limit"] == ""
    assert _categories(qa) == []


def test_limit_routes_to_detection_limit():
    out, qa = _transform(_row(
        **{"DetectionQuantitationLimitTypeName": "Method Detection Level",
           "DetectionQuantitationLimitMeasure/MeasureValue": "0.2",
           "DetectionQuantitationLimitMeasure/MeasureUnitCode": "ug/L"}))
    assert out[0]["__wqx_detection_limit"] == "0.2"
    assert out[0]["__wqx_reporting_limit"] == ""


def test_unmapped_limit_type_defaults_rl_and_warns():
    out, qa = _transform(_row(
        **{"DetectionQuantitationLimitTypeName": "Some Novel Limit",
           "DetectionQuantitationLimitMeasure/MeasureValue": "1.5",
           "DetectionQuantitationLimitMeasure/MeasureUnitCode": "ug/L"}))
    assert out[0]["__wqx_reporting_limit"] == "1.5"
    assert "wqx_unmapped_limit_type" in _categories(qa)


def test_limit_unit_converted_to_result_units():
    out, qa = _transform(_row(
        **{"DetectionQuantitationLimitTypeName": "Reporting Limit",
           "DetectionQuantitationLimitMeasure/MeasureValue": "10",
           "DetectionQuantitationLimitMeasure/MeasureUnitCode": "ng/L"}))
    # 10 ng/L -> 0.01 ug/L
    assert float(out[0]["__wqx_reporting_limit"]) == 0.01
    assert _categories(qa) == []


def test_same_unregistered_units_short_circuit_no_warn():
    out, qa = _transform(_row(
        **{"ResultMeasure/MeasureUnitCode": "deg C",
           "DetectionQuantitationLimitTypeName": "Reporting Limit",
           "DetectionQuantitationLimitMeasure/MeasureValue": "0.1",
           "DetectionQuantitationLimitMeasure/MeasureUnitCode": "deg C"}))
    assert out[0]["__wqx_reporting_limit"] == "0.1"
    assert _categories(qa) == []


def test_empty_limit_unit_assumes_result_units_no_warn():
    out, qa = _transform(_row(
        **{"DetectionQuantitationLimitTypeName": "Reporting Limit",
           "DetectionQuantitationLimitMeasure/MeasureValue": "0.5",
           "DetectionQuantitationLimitMeasure/MeasureUnitCode": ""}))
    assert out[0]["__wqx_reporting_limit"] == "0.5"
    assert _categories(qa) == []


def test_unconvertible_limit_unit_keeps_raw_and_warns():
    out, qa = _transform(_row(
        **{"DetectionQuantitationLimitTypeName": "Reporting Limit",
           "DetectionQuantitationLimitMeasure/MeasureValue": "0.4",
           "DetectionQuantitationLimitMeasure/MeasureUnitCode": "NTU"}))
    assert out[0]["__wqx_reporting_limit"] == "0.4"   # raw kept
    assert "wqx_limit_unit_mismatch" in _categories(qa)


def test_units_prefer_result_unit():
    out, _ = _transform(_row())
    assert out[0]["__wqx_units"] == "ug/L"


def test_nd_row_units_fall_back_to_limit_unit_unconverted():
    # WQP ND rows commonly carry no result unit; the record's Units must then
    # be the limit's unit and the limit value must stay in that unit
    # (cold review F3 — otherwise "limits in result units" silently breaks).
    out, qa = _transform(_row(
        **{"ResultMeasure/MeasureUnitCode": "",
           "ResultMeasureValue": "",
           "ResultDetectionConditionText": "Not Detected",
           "DetectionQuantitationLimitTypeName": "Reporting Limit",
           "DetectionQuantitationLimitMeasure/MeasureValue": "200",
           "DetectionQuantitationLimitMeasure/MeasureUnitCode": "ng/L"}))
    assert out[0]["__wqx_units"] == "ng/L"
    assert out[0]["__wqx_reporting_limit"] == "200.0"
    assert _categories(qa) == []


def test_bad_limit_value_dropped_with_warn():
    out, qa = _transform(_row(
        **{"DetectionQuantitationLimitTypeName": "Reporting Limit",
           "DetectionQuantitationLimitMeasure/MeasureValue": "n/a"}))
    assert out[0]["__wqx_reporting_limit"] == ""
    assert "wqx_bad_limit_value" in _categories(qa)


# ---------------------------------------------------------------------------
# MethodDilutionKey composite (D5) — unconditional fold
# ---------------------------------------------------------------------------

def test_dilution_key_all_components():
    out, _ = _transform(_row(SubstanceDilutionFactor="5",
                             StatisticalBaseCode="Mean",
                             ResultWeightBasisText="Dry"))
    assert out[0]["__wqx_method_dilution_key"] == "5|Mean|Dry"


def test_dilution_key_single_component():
    out, _ = _transform(_row(SubstanceDilutionFactor="10"))
    assert out[0]["__wqx_method_dilution_key"] == "10"


def test_dilution_key_basis_folds_unconditionally():
    # No dual-reported twin needed — the fold must be per-row deterministic
    # so re-imports across batches compute identical keys.
    out, _ = _transform(_row(ResultWeightBasisText="Wet"))
    assert out[0]["__wqx_method_dilution_key"] == "Wet"


def test_dilution_key_empty_when_no_discriminators():
    out, _ = _transform(_row())
    assert out[0]["__wqx_method_dilution_key"] == ""


# ---------------------------------------------------------------------------
# Speciation fold (D6) + matrix coalesce (D2 companion)
# ---------------------------------------------------------------------------

def test_speciation_folds_into_analyte():
    out, _ = _transform(_row(CharacteristicName="Nitrate",
                             MethodSpeciationName="as N"))
    assert out[0]["__wqx_analyte"] == "Nitrate as N"


def test_no_speciation_analyte_unchanged():
    out, _ = _transform(_row())
    assert out[0]["__wqx_analyte"] == "Benzene"


def test_matrix_prefers_subdivision():
    out, _ = _transform(_row())
    assert out[0]["__wqx_matrix"] == "Groundwater"


def test_matrix_falls_back_to_media_on_empty_subdivision():
    out, _ = _transform(_row(ActivityMediaSubdivisionName=""))
    assert out[0]["__wqx_matrix"] == "Water"


# ---------------------------------------------------------------------------
# Row status (D10) + ActivityTypeCode (D11)
# ---------------------------------------------------------------------------

def test_rejected_row_skipped_with_warn():
    qa = QACollector()
    out = transform_wqx_rows(
        [_row(ResultStatusIdentifier="Rejected"), _row()], PROFILE, qa)
    assert len(out) == 1
    assert "wqx_rejected_row_skipped" in _categories(qa)


def test_source_rows_survive_a_skipped_row():
    qa = QACollector()
    out = transform_wqx_rows(
        [_row(ResultStatusIdentifier="Rejected"), _row()], PROFILE, qa)
    assert out[0]["__source_row"] == 3        # true source row, not re-numbered


def test_unmapped_activity_type_warns():
    out, qa = _transform(_row(
        ActivityTypeCode="Quality Control Sample-Reference Material"))
    assert len(out) == 1                    # imported (fail-safe: QC-flagged)
    assert "wqx_unmapped_activity_type" in _categories(qa)


def test_mapped_activity_types_do_not_warn():
    _, qa = _transform(_row(
        ActivityTypeCode="Quality Control Sample-Field Replicate"))
    assert _categories(qa) == []


# ---------------------------------------------------------------------------
# End-to-end: CSV -> read_edd_file -> normalize_edd_rows -> records
# ---------------------------------------------------------------------------

ANALYTES = {
    "Benzene": {"aliases": ["benzene"], "abbreviation": "BNZ",
                "analytical_group": "VOC", "method_group": "EPA8260"},
    "Nitrate as N": {"aliases": [], "abbreviation": "NO3-N",
                     "analytical_group": "NUTRIENT", "method_group": "EPA300"},
}


def _write_csv(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "wqp_export.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_end_to_end_wqp_csv(tmp_path):
    rows = [
        # Total/Dissolved pair on the SAME grain — the Step-1 collision case.
        _row(ResultSampleFractionText="Total", ResultMeasureValue="5.0"),
        _row(ResultSampleFractionText="Dissolved", ResultMeasureValue="1.0"),
        # Field replicate -> QCType=FIELD_DUP
        _row(ActivityTypeCode="Quality Control Sample-Field Replicate",
             ResultMeasureValue="4.8"),
        # Non-detect the way WQP really emits it: no result value AND no
        # result unit — Units must fall back to the limit's unit, unconverted.
        _row(ResultMeasureValue="",
             ResultDetectionConditionText="Not Detected",
             **{"ResultMeasure/MeasureUnitCode": "",
                "DetectionQuantitationLimitTypeName": "Method Detection Level",
                "DetectionQuantitationLimitMeasure/MeasureValue": "200",
                "DetectionQuantitationLimitMeasure/MeasureUnitCode": "ng/L"}),
        # Rejected row — must not import
        _row(ResultStatusIdentifier="Rejected"),
        # Speciated nutrient
        _row(CharacteristicName="Nitrate", MethodSpeciationName="as N",
             ResultMeasureValue="2.5",
             **{"ResultMeasure/MeasureUnitCode": "mg/L"}),
    ]
    path = _write_csv(tmp_path, rows)

    qa = QACollector()
    flat = read_edd_file(path, PROFILE, qa)
    assert len(flat) == 5                       # rejected row dropped
    assert "wqx_rejected_row_skipped" in _categories(qa)

    samples, results = normalize_edd_rows(
        rows=flat, profile=PROFILE, site_id="S1", batch_id="B1",
        analyte_dictionary=ANALYTES, screening_levels={}, qa=qa)
    assert len(results) == 5

    total, dissolved, dup, nd, nitrate = results

    # Frozen Step-1 fields land end-to-end.
    assert total.ResultFraction == "Total"
    assert dissolved.ResultFraction == "Dissolved"
    assert total.Matrix == "GW"                 # Groundwater -> GW via matrix_map
    assert total.MethodID == "EPA 8260D"
    assert total.MethodName == "VOC by GC/MS"
    assert total.AnalysisDate == date(2026, 6, 20)
    assert total.LabName == "Acme Labs"
    assert total.PrepMethodID == "EPA 5030C"
    assert total.PrepDate == date(2026, 6, 18)
    assert total.SampleDate == date(2026, 6, 15)
    assert total.ResultNumeric == 5.0

    # QC discriminator
    assert dup.QCType == "FIELD_DUP"
    assert total.QCType == ""

    # ND: synthesized token + DL-routed limit; with no result unit the record's
    # Units is the limit's unit and the value stays in it (consistent pair).
    assert nd.IsNonDetect == 1
    assert nd.ResultNumeric is None
    assert nd.DetectionLimit == 200.0
    assert nd.Units == "ng/L"
    assert nd.LimitType == "Method Detection Level"

    # Provenance: the record AFTER the rejected row keeps its true source row.
    assert nitrate.SourceRow == 7               # not re-numbered to 6

    # Speciation fold reaches the canonical name (key safety)
    assert nitrate.AnalyteCanonicalName == "Nitrate as N"
    assert nitrate.MethodSpeciation == "as N"

    # Key distinctness: the Total/Dissolved pair must NOT collide.
    key_total = compute_unique_key(dataclasses.asdict(total),
                                   "Env_AnalyticalResults")
    key_dissolved = compute_unique_key(dataclasses.asdict(dissolved),
                                       "Env_AnalyticalResults")
    assert key_total != key_dissolved
    # ...and the QC row is key-distinct from its routine twin too.
    key_dup = compute_unique_key(dataclasses.asdict(dup),
                                 "Env_AnalyticalResults")
    assert key_dup not in (key_total, key_dissolved)


def test_batch_import_surfaces_wqx_reader_qa(tmp_path):
    # Regression (cold review F1): run_batch_import must thread its collector
    # into read_edd_file, or every reader warning vanishes silently.
    from autogis.core.envmon.batch_workbook_importer import run_batch_import

    path = _write_csv(tmp_path, [_row(ResultStatusIdentifier="Rejected"),
                                 _row()])
    qa = QACollector()
    result = run_batch_import(
        [{"workbook_path": str(path), "profile_path": str(PROFILE_PATH),
          "site_id": "S1"}],
        analyte_dictionary=ANALYTES, qa=qa)
    assert len(result.all_results) == 1
    assert "wqx_rejected_row_skipped" in _categories(qa)


def test_run_edd_import_caller_collector_gets_wqx_reader_qa(tmp_path, monkeypatch):
    # Reconciliation with PR #225 (review finding on #226): run_edd_import
    # accepts a caller-owned QACollector, initializes it BEFORE the read so
    # WQX reader warnings land in it, and the SAME collector reaches the GDB
    # QA write.
    import autogis.core.envmon.edd_importer as mod

    seen = {}
    monkeypatch.setattr(mod, "create_or_update_gdb_schema", lambda g, qa=None: None)
    monkeypatch.setattr(mod, "create_edd_import_batch",
                        lambda *a, **k: "BATCH-001")
    monkeypatch.setattr(mod, "append_records_idempotent",
                        lambda g, t, r, qa, b: (len(r), 0))
    monkeypatch.setattr(mod, "finalize_batch", lambda g, b, qa, c, s: None)
    monkeypatch.setattr(mod, "write_qa_to_gdb",
                        lambda g, qa, b: seen.setdefault("qa", qa))

    path = _write_csv(tmp_path, [_row(ResultStatusIdentifier="Rejected"),
                                 _row()])
    caller_qa = QACollector()
    batch_id = mod.run_edd_import(
        edd_path=path, profile=PROFILE, gdb_path=tmp_path / "t.gdb",
        site_id="S1", analyte_dictionary=ANALYTES, screening_levels={},
        qa=caller_qa)
    assert batch_id == "BATCH-001"
    assert "wqx_rejected_row_skipped" in _categories(caller_qa)
    assert seen["qa"] is caller_qa               # same object, GDB-written


def test_speciated_alias_must_map_to_speciated_canonical():
    # Guard for the D6 dictionary rule: an alias that strips speciation
    # ("Nitrate as N" -> "Nitrate") would recreate the as-N/as-NO3 key
    # collision. The shipped analyte dictionary must never do that.
    from autogis.core.common.config import load_config
    dict_path = (Path(autogis.__file__).parent / "config" / "analytes"
                 / "analyte_dictionary.yaml")
    data = load_config(dict_path)
    for canonical, entry in data.items():
        if canonical.startswith("_") or not isinstance(entry, dict):
            continue
        for alias in entry.get("aliases", []) or []:
            a = str(alias).lower()
            if " as " in f" {a} ":
                assert " as " in f" {canonical.lower()} ", (
                    f"speciated alias '{alias}' maps to unspeciated "
                    f"canonical '{canonical}' — strips speciation post-fold")
