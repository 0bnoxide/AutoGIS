"""LabEDD profile drafter (Tool 2.3a) + validate-lab-profile CLI.

Core matching tests are arcpy-free and file-light (tmp_path fixtures built
inline). Spec: docs/superpowers/specs/2026-07-08-lab-profile-drafting-tooling-design.md.
"""
from pathlib import Path

import openpyxl
import pytest
import yaml
from click.testing import CliRunner

from autogis.adapters.cli import autogis
from autogis.core.common.qa import QACollector
from autogis.core.envmon.edd_profile import LabEDDProfile, validate_edd_profile
from autogis.core.envmon.edd_profile_draft import (
    REQUIRED_FIELDS,
    draft_edd_profile,
    drafted_profile_to_yaml_dict,
)

TESTAMERICA_HEADER = ("SysLocCode,CollDate,Medium,Chemical,Result,Unit,"
                      "Qualifier,RL,AnalytMeth,LabID,TopDepth,BotDepth\n")


def _run(*args):
    return CliRunner().invoke(autogis, list(args), catch_exceptions=False)


def _field(drafted, name):
    return next(f for f in drafted.fields if f.canonical_name == name)


# ---------------------------------------------------------------------------
# Core: flat_csv matching
# ---------------------------------------------------------------------------

def test_flat_csv_confirmed_matches(tmp_path):
    p = tmp_path / "testamerica_export.csv"
    p.write_text(TESTAMERICA_HEADER + "MW-1,01/02/2026,WG,Benzene,5,ug/L,,1,"
                 "8260,L1,,\n", encoding="utf-8")
    drafted = draft_edd_profile(p)
    assert drafted.format == "flat_csv"
    assert drafted.encoding == "utf-8"
    for name, col in [("sample_id", "SysLocCode"), ("location_id", "SysLocCode"),
                      ("event_date", "CollDate"), ("matrix", "Medium"),
                      ("analyte", "Chemical"), ("result", "Result"),
                      ("units", "Unit"), ("qualifier", "Qualifier"),
                      ("reporting_limit", "RL"), ("method", "AnalytMeth"),
                      ("lab_sample_id", "LabID"), ("depth_top_ft", "TopDepth"),
                      ("depth_bot_ft", "BotDepth")]:
        f = _field(drafted, name)
        assert f.status == "CONFIRMED", f"{name}: {f}"
        assert f.matched_column == col


def test_flat_csv_zero_match_needs_review(tmp_path):
    p = tmp_path / "odd.csv"
    p.write_text("Foo,Bar,SampleID\n1,2,S-1\n", encoding="utf-8")
    drafted = draft_edd_profile(p)
    assert _field(drafted, "sample_id").status == "CONFIRMED"
    analyte = _field(drafted, "analyte")
    assert analyte.status == "NEEDS_REVIEW"
    assert analyte.candidates == ()


def test_flat_csv_ambiguous_records_candidates(tmp_path):
    p = tmp_path / "ambig.csv"
    p.write_text("Result,Result Value,Analyte\n1,2,Benzene\n", encoding="utf-8")
    drafted = draft_edd_profile(p)
    result = _field(drafted, "result")
    assert result.status == "NEEDS_REVIEW"
    assert set(result.candidates) == {"Result", "Result Value"}
    assert result.matched_column is None


def test_flat_csv_bom_detected_as_utf8_sig(tmp_path):
    p = tmp_path / "bom.csv"
    p.write_bytes(b"\xef\xbb\xbf" + TESTAMERICA_HEADER.encode())
    drafted = draft_edd_profile(p)
    assert drafted.encoding == "utf-8-sig"
    assert _field(drafted, "analyte").matched_column == "Chemical"


def test_empty_csv_raises(tmp_path):
    p = tmp_path / "empty.csv"
    p.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="No header row"):
        draft_edd_profile(p)


# ---------------------------------------------------------------------------
# Core: two_tab_xlsx detection
# ---------------------------------------------------------------------------

def _xlsx(tmp_path, sheets: dict) -> Path:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, header in sheets.items():
        ws = wb.create_sheet(name)
        if header:
            ws.append(header)
    p = tmp_path / "edd.xlsx"
    wb.save(p)
    return p


def test_two_tab_xlsx_default_sheet_names(tmp_path):
    p = _xlsx(tmp_path, {
        "Samples": ["Sample ID", "Collection Date", "Matrix"],
        "Results": ["Sample ID", "Analyte", "Result", "Units", "Qualifier",
                    "Reporting Limit"],
    })
    drafted = draft_edd_profile(p)
    assert drafted.format == "two_tab_xlsx"
    assert (drafted.sample_sheet, drafted.result_sheet) == ("Samples", "Results")
    assert drafted.notes == ()
    # same header name on both sheets dedups to one unambiguous match
    assert _field(drafted, "sample_id").matched_column == "Sample ID"
    assert _field(drafted, "analyte").matched_column == "Analyte"


