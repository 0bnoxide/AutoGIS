"""run_import() tests restricted to validate_only mode, which never touches
arcpy (create_or_update_gdb_schema/create_import_batch/finalize_batch/
write_qa_to_gdb are all skipped when mode == "validate_only"), so these run
in CI same as the rest of core/.

Regression coverage for issue #220: a workbook/profile mismatch that parses
zero rows must not report a clean PASS indistinguishable from a healthy run.
"""

import csv

from autogis.core.common.config import SiteConfig
import autogis.core.envmon.import_to_gdb as import_to_gdb

SITE = SiteConfig(data={"site_id": "H281_TEST"})


def _run_import(tmp_path, workbook, profile, adict, slevels, monkeypatch,
                 **kwargs):
    monkeypatch.setattr(import_to_gdb, "load_analyte_dictionary",
                        lambda p: adict)
    monkeypatch.setattr(import_to_gdb, "load_screening_levels",
                        lambda p: slevels)
    return import_to_gdb.run_import(
        workbook=workbook, gdb=tmp_path / "unused.gdb",
        site_config=SITE, profile=profile,
        analyte_dictionary_path=tmp_path / "unused_adict.yaml",
        screening_levels_path=tmp_path / "unused_slevels.yaml",
        qa_output_dir=tmp_path / "qa",
        mode="validate_only",
        **kwargs,
    )


def _qa_categories(tmp_path) -> set:
    csv_files = list((tmp_path / "qa").glob("import_qa_*.csv"))
    assert csv_files, "run_import did not write a QA csv"
    with csv_files[0].open(encoding="utf-8") as fh:
        return {row["category"] for row in csv.DictReader(fh)}


def test_zero_rows_parsed_emits_qa_warning(
        tmp_path, workbook, profile, adict, slevels, monkeypatch):
    # This profile has no SOIL sheets, so filtering to SOIL parses 0 rows.
    summary = _run_import(tmp_path, workbook, profile, adict, slevels,
                          monkeypatch, matrix_filter="SOIL")

    assert sum(summary["counts_parsed"].values()) == 0
    assert "zero_rows_parsed" in _qa_categories(tmp_path)


def test_nonzero_rows_parsed_has_no_zero_rows_warning(
        tmp_path, workbook, profile, adict, slevels, monkeypatch):
    summary = _run_import(tmp_path, workbook, profile, adict, slevels,
                          monkeypatch)

    assert sum(summary["counts_parsed"].values()) > 0
    assert "zero_rows_parsed" not in _qa_categories(tmp_path)
