"""CLI smoke tests for the §2/§7 intake + planning batch (5 headless tools).

Each test:
1. Builds minimal valid inputs under tmp_path.
2. Invokes the CLI via CliRunner (catch_exceptions=False).
3. Asserts exit_code == 0 and output file(s) exist with expected content.

No arcpy, no arcgis. Only touches tests/envmon/.
"""
import csv
import json
from pathlib import Path

import openpyxl
import pytest
import yaml
from click.testing import CliRunner

from autogis.adapters.cli import autogis


def _run(*args):
    return CliRunner().invoke(autogis, list(args), catch_exceptions=False)


def _write_csv(path: Path, rows: list) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow(r)


# ---------------------------------------------------------------------------
# 1. draft-parser-profile (Tool 2.1)
# ---------------------------------------------------------------------------

class TestDraftParserProfile:
    def test_creates_draft_yaml(self, tmp_path):
        """A single-sheet workbook produces a YAML draft profile."""
        wb_path = tmp_path / "lab.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Results"
        ws.append(["LocationID", "SampleDate", "Benzene", "Toluene"])
        ws.append(["MW-01", "2024-06-01", "12.3", "ND"])
        wb.save(str(wb_path))

        out = tmp_path / "draft.yaml"
        r = _run("envmon", "draft-parser-profile", str(wb_path),
                 "--output", str(out), "--profile-id", "TEST_DRAFT")
        assert r.exit_code == 0, r.output
        assert out.exists()
        profile = yaml.safe_load(out.read_text(encoding="utf-8"))
        assert profile["profile_id"] == "TEST_DRAFT"
        assert "sheets" in profile
        assert len(profile["sheets"]) >= 1
        assert "_TODO" in profile["sheets"][0]

    def test_multi_sheet_workbook(self, tmp_path):
        wb_path = tmp_path / "multi.xlsx"
        wb = openpyxl.Workbook()
        wb.active.title = "Sheet1"
        wb.active.append(["ID", "Date", "Analyte"])
        wb.create_sheet("Sheet2")
        wb["Sheet2"].append(["ID", "Date", "Analyte"])
        wb.save(str(wb_path))

        out = tmp_path / "multi_draft.yaml"
        r = _run("envmon", "draft-parser-profile", str(wb_path),
                 "--output", str(out))
        assert r.exit_code == 0, r.output
        profile = yaml.safe_load(out.read_text(encoding="utf-8"))
        assert len(profile["sheets"]) == 2


# ---------------------------------------------------------------------------
# 2. batch-import-workbooks (Tool 2.2)
# ---------------------------------------------------------------------------