def test_two_tab_xlsx_fallback_sheet_order_is_flagged(tmp_path):
    p = _xlsx(tmp_path, {
        "Meta": ["Sample ID", "Collection Date"],
        "Data": ["Sample ID", "Analyte", "Result"],
    })
    drafted = draft_edd_profile(p)
    assert (drafted.sample_sheet, drafted.result_sheet) == ("Meta", "Data")
    assert any("VERIFY" in n for n in drafted.notes)


def test_single_sheet_xlsx_identity_merge(tmp_path):
    p = _xlsx(tmp_path, {"Export": ["Sample ID", "Analyte", "Result"]})
    drafted = draft_edd_profile(p)
    assert drafted.sample_sheet == drafted.result_sheet == "Export"
    assert any("Single-sheet" in n for n in drafted.notes)


def test_headerless_xlsx_raises(tmp_path):
    p = _xlsx(tmp_path, {"Blank": []})
    with pytest.raises(ValueError, match="No header row"):
        draft_edd_profile(p)


# ---------------------------------------------------------------------------
# Core: YAML dict assembly + round-trip through LabEDDProfile
# ---------------------------------------------------------------------------

def test_yaml_dict_omits_needs_review_and_lists_todos(tmp_path):
    p = tmp_path / "partial.csv"
    p.write_text("SampleID,Analyte,Result,Result Value\nS-1,Benzene,1,1\n",
                 encoding="utf-8")
    d = drafted_profile_to_yaml_dict(draft_edd_profile(p), "DRAFT", "somelab")
    assert d["columns"]["sample_id"] == "SampleID"
    assert "result" not in d["columns"]          # ambiguous -> omitted
    assert "matrix" not in d["columns"]          # zero-match -> omitted
    todos = "\n".join(d["_TODO"])
    assert "result (REQUIRED): ambiguous" in todos
    assert "Result Value" in todos
    assert "matrix (REQUIRED): no match found" in todos


def test_full_draft_round_trips_and_validates(tmp_path):
    p = tmp_path / "full.csv"
    p.write_text(TESTAMERICA_HEADER, encoding="utf-8")
    d = drafted_profile_to_yaml_dict(draft_edd_profile(p), "DRAFT_acme", "Acme")
    out = tmp_path / "profile.yaml"
    out.write_text(yaml.dump(d, sort_keys=False), encoding="utf-8")
    profile = LabEDDProfile.load(out)
    qa = QACollector()
    validate_edd_profile(profile, qa)
    assert not qa.has_blocking(), [r.message for r in qa.records]
    assert set(REQUIRED_FIELDS) <= set(profile.columns)


# ---------------------------------------------------------------------------
# CLI: draft-edd-profile / validate-lab-profile
# ---------------------------------------------------------------------------

def test_cli_draft_edd_profile(tmp_path):
    src = tmp_path / "acme_export.csv"
    src.write_text(TESTAMERICA_HEADER, encoding="utf-8")
    out = tmp_path / "acme.yaml"
    res = _run("envmon", "draft-edd-profile", str(src), "--output", str(out))
    assert res.exit_code == 0, res.output
    assert "Draft profile written" in res.output
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert data["lab_name"] == "acme_export"     # default: file stem
    assert data["profile_id"] == "DRAFT"
    assert data["columns"]["analyte"] == "Chemical"


def test_cli_draft_edd_profile_empty_file_errors(tmp_path):
    src = tmp_path / "empty.csv"
    src.write_text("", encoding="utf-8")
    res = CliRunner().invoke(
        autogis, ["envmon", "draft-edd-profile", str(src),
                  "--output", str(tmp_path / "x.yaml")])
    assert res.exit_code != 0
    assert "No header row" in res.output


def test_cli_validate_lab_profile_pass_and_fail(tmp_path):
    good = tmp_path / "good.yaml"
    good.write_text(yaml.dump({
        "profile_id": "acme", "format": "flat_csv",
        "columns": {f: f for f in REQUIRED_FIELDS},
    }), encoding="utf-8")
    res = _run("envmon", "validate-lab-profile", str(good))
    assert res.exit_code == 0, res.output

    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.dump({
        "profile_id": "acme", "format": "flat_csv",
        "columns": {"sample_id": "SampleID"},     # 8 required mappings missing
    }), encoding="utf-8")
    res = CliRunner().invoke(
        autogis, ["envmon", "validate-lab-profile", str(bad)])
    assert res.exit_code == 1
    assert "edd_profile_missing_column" in res.output


def test_cli_validate_lab_profile_unloadable_errors(tmp_path):
    broken = tmp_path / "broken.yaml"
    broken.write_text("lab_name: no profile_id here\n", encoding="utf-8")
    res = CliRunner().invoke(
        autogis, ["envmon", "validate-lab-profile", str(broken)])
    assert res.exit_code != 0
    assert "Cannot load profile" in res.output
