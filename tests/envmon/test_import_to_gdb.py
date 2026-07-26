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


def test_zero_rows_warning_names_the_matrix_filter(
        tmp_path, workbook, profile, adict, slevels, monkeypatch):
    """No shipped profile declares a SOIL data_type, but the .pyt offers SOIL
    in its matrix_filter dropdown, so this is a legitimate zero-row run. The
    warning must not blame the profile without naming the filter."""
    _run_import(tmp_path, workbook, profile, adict, slevels,
                monkeypatch, matrix_filter="SOIL")

    csv_files = list((tmp_path / "qa").glob("import_qa_*.csv"))
    with csv_files[0].open(encoding="utf-8") as fh:
        msgs = [r["message"] for r in csv.DictReader(fh)
                if r["category"] == "zero_rows_parsed"]
    assert msgs and "matrix filter: SOIL" in msgs[0]


def _run_replace(tmp_path, workbook, profile, adict, slevels, monkeypatch,
                 **kwargs):
    """Drive a replace_* run with every arcpy seam stubbed out.

    Records whether the destructive delete was reached.
    """
    deletes: list = []
    monkeypatch.setattr(import_to_gdb, "load_analyte_dictionary",
                        lambda p: adict)
    monkeypatch.setattr(import_to_gdb, "load_screening_levels",
                        lambda p: slevels)
    monkeypatch.setattr(import_to_gdb, "create_or_update_gdb_schema",
                        lambda *a, **k: None)
    monkeypatch.setattr(import_to_gdb, "create_import_batch",
                        lambda *a, **k: "BATCH1")
    monkeypatch.setattr(import_to_gdb, "finalize_batch",
                        lambda *a, **k: None)
    monkeypatch.setattr(import_to_gdb, "write_qa_to_gdb",
                        lambda *a, **k: 0)
    monkeypatch.setattr(import_to_gdb, "append_records_idempotent",
                        lambda *a, **k: (0, 0))
    monkeypatch.setattr(
        import_to_gdb, "_delete_for_replace",
        lambda *a, **k: deletes.append(a[1]))
    summary = import_to_gdb.run_import(
        workbook=workbook, gdb=tmp_path / "unused.gdb",
        site_config=SITE, profile=profile,
        analyte_dictionary_path=tmp_path / "unused_adict.yaml",
        screening_levels_path=tmp_path / "unused_slevels.yaml",
        qa_output_dir=tmp_path / "qa",
        **kwargs,
    )
    return summary, deletes


def test_replace_with_zero_rows_does_not_delete_existing_data(
        tmp_path, workbook, profile, adict, slevels, monkeypatch):
    """The data-loss guard.

    zero_rows_parsed is non-blocking by design, so has_blocking() is False and
    control reaches the replace branch. Deleting there would remove the prior
    event's rows and then insert nothing -- a profile/workbook mismatch would
    silently erase data rather than replace it.
    """
    summary, deletes = _run_replace(
        tmp_path, workbook, profile, adict, slevels, monkeypatch,
        mode="replace_site_event", matrix_filter="SOIL",
        event_date="2026-07-15")

    assert sum(summary["counts_parsed"].values()) == 0
    assert deletes == [], "replace deleted rows despite parsing none"
    assert "replace_skipped_zero_rows" in _qa_categories(tmp_path)


def test_replace_with_rows_still_deletes(
        tmp_path, workbook, profile, adict, slevels, monkeypatch):
    """The guard must not disarm a legitimate replace.

    allow_errors_override because the shared fixture workbook raises blocking
    QA errors; without it the run short-circuits before the replace branch and
    this would pass for the wrong reason.
    """
    summary, deletes = _run_replace(
        tmp_path, workbook, profile, adict, slevels, monkeypatch,
        mode="replace_site_event", event_date="2026-07-15",
        allow_errors_override=True)

    assert sum(summary["counts_parsed"].values()) > 0
    assert deletes == ["replace_site_event"]
    assert "replace_skipped_zero_rows" not in _qa_categories(tmp_path)


def test_nonzero_rows_parsed_has_no_zero_rows_warning(
        tmp_path, workbook, profile, adict, slevels, monkeypatch):
    summary = _run_import(tmp_path, workbook, profile, adict, slevels,
                          monkeypatch)

    assert sum(summary["counts_parsed"].values()) > 0
    assert "zero_rows_parsed" not in _qa_categories(tmp_path)


# --- _delete_for_replace matrix-scoping (issue #369) -----------------------

def test_matrix_scoped_replace_skips_tables_with_no_matrix_column(monkeypatch):
    """Env_WaterLevels/Env_RPDResults have no Matrix column (gdb_schema.py),
    so a --matrix SOIL replace_site_event must not delete them unscoped --
    that would wipe e.g. GW water levels the run never touched. Previously
    it did exactly that (issue #369)."""
    from autogis.core.common.qa import QACollector

    calls = []
    monkeypatch.setattr(import_to_gdb, "delete_rows",
                        lambda gdb, table, where: calls.append((table, where)) or 0)
    qa = QACollector()
    import_to_gdb._delete_for_replace(
        gdb=None, mode="replace_site_event", site_id="H281",
        batch_id_to_replace=None, event_date="2026-07-15",
        matrix="SOIL", qa=qa)

    tables_deleted = {t for t, _where in calls}
    assert tables_deleted == {"Env_Samples", "Env_AnalyticalResults"}
    for table, where in calls:
        assert "Matrix = 'SOIL'" in where

    skipped = [r for r in qa.records if r.category == "replace_skipped_unscopable_table"]
    assert {r.message.split()[0] for r in skipped} == {
        "Env_WaterLevels", "Env_RPDResults"}


def test_unscoped_replace_still_deletes_all_four_tables(monkeypatch):
    """No --matrix given: the pre-#369 behavior (delete all four tables) is
    unchanged, since there's no matrix to scope by."""
    from autogis.core.common.qa import QACollector

    calls = []
    monkeypatch.setattr(import_to_gdb, "delete_rows",
                        lambda gdb, table, where: calls.append((table, where)) or 0)
    qa = QACollector()
    import_to_gdb._delete_for_replace(
        gdb=None, mode="replace_site_event", site_id="H281",
        batch_id_to_replace=None, event_date="2026-07-15",
        matrix=None, qa=qa)

    tables_deleted = {t for t, _where in calls}
    assert tables_deleted == {"Env_WaterLevels", "Env_Samples",
                              "Env_AnalyticalResults", "Env_RPDResults"}
    assert not [r for r in qa.records
               if r.category == "replace_skipped_unscopable_table"]
