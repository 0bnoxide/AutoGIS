from __future__ import annotations
import textwrap
from pathlib import Path
import pytest
from autogis.core.envmon.edd_profile import LabEDDProfile, validate_edd_profile
from autogis.core.common.qa import QACollector, SEV_ERROR


def _write_yaml(tmp_path, content: str) -> Path:
    p = tmp_path / "test.yaml"
    p.write_text(content, encoding="utf-8")
    return p


MINIMAL_YAML = textwrap.dedent("""
    profile_id: test_lab
    lab_name: Test Lab
    format: flat_csv
    date_format: "%m/%d/%Y"
    encoding: utf-8
    columns:
      sample_id: SampleID
      location_id: LocationID
      event_date: CollDate
      matrix: Medium
      analyte: Chemical
      result: Result
      units: Unit
      qualifier: Qual
      reporting_limit: RL
    matrix_map:
      WS: GW
    nondetect_qualifiers:
      - U
      - UJ
""").strip()


def test_load_returns_profile(tmp_path):
    p = _write_yaml(tmp_path, MINIMAL_YAML)
    profile = LabEDDProfile.load(p)
    assert profile.profile_id == "test_lab"
    assert profile.lab_name == "Test Lab"
    assert profile.format == "flat_csv"
    assert profile.date_format == "%m/%d/%Y"
    assert profile.encoding == "utf-8"
    assert profile.matrix_map == {"WS": "GW"}
    assert profile.nondetect_qualifiers == ["U", "UJ"]
    assert profile.path == p


def test_load_defaults_for_xlsx_sheets(tmp_path):
    p = _write_yaml(tmp_path, MINIMAL_YAML)
    profile = LabEDDProfile.load(p)
    assert profile.sample_sheet == "Samples"
    assert profile.result_sheet == "Results"


def test_load_overrides_xlsx_sheets(tmp_path):
    yaml = MINIMAL_YAML + "\nsample_sheet: SampleData\nresult_sheet: ResultData\n"
    p = _write_yaml(tmp_path, yaml)
    profile = LabEDDProfile.load(p)
    assert profile.sample_sheet == "SampleData"
    assert profile.result_sheet == "ResultData"


def test_resolve_column_string_match(tmp_path):
    p = _write_yaml(tmp_path, MINIMAL_YAML)
    profile = LabEDDProfile.load(p)
    row = {"SampleID": "S-001", "LocationID": "MW-1"}
    assert profile.resolve_column(row, "sample_id") == "S-001"


def test_resolve_column_list_first_match(tmp_path):
    yaml = MINIMAL_YAML.replace("sample_id: SampleID",
                                "sample_id:\n      - SampleRef\n      - SampleID")
    p = _write_yaml(tmp_path, yaml)
    profile = LabEDDProfile.load(p)
    # "SampleRef" not present, falls back to "SampleID"
    row = {"SampleID": "S-001"}
    assert profile.resolve_column(row, "sample_id") == "S-001"


def test_resolve_column_list_prefers_first(tmp_path):
    yaml = MINIMAL_YAML.replace("sample_id: SampleID",
                                "sample_id:\n      - SampleRef\n      - SampleID")
    p = _write_yaml(tmp_path, yaml)
    profile = LabEDDProfile.load(p)
    row = {"SampleRef": "primary", "SampleID": "fallback"}
    assert profile.resolve_column(row, "sample_id") == "primary"


def test_resolve_column_missing_field_returns_none(tmp_path):
    p = _write_yaml(tmp_path, MINIMAL_YAML)
    profile = LabEDDProfile.load(p)
    row = {"SampleID": "S-001"}
    # "depth_top_ft" not in columns
    assert profile.resolve_column(row, "depth_top_ft") is None


def test_resolve_column_missing_value_returns_none(tmp_path):
    p = _write_yaml(tmp_path, MINIMAL_YAML)
    profile = LabEDDProfile.load(p)
    row = {}   # SampleID column not present in row
    assert profile.resolve_column(row, "sample_id") is None