class TestBatchImportWorkbooks:
    def _make_edd_profile(self, path: Path) -> None:
        import textwrap
        profile_yaml = textwrap.dedent("""
            profile_id: TEST_PROFILE
            lab_name: Test Lab
            format: flat_csv
            date_format: "%Y-%m-%d"
            encoding: utf-8
            columns:
              sample_id:       SampleID
              location_id:     LocationID
              event_date:      SampleDate
              matrix:          Matrix
              analyte:         Analyte
              result:          Result
              units:           Units
              qualifier:       Qualifier
              reporting_limit: RL
            matrix_map:
              GW: GW
            nondetect_qualifiers:
              - U
        """).strip()
        path.write_text(profile_yaml, encoding="utf-8")

    def _make_edd_csv(self, path: Path) -> None:
        rows = [
            {"SampleID": "S-001", "LocationID": "MW-01", "SampleDate": "2024-06-01",
             "Matrix": "GW", "Analyte": "Benzene", "Result": "12.3",
             "Units": "ug/L", "Qualifier": "", "RL": "1.0"},
        ]
        _write_csv(path, rows)

    def test_batch_processes_one_workbook(self, tmp_path):
        prof_path = tmp_path / "profile.yaml"
        wb_path = tmp_path / "lab_edd.csv"
        self._make_edd_profile(prof_path)
        self._make_edd_csv(wb_path)

        manifest_path = tmp_path / "manifest.csv"
        _write_csv(manifest_path, [{"workbook_path": str(wb_path),
                                    "profile_path": str(prof_path),
                                    "site_id": "SITE-A"}])
        out_dir = tmp_path / "out"

        r = _run("envmon", "batch-import-workbooks",
                 "--manifest", str(manifest_path),
                 "--output-dir", str(out_dir))
        assert r.exit_code == 0, r.output
        manifest_out = out_dir / "batch_manifest.csv"
        assert manifest_out.exists()
        with manifest_out.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 1
        assert rows[0]["Status"] == "OK"

    def test_missing_workbook_marked_skip(self, tmp_path):
        prof_path = tmp_path / "profile.yaml"
        self._make_edd_profile(prof_path)
        manifest_path = tmp_path / "manifest.csv"
        _write_csv(manifest_path, [{"workbook_path": "/no/such/file.csv",
                                    "profile_path": str(prof_path),
                                    "site_id": "SITE-A"}])
        out_dir = tmp_path / "out"
        r = _run("envmon", "batch-import-workbooks",
                 "--manifest", str(manifest_path),
                 "--output-dir", str(out_dir))
        assert r.exit_code == 0, r.output
        with (out_dir / "batch_manifest.csv").open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert rows[0]["Status"] == "SKIP"

    # --- --edd-dir alternate input mode (BatchEDDImport fold, ADR-0048) ---

    def test_edd_dir_mode_imports_directory(self, tmp_path):
        """Directory of EDD CSVs + one shared profile/site imports every file."""
        prof_path = tmp_path / "profile.yaml"
        self._make_edd_profile(prof_path)
        edd_dir = tmp_path / "edds"
        edd_dir.mkdir()
        self._make_edd_csv(edd_dir / "a.csv")
        self._make_edd_csv(edd_dir / "b.csv")
        out_dir = tmp_path / "out"

        r = _run("envmon", "batch-import-workbooks",
                 "--edd-dir", str(edd_dir),
                 "--profile", str(prof_path),
                 "--site", "SITE-A",
                 "--output-dir", str(out_dir))
        assert r.exit_code == 0, r.output
        with (out_dir / "batch_manifest.csv").open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 2
        assert all(row["Status"] == "OK" for row in rows)
        assert all(row["SiteID"] == "SITE-A" for row in rows)
        with (out_dir / "sample_records.csv").open(encoding="utf-8") as fh:
            samples = list(csv.DictReader(fh))
        assert len(samples) == 2

    def test_edd_dir_per_file_failure_does_not_abort(self, tmp_path):
        """One unreadable file is marked ERROR; the rest still import."""
        prof_path = tmp_path / "profile.yaml"
        self._make_edd_profile(prof_path)
        edd_dir = tmp_path / "edds"
        edd_dir.mkdir()
        self._make_edd_csv(edd_dir / "good.csv")
        (edd_dir / "bad.csv").write_bytes(b"\xff\xfe\x00\x00not utf-8\xff")
        out_dir = tmp_path / "out"

        r = _run("envmon", "batch-import-workbooks",
                 "--edd-dir", str(edd_dir),
                 "--profile", str(prof_path),
                 "--site", "SITE-A",
                 "--output-dir", str(out_dir))
        assert r.exit_code == 1  # SEV_ERROR recorded -> fail-on=error default
        with (out_dir / "batch_manifest.csv").open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        statuses = {Path(row["WorkbookPath"]).name: row["Status"] for row in rows}
        assert statuses == {"good.csv": "OK", "bad.csv": "ERROR"}
        with (out_dir / "sample_records.csv").open(encoding="utf-8") as fh:
            samples = list(csv.DictReader(fh))
        assert len(samples) == 1  # good.csv still imported

    def test_manifest_and_edd_dir_mutually_exclusive(self, tmp_path):
        prof_path = tmp_path / "profile.yaml"
        self._make_edd_profile(prof_path)
        wb_path = tmp_path / "lab_edd.csv"
        self._make_edd_csv(wb_path)
        manifest_path = tmp_path / "manifest.csv"
        _write_csv(manifest_path, [{"workbook_path": str(wb_path),
                                    "profile_path": str(prof_path),
                                    "site_id": "SITE-A"}])
        r = _run("envmon", "batch-import-workbooks",
                 "--manifest", str(manifest_path),
                 "--edd-dir", str(tmp_path),
                 "--profile", str(prof_path),
                 "--site", "SITE-A",
                 "--output-dir", str(tmp_path / "out"))
        assert r.exit_code == 2  # UsageError: both input modes supplied

    def test_input_mode_required(self, tmp_path):
        r = _run("envmon", "batch-import-workbooks",
                 "--output-dir", str(tmp_path / "out"))
        assert r.exit_code == 2  # UsageError: neither --manifest nor --edd-dir

    def test_edd_dir_no_matching_files_errors(self, tmp_path):
        prof_path = tmp_path / "profile.yaml"
        self._make_edd_profile(prof_path)
        edd_dir = tmp_path / "empty"
        edd_dir.mkdir()
        r = _run("envmon", "batch-import-workbooks",
                 "--edd-dir", str(edd_dir),
                 "--profile", str(prof_path),
                 "--site", "SITE-A",
                 "--output-dir", str(tmp_path / "out"))
        assert r.exit_code == 1  # ClickException: nothing matched

    def test_manifest_rows_from_dir_xlsx_fallback(self, tmp_path):
        """Default pattern *.csv falls back to *.xlsx; explicit pattern doesn't."""
        from autogis.core.envmon.batch_workbook_importer import manifest_rows_from_dir
        (tmp_path / "a.xlsx").write_bytes(b"")
        rows = manifest_rows_from_dir(tmp_path, Path("p.yaml"), "SITE-A")
        assert [Path(r["workbook_path"]).name for r in rows] == ["a.xlsx"]
        assert rows[0] == {"workbook_path": str(tmp_path / "a.xlsx"),
                           "profile_path": "p.yaml", "site_id": "SITE-A"}
        assert manifest_rows_from_dir(tmp_path, Path("p.yaml"), "SITE-A",
                                      pattern="*.csv") == []

    def _make_equis_workbook(self, path, case="canonical", sample_id="S1"):
        import autogis as package
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        time = "09:14:17" if case == "invalid_time" else "09:14"
        sheets = {
            "EPAR4_FSample_v1": [dict(sys_sample_code=sample_id, sys_loc_code="MW1",
                sample_matrix_code="GW", sample_date="03/11/2025",
                sample_source="Field", sample_type_code="N")],
            "EPAR4_TST_v1": [dict(sys_sample_code=sample_id, lab_anl_method_name="E200.8",
                analysis_date="03/17/2025", analysis_time=time, total_or_dissolved="T",
                column_number="NA", test_type="INITIAL", dilution_factor="1", basis="NA")],
        }
        sheets["EPAR4_RES_v1"] = [{k: v for k, v in sheets["EPAR4_TST_v1"][0].items()
                                  if k not in {"dilution_factor", "basis"}}]
        sheets["EPAR4_RES_v1"][0].update(chemical_name="Lead", result_value="1",
            result_unit="mg/L", result_type_code="TRG", reportable_result="Yes",
            test_batch_type="Analysis", test_batch_id="AB1")
        if case == "collision":
            sheets["EPAR4_TST_v1"].append(dict(sheets["EPAR4_TST_v1"][0], dilution_factor="5"))
        for name, rows in sheets.items():
            sheet = wb.create_sheet(name)
            sheet.append(list(rows[0]))
            for row in rows:
                sheet.append(list(row.values()))
        wb.save(path)
        wb.close()
        return Path(package.__file__).parent / "config/lab_profiles/epar4.yaml"

    @pytest.mark.parametrize("case", ["canonical", "invalid_time", "collision"])
    def test_batch_api_rejects_structural_reader_errors_before_aggregation(self, tmp_path, case):
        from autogis.core.envmon.batch_workbook_importer import run_batch_import
        path = tmp_path / "input.xlsx"
        profile = self._make_equis_workbook(path, case)
        result = run_batch_import([dict(workbook_path=str(path), profile_path=str(profile), site_id="SITE")])
        row = result.manifest[0]
        if case == "canonical":
            assert row.Status == "OK" and row.SampleCount == row.ResultCount == 1
            assert result.all_results[0].MethodDilutionKey == "1|INITIAL|E200.8|03/17/2025@09:14"
        else:
            assert row.Status == "ERROR" and row.SampleCount == row.ResultCount == 0
            assert not result.all_samples and not result.all_results
            category = "equis_invalid_run_timestamp" if case == "invalid_time" else "equis_test_key_collision"
            assert [r for r in result.qa.records if r.category == category and r.severity == "ERROR"]

    @pytest.mark.parametrize("case", ["canonical", "invalid_time", "collision"])
    @pytest.mark.parametrize("mode", ["manifest", "directory"])
    def test_batch_cli_never_publishes_structurally_invalid_records(self, tmp_path, monkeypatch, case, mode):
        monkeypatch.setenv("AUTOGIS_RUN_HISTORY", "off")
        inputs = tmp_path / "inputs"
        inputs.mkdir()
        path = inputs / "input.xlsx"
        profile = self._make_equis_workbook(path, case)
        manifest = tmp_path / "manifest.csv"
        _write_csv(manifest, [dict(workbook_path=str(path), profile_path=str(profile), site_id="SITE")])
        options = (["--manifest", str(manifest)] if mode == "manifest" else
                   ["--edd-dir", str(inputs), "--profile", str(profile), "--site", "SITE"])
        out, report = tmp_path / "out", tmp_path / "qa.json"
        invoked = _run("envmon", "batch-import-workbooks", *options,
                       "--output-dir", str(out), "--report", str(report))
        with (out / "batch_manifest.csv").open(newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
        if case == "canonical":
            assert invoked.exit_code == 0 and rows[0]["Status"] == "OK"
            with (out / "result_records.csv").open(newline="", encoding="utf-8-sig") as fh:
                assert [r["MethodDilutionKey"] for r in csv.DictReader(fh)] == [
                    "1|INITIAL|E200.8|03/17/2025@09:14"]
        else:
            assert invoked.exit_code == 1 and rows[0]["Status"] == "ERROR"
            assert rows[0]["SampleCount"] == rows[0]["ResultCount"] == "0"
            assert not (out / "sample_records.csv").exists()
            assert not (out / "result_records.csv").exists()
            category = "equis_invalid_run_timestamp" if case == "invalid_time" else "equis_test_key_collision"
            summary = json.loads(report.read_text(encoding="utf-8"))
            assert summary["counts_by_category"][f"ERROR/{category}"] > 0

    @pytest.mark.parametrize("case", ["invalid_time", "collision"])
    @pytest.mark.parametrize("bad_first", [True, False])
    @pytest.mark.parametrize("mode", ["api", "manifest", "directory"])
    def test_batch_structural_failure_preserves_valid_siblings_in_both_orders(
            self, tmp_path, monkeypatch, case, bad_first, mode):
        from autogis.core.envmon.batch_workbook_importer import run_batch_import
        monkeypatch.setenv("AUTOGIS_RUN_HISTORY", "off")
        inputs = tmp_path / "inputs"
        inputs.mkdir()
        bad = inputs / ("a_bad.xlsx" if bad_first else "z_bad.xlsx")
        good = inputs / ("z_good.xlsx" if bad_first else "a_good.xlsx")
        profile = self._make_equis_workbook(bad, case, "BAD")
        self._make_equis_workbook(good, "canonical", "GOOD")
        paths = sorted((bad, good))
        manifest_rows = [dict(workbook_path=str(p), profile_path=str(profile), site_id="SITE") for p in paths]
        if mode == "api":
            result = run_batch_import(manifest_rows)
            states = {Path(r.WorkbookPath).name: r.Status for r in result.manifest}
            assert states == {bad.name: "ERROR", good.name: "OK"}
            assert [r.SampleID for r in result.all_samples] == ["GOOD"]
            assert [r.SampleID for r in result.all_results] == ["GOOD"]
        else:
            manifest = tmp_path / "manifest.csv"
            _write_csv(manifest, manifest_rows)
            options = (["--manifest", str(manifest)] if mode == "manifest" else
                       ["--edd-dir", str(inputs), "--profile", str(profile), "--site", "SITE"])
            out = tmp_path / "out"
            invoked = _run("envmon", "batch-import-workbooks", *options, "--output-dir", str(out))
            assert invoked.exit_code == 1
            with (out / "batch_manifest.csv").open(newline="", encoding="utf-8-sig") as fh:
                states = {Path(r["WorkbookPath"]).name: r["Status"] for r in csv.DictReader(fh)}
            assert states == {bad.name: "ERROR", good.name: "OK"}
            for filename in ("sample_records.csv", "result_records.csv"):
                with (out / filename).open(newline="", encoding="utf-8-sig") as fh:
                    assert [r["SampleID"] for r in csv.DictReader(fh)] == ["GOOD"]

    def test_batch_does_not_gate_preexisting_qa_or_ordinary_row_errors(self, tmp_path):
        from autogis.core.common.qa import QACollector, SEV_ERROR
        from autogis.core.envmon.batch_workbook_importer import run_batch_import
        profile, path = tmp_path / "profile.yaml", tmp_path / "input.csv"
        self._make_edd_profile(profile)
        self._make_edd_csv(path)
        with path.open(newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        _write_csv(path, rows + [dict(rows[0], SampleID="")])
        qa = QACollector()
        qa.add(SEV_ERROR, "equis_invalid_run_timestamp", "Previously recorded failure")
        result = run_batch_import([dict(workbook_path=str(path), profile_path=str(profile), site_id="SITE")], qa=qa)
        assert result.manifest[0].Status == "OK"
        assert len(result.all_samples) == len(result.all_results) == 1
        assert any(r.category == "edd_missing_required_field" for r in qa.records)


# ---------------------------------------------------------------------------
# 3. migrate-legacy-data (Tool 2.4)
# ---------------------------------------------------------------------------

class TestMigrateLegacyData:
    def test_wide_to_long_basic(self, tmp_path):
        wide = tmp_path / "wide.csv"
        _write_csv(wide, [
            {"LocationID": "MW-01", "SampleDate": "2024-06-01",
             "Benzene": "12.3", "Toluene": "<5", "Xylenes": ""},
            {"LocationID": "MW-02", "SampleDate": "2024-06-01",
             "Benzene": "ND", "Toluene": "8.1", "Xylenes": ""},
        ])
        out = tmp_path / "long.csv"
        r = _run("envmon", "migrate-legacy-data",
                 "--input-csv", str(wide),
                 "--output", str(out),
                 "--site-id", "SITE-A")
        assert r.exit_code == 0, r.output
        assert out.exists()
        with out.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        # MW-01: Benzene + Toluene (Xylenes blank = skipped); MW-02: Toluene + Benzene
        assert len(rows) == 4
        analytes = {r["AnalyteCanonicalName"] for r in rows}
        assert "Benzene" in analytes and "Toluene" in analytes

    def test_nondetect_flagged(self, tmp_path):
        wide = tmp_path / "wide.csv"
        _write_csv(wide, [
            {"LocationID": "MW-01", "SampleDate": "2024-06-01",
             "Benzene": "<5"},
        ])
        out = tmp_path / "long.csv"
        r = _run("envmon", "migrate-legacy-data",
                 "--input-csv", str(wide), "--output", str(out),
                 "--nondetect-prefix", "<")
        assert r.exit_code == 0, r.output
        with out.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert rows[0]["IsNondetect"] == "True"

    def test_missing_location_skipped(self, tmp_path):
        wide = tmp_path / "wide.csv"
        _write_csv(wide, [
            {"LocationID": "", "SampleDate": "2024-06-01", "Benzene": "5.0"},
            {"LocationID": "MW-01", "SampleDate": "2024-06-01", "Benzene": "3.0"},
        ])
        out = tmp_path / "long.csv"
        r = _run("envmon", "migrate-legacy-data",
                 "--input-csv", str(wide), "--output", str(out))
        assert r.exit_code == 0, r.output
        with out.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert all(row["LocationID"] == "MW-01" for row in rows)


# ---------------------------------------------------------------------------
# 4. create-sampling-plan (Tool 7.2)
# ---------------------------------------------------------------------------

class TestCreateSamplingPlan:
    def _make_wells(self, path: Path, extra_col: bool = False) -> None:
        rows = [{"location_id": "MW-01", "matrix": "GW"},
                {"location_id": "MW-02", "matrix": "GW"}]
        if extra_col:
            for r in rows:
                r["analyte_groups"] = "voc,metals"
        _write_csv(path, rows)

    def _make_groups(self, path: Path) -> None:
        groups = {
            "voc": {"bottles": 2, "bottle_size_ml": 40,
                    "preservation": "HCl pH<2"},
            "metals": {"bottles": 1, "bottle_size_ml": 500,
                       "preservation": "HNO3 pH<2"},
        }
        path.write_text(yaml.dump(groups), encoding="utf-8")

    def test_plan_created_with_two_groups(self, tmp_path):
        wells = tmp_path / "wells.csv"
        groups = tmp_path / "groups.yaml"
        self._make_wells(wells)
        self._make_groups(groups)
        samples_out = tmp_path / "samples.csv"
        bottles_out = tmp_path / "bottles.csv"

        r = _run("envmon", "create-sampling-plan",
                 "--wells-csv", str(wells),
                 "--analyte-groups", str(groups),
                 "--event-date", "2024-06-01",
                 "--site-id", "SITE-A",
                 "--samples-output", str(samples_out),
                 "--bottles-output", str(bottles_out))
        assert r.exit_code == 0, r.output
        with samples_out.open(encoding="utf-8") as fh:
            samples = list(csv.DictReader(fh))
        # 2 wells × 2 groups = 4 planned samples
        assert len(samples) == 4
        with bottles_out.open(encoding="utf-8") as fh:
            bottles = list(csv.DictReader(fh))
        assert len(bottles) == 2
        voc_row = next(b for b in bottles if b["AnalyteGroup"] == "voc")
        assert int(voc_row["BottleCount"]) == 4  # 2 wells × 2 bottles each

    def test_empty_wells_produces_empty_plan(self, tmp_path):
        wells = tmp_path / "wells.csv"
        wells.write_text("location_id,matrix\n", encoding="utf-8")
        groups = tmp_path / "groups.yaml"
        self._make_groups(groups)
        r = _run("envmon", "create-sampling-plan",
                 "--wells-csv", str(wells),
                 "--analyte-groups", str(groups),
                 "--event-date", "2024-06-01",
                 "--samples-output", str(tmp_path / "s.csv"),
                 "--bottles-output", str(tmp_path / "b.csv"))
        assert r.exit_code == 0, r.output

    def test_per_well_analyte_group_restriction(self, tmp_path):
        """Wells with analyte_groups column only get those groups, not all."""
        wells = tmp_path / "wells.csv"
        # MW-01 gets only voc; MW-02 gets all groups (no restriction)
        _write_csv(wells, [
            {"location_id": "MW-01", "matrix": "GW", "analyte_groups": "voc"},
            {"location_id": "MW-02", "matrix": "GW", "analyte_groups": ""},
        ])
        groups = tmp_path / "groups.yaml"
        self._make_groups(groups)
        samples_out = tmp_path / "samples.csv"
        bottles_out = tmp_path / "bottles.csv"
        r = _run("envmon", "create-sampling-plan",
                 "--wells-csv", str(wells),
                 "--analyte-groups", str(groups),
                 "--event-date", "2024-06-01",
                 "--samples-output", str(samples_out),
                 "--bottles-output", str(bottles_out))
        assert r.exit_code == 0, r.output
        with samples_out.open(encoding="utf-8") as fh:
            samples = list(csv.DictReader(fh))
        # MW-01: only voc (1); MW-02: voc + metals (2) → 3 total
        assert len(samples) == 3
        mw01 = [s for s in samples if s["LocationID"] == "MW-01"]
        assert all(s["AnalyteGroup"] == "voc" for s in mw01)


# ---------------------------------------------------------------------------
# 5. reconcile-field-lab (Tool 7.3)
# ---------------------------------------------------------------------------

class TestReconcileFieldLab:
    def _field_rows(self):
        return [
            {"sample_id": "S-001", "location_id": "MW-01",
             "collection_date": "2024-06-01", "matrix": "GW"},
            {"sample_id": "S-002", "location_id": "MW-02",
             "collection_date": "2024-06-01", "matrix": "GW"},
        ]

    def _lab_rows(self):
        return [
            {"sample_id": "S-001", "location_id": "MW-01",
             "analysis_date": "2024-06-01", "analyte_name": "Benzene",
             "matrix": "GW"},
            {"sample_id": "S-001", "location_id": "MW-01",
             "analysis_date": "2024-06-01", "analyte_name": "Toluene",
             "matrix": "GW"},
        ]

    def test_missing_lab_result_flagged(self, tmp_path):
        # FIELD_MISSING_FROM_LAB is an ERROR → exit 1 with fail-on=error (default)
        field = tmp_path / "field.csv"
        lab = tmp_path / "lab.csv"
        _write_csv(field, self._field_rows())
        _write_csv(lab, self._lab_rows())
        out = tmp_path / "flags.csv"
        r = CliRunner().invoke(autogis, [
            "envmon", "reconcile-field-lab",
            "--field-csv", str(field), "--lab-csv", str(lab),
            "--output", str(out),
        ], catch_exceptions=False)
        assert r.exit_code == 1  # errors present → non-zero
        assert out.exists()
        with out.open(encoding="utf-8") as fh:
            flags = list(csv.DictReader(fh))
        types = {f["FlagType"] for f in flags}
        assert "FIELD_MISSING_FROM_LAB" in types  # S-002 has no lab result

    def test_extra_lab_sample_flagged(self, tmp_path):
        field = tmp_path / "field.csv"
        lab = tmp_path / "lab.csv"
        _write_csv(field, self._field_rows()[:1])  # only S-001
        lab_rows = self._lab_rows() + [
            {"sample_id": "S-EXTRA", "location_id": "MW-99",
             "analysis_date": "2024-06-01", "analyte_name": "Benzene",
             "matrix": "GW"},
        ]
        _write_csv(lab, lab_rows)
        out = tmp_path / "flags.csv"
        r = CliRunner().invoke(autogis, [
            "envmon", "reconcile-field-lab",
            "--field-csv", str(field), "--lab-csv", str(lab),
            "--output", str(out),
        ], catch_exceptions=False)
        assert r.exit_code == 1  # errors present
        assert out.exists()
        with out.open(encoding="utf-8") as fh:
            flags = list(csv.DictReader(fh))
        types = {f["FlagType"] for f in flags}
        assert "LAB_MISSING_FROM_FIELD" in types

    def test_date_mismatch_flagged(self, tmp_path):
        # DATE_MISMATCH is a WARNING; fail-on=warning → exit 1
        field = tmp_path / "field.csv"
        lab = tmp_path / "lab.csv"
        _write_csv(field, [{"sample_id": "S-001", "location_id": "MW-01",
                             "collection_date": "2024-06-01", "matrix": "GW"}])
        _write_csv(lab, [{"sample_id": "S-001", "location_id": "MW-01",
                           "analysis_date": "2024-06-10",  # 9-day gap
                           "analyte_name": "Benzene", "matrix": "GW"}])
        out = tmp_path / "flags.csv"
        r = CliRunner().invoke(autogis, [
            "envmon", "reconcile-field-lab",
            "--field-csv", str(field), "--lab-csv", str(lab),
            "--output", str(out),
            "--date-tolerance", "1", "--fail-on", "warning",
        ], catch_exceptions=False)
        assert r.exit_code == 1  # warning present and fail-on=warning
        assert out.exists()
        with out.open(encoding="utf-8") as fh:
            flags = list(csv.DictReader(fh))
        assert any(f["FlagType"] == "DATE_MISMATCH" for f in flags)

    def test_clean_data_no_flags(self, tmp_path):
        field = tmp_path / "field.csv"
        lab = tmp_path / "lab.csv"
        _write_csv(field, [{"sample_id": "S-001", "location_id": "MW-01",
                             "collection_date": "2024-06-01", "matrix": "GW"}])
        _write_csv(lab, [{"sample_id": "S-001", "location_id": "MW-01",
                           "analysis_date": "2024-06-01",
                           "analyte_name": "Benzene", "matrix": "GW"}])
        out = tmp_path / "flags.csv"
        r = _run("envmon", "reconcile-field-lab",
                 "--field-csv", str(field),
                 "--lab-csv", str(lab),
                 "--output", str(out))
        assert r.exit_code == 0, r.output
        with out.open(encoding="utf-8") as fh:
            flags = list(csv.DictReader(fh))
        assert len(flags) == 0
