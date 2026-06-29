from pathlib import Path
import csv
import pytest
from autogis.core.envmon.event_results_merger import (
    SourceFile, MergeResult, infer_event_label,
    merge_event_results, write_merge_manifest,
)


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow(r)


_ROW_A = {"SampleID": "S1", "AnalyteName": "Benzene",
          "ReportedUnits": "ug/L", "ResultValue": "5.0",
          "LocationID": "MW-01", "SampleDate": "2026-01-15"}
_ROW_B = {"SampleID": "S2", "AnalyteName": "Benzene",
          "ReportedUnits": "ug/L", "ResultValue": "12.0",
          "LocationID": "MW-01", "SampleDate": "2026-06-15"}
_ROW_DUP = dict(_ROW_A)  # same SampleID, AnalyteName, Units


def test_merge_two_files(tmp_path):
    f1 = tmp_path / "Env_Results_20260115.csv"
    f2 = tmp_path / "Env_Results_20260615.csv"
    _write_csv(f1, [_ROW_A])
    _write_csv(f2, [_ROW_B])
    out = tmp_path / "merged.csv"
    manifest = tmp_path / "manifest.csv"
    result = merge_event_results([f1, f2], out, manifest_path=manifest)
    assert result.total_rows == 2
    assert result.duplicate_rows_dropped == 0


def test_deduplication(tmp_path):
    f1 = tmp_path / "Env_Results_20260115.csv"
    f2 = tmp_path / "Env_Results_20260615.csv"
    _write_csv(f1, [_ROW_A])
    _write_csv(f2, [_ROW_DUP])  # same key as f1
    out = tmp_path / "merged.csv"
    result = merge_event_results([f1, f2], out)
    assert result.total_rows == 1
    assert result.duplicate_rows_dropped == 1


def test_event_label_added(tmp_path):
    f1 = tmp_path / "Env_Results_20260115.csv"
    _write_csv(f1, [_ROW_A])
    out = tmp_path / "merged.csv"
    merge_event_results([f1], out, event_labels=["Q1-2026"])
    with out.open() as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0].get("EventLabel") == "Q1-2026"


def test_infer_event_label_date():
    p = Path("Env_Results_20260615_GW.csv")
    assert infer_event_label(p) == "20260615"


def test_infer_event_label_fallback():
    p = Path("custom_export.csv")
    assert infer_event_label(p) == "custom_export"


def test_manifest_written(tmp_path):
    f1 = tmp_path / "Env_Results_20260115.csv"
    _write_csv(f1, [_ROW_A])
    out = tmp_path / "merged.csv"
    manifest = tmp_path / "manifest.csv"
    merge_event_results([f1], out, manifest_path=manifest)
    assert manifest.exists()
    with manifest.open() as fh:
        rows = list(csv.DictReader(fh))
    assert "sha256" in rows[0]


def test_missing_source_error(tmp_path):
    f1 = tmp_path / "nonexistent.csv"
    out = tmp_path / "merged.csv"
    result = merge_event_results([f1], out)
    assert any(r.severity == "ERROR" for r in result.qa.records)


def test_single_file_valid(tmp_path):
    f1 = tmp_path / "Env_Results_20260615.csv"
    _write_csv(f1, [_ROW_A])
    out = tmp_path / "merged.csv"
    result = merge_event_results([f1], out)
    assert result.total_rows == 1


def test_empty_dedup_key_keeps_all_rows(tmp_path):
    # An empty dedup_key (the --no-dedup flag) must DISABLE dedup, not collapse
    # every row to the same empty key and drop all but the first.
    f1 = tmp_path / "Env_Results_20260115.csv"
    f2 = tmp_path / "Env_Results_20260615.csv"
    _write_csv(f1, [_ROW_A])
    _write_csv(f2, [_ROW_DUP])  # identical key to _ROW_A
    out = tmp_path / "merged.csv"
    result = merge_event_results([f1, f2], out, dedup_key=())
    assert result.total_rows == 2
    assert result.duplicate_rows_dropped == 0