def test_validate_edd_profile_happy_path(tmp_path):
    p = _write_yaml(tmp_path, MINIMAL_YAML)
    profile = LabEDDProfile.load(p)
    qa = QACollector()
    validate_edd_profile(profile, qa)
    assert not any(r.severity == SEV_ERROR for r in qa.records)


def test_validate_edd_profile_bad_format(tmp_path):
    yaml = MINIMAL_YAML.replace("format: flat_csv", "format: excel_grid")
    p = _write_yaml(tmp_path, yaml)
    profile = LabEDDProfile.load(p)
    qa = QACollector()
    validate_edd_profile(profile, qa)
    assert any(r.severity == SEV_ERROR and "format" in r.message for r in qa.records)


def test_value_maps_defaults_empty_and_maps_pass_through(tmp_path):
    p = _write_yaml(tmp_path, MINIMAL_YAML)
    prof = LabEDDProfile.load(p)
    assert prof.map_value("qc_type", "TB") == "TB"        # unmapped: pass-through
    assert prof.map_value("result_fraction", "") == ""


def test_matrix_map_merged_into_value_maps(tmp_path):
    p = _write_yaml(tmp_path, MINIMAL_YAML)
    prof = LabEDDProfile.load(p)
    assert prof.value_maps["matrix"] == prof.matrix_map
    assert prof.map_value("matrix", next(iter(prof.matrix_map))) \
        == prof.matrix_map[next(iter(prof.matrix_map))]


def test_value_maps_loaded_from_yaml(tmp_path):
    yaml_text = MINIMAL_YAML + textwrap.dedent("""
        value_maps:
          qc_type:
            "TB": "TRIP_BLANK"
          result_fraction:
            "T": "Total"
        """)
    p = _write_yaml(tmp_path, yaml_text)
    prof = LabEDDProfile.load(p)
    assert prof.map_value("qc_type", "TB") == "TRIP_BLANK"
    assert prof.map_value("result_fraction", "T") == "Total"
    assert prof.value_maps["matrix"]          # matrix_map still merged in


def test_validate_edd_profile_missing_required_column(tmp_path):
    yaml = textwrap.dedent("""
    profile_id: test_lab
    lab_name: Test Lab
    format: flat_csv
    date_format: "%m/%d/%Y"
    encoding: utf-8
    columns:
      location_id: LocationID
      event_date: CollDate
      matrix: Medium
      analyte: Chemical
      result: Result
      units: Unit
      qualifier: Qual
      reporting_limit: RL
    matrix_map:
      WS: GW
    nondetect_qualifiers:
      - U
      - UJ
    """).strip()
    p = _write_yaml(tmp_path, yaml)
    profile = LabEDDProfile.load(p)
    qa = QACollector()
    validate_edd_profile(profile, qa)
    assert any(r.severity == SEV_ERROR and "sample_id" in r.message for r in qa.records)


def test_equis_xls_is_valid_format():
    profile = LabEDDProfile(
        profile_id="p", lab_name="l", format="equis_xls",
        date_format="%m/%d/%Y", encoding="utf-8",
        columns={c: "x" for c in ("sample_id", "location_id", "event_date",
                                  "matrix", "analyte", "result", "units",
                                  "qualifier", "reporting_limit")},
        matrix_map={}, nondetect_qualifiers=[],
    )
    qa = QACollector()
    validate_edd_profile(profile, qa)
    assert not qa.has_blocking()


def test_batch_sheet_defaults_empty_and_loads(tmp_path):
    p = tmp_path / "prof.yaml"
    p.write_text(
        "profile_id: p\nformat: equis_xls\n"
        "sample_sheet: Sample_v1\nresult_sheet: TestResultQC_v1\n"
        "batch_sheet: Batch_v1\ncolumns: {}\n",
        encoding="utf-8")
    prof = LabEDDProfile.load(p)
    assert prof.batch_sheet == "Batch_v1"
    assert LabEDDProfile(
        profile_id="p", lab_name="l", format="equis_xls",
        date_format="%m/%d/%Y", encoding="utf-8", columns={},
        matrix_map={}, nondetect_qualifiers=[],
    ).batch_sheet == ""
