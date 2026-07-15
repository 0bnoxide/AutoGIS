"""Within-file key-collision guard (PR #229 review / issue #230).

Rows that collide under the frozen dedup keys would be silently dropped by
the idempotent writer while the batch reported PASS. The guard turns that
into blocking QA, and run_edd_import finalizes with the writer's actual
inserted/skipped counts instead of pre-dedup list lengths.
"""
from autogis.core.common.qa import QACollector, SEV_ERROR, SEV_WARNING
from autogis.core.envmon.edd_importer import (
    detect_within_file_key_collisions, normalize_edd_rows, normalize_qc_rows,
)
from autogis.core.envmon.edd_profile import LabEDDProfile


def _flat_profile():
    return LabEDDProfile(
        profile_id="p", lab_name="l", format="flat_csv",
        date_format="%m/%d/%Y", encoding="utf-8",
        columns={"sample_id": "sid", "location_id": "loc", "event_date": "dt",
                 "matrix": "mx", "analyte": "an", "result": "res",
                 "units": "un", "qualifier": "q", "reporting_limit": "rl",
                 "method": "meth"},
        matrix_map={}, nondetect_qualifiers=[])


def _flat_row(**over):
    row = {"sid": "S1", "loc": "MW-1", "dt": "01/02/2026", "mx": "GW",
           "an": "TEH", "res": "1.2", "un": "ug/l", "q": "", "rl": "",
           "meth": "8015"}
    row.update(over)
    return row


def _analytical(rows):
    qa = QACollector()
    _, results = normalize_edd_rows(rows, _flat_profile(), "site", "batch",
                                    {}, {}, qa)
    return results


def test_method_only_difference_collides_and_blocks():
    # The real #230 analytical case: same analyte under two methods on one
    # sample — MethodID is not a key component, so the keys are equal.
    results = _analytical([_flat_row(meth="8015"),
                           _flat_row(meth="8015M", res="2.4")])
    qa = QACollector()
    surplus = detect_within_file_key_collisions(
        results, "Env_AnalyticalResults", qa, "B1")
    assert surplus == 1
    recs = [r for r in qa.records if r.category == "edd_key_collision"]
    assert len(recs) == 1
    assert recs[0].severity == SEV_ERROR
    assert qa.has_blocking()


def test_distinct_keys_pass_clean():
    results = _analytical([_flat_row(), _flat_row(an="Benzene")])
    qa = QACollector()
    assert detect_within_file_key_collisions(
        results, "Env_AnalyticalResults", qa, "B1") == 0
    assert not qa.records
    assert not qa.has_blocking()


def _qc_profile():
    return LabEDDProfile(
        profile_id="p", lab_name="l", format="equis_xls",
        date_format="%m/%d/%Y", encoding="utf-8",
        columns={"sample_id": "sid", "analyte": "an", "matrix": "mx",
                 "qc_type": "qct", "result": "res", "units": "un",
                 "method": "meth", "result_fraction": "frac",
                 "analysis_batch_id": "ab"},
        matrix_map={}, nondetect_qualifiers=[])


_QC_BASE = {"sid": "LCS-1", "an": "Decachlorobiphenyl", "mx": "SQ-CONTROL",
            "qct": "SURROGATE", "un": "% recovery", "meth": "8081",
            "frac": "Total", "ab": "AB-1"}


def test_qc_surrogate_rerun_kept_distinct():
    # The real #230 QC case: two surrogate rows identical on every frozen key
    # part but the measured value. ADR-0084 §2 folds a source-order
    # run-instance token into MethodDilutionKey, so both now persist.
    qa = QACollector()
    qc = normalize_qc_rows([{**_QC_BASE, "res": "96"},
                            {**_QC_BASE, "res": "101"}],
                           _qc_profile(), "site", "batch", {}, qa)
    assert len(qc) == 2
    assert qc[0].MethodDilutionKey != qc[1].MethodDilutionKey
    guard_qa = QACollector()
    assert detect_within_file_key_collisions(
        qc, "Env_QCResults", guard_qa, "B1") == 0    # no longer collides
    assert not guard_qa.has_blocking()


def test_qc_genuine_duplicate_warns_but_does_not_block():
    # A true source duplicate (ADR-0084 §3): two rows identical on every field
    # including the measured value — they share a run-instance token, still
    # collapse, and surface as a non-blocking WARNING rather than an ERROR.
    qa = QACollector()
    qc = normalize_qc_rows([{**_QC_BASE, "res": "96"},
                            {**_QC_BASE, "res": "96"}],
                           _qc_profile(), "site", "batch", {}, qa)
    assert qc[0].MethodDilutionKey == qc[1].MethodDilutionKey
    guard_qa = QACollector()
    assert detect_within_file_key_collisions(
        qc, "Env_QCResults", guard_qa, "B1") == 1
    assert not guard_qa.has_blocking()               # WARNING, not ERROR
    dups = [r for r in guard_qa.records
            if r.category == "edd_true_duplicate"]
    assert len(dups) == 1 and dups[0].severity == SEV_WARNING


def test_run_edd_import_collision_finalizes_error_with_honest_counts(
        monkeypatch, tmp_path):
    from autogis.core.envmon import edd_importer

    seen = {}
    monkeypatch.setattr(edd_importer, "create_or_update_gdb_schema",
                        lambda gdb, qa=None: None)
    monkeypatch.setattr(edd_importer, "create_edd_import_batch",
                        lambda *a, **k: "B1")
    # Simulate the writer skipping the within-file duplicate.
    monkeypatch.setattr(
        edd_importer, "append_records_idempotent",
        lambda gdb, table, records, qa, batch:
            (len(records) - 1, 1) if table == "Env_AnalyticalResults"
            else (len(records), 0))
    monkeypatch.setattr(
        edd_importer, "finalize_batch",
        lambda gdb, batch, qa, counts, status:
            seen.update(counts=counts, status=status))
    monkeypatch.setattr(edd_importer, "write_qa_to_gdb", lambda *a, **k: None)
    monkeypatch.setattr(
        edd_importer, "read_edd_file",
        lambda path, profile, qa=None: [_flat_row(meth="8015"),
                                        _flat_row(meth="8015M", res="2.4")])

    edd_importer.run_edd_import(
        tmp_path / "f.csv", _flat_profile(), tmp_path / "g.gdb",
        "site", {}, {})

    assert seen["status"] == "ERROR"          # collision can never PASS
    assert seen["counts"]["analytical_results"] == 1   # inserted, not len()
    assert seen["counts"]["analytical_skipped"] == 1


def test_run_edd_import_clean_file_still_passes(monkeypatch, tmp_path):
    from autogis.core.envmon import edd_importer

    seen = {}
    monkeypatch.setattr(edd_importer, "create_or_update_gdb_schema",
                        lambda gdb, qa=None: None)
    monkeypatch.setattr(edd_importer, "create_edd_import_batch",
                        lambda *a, **k: "B1")
    monkeypatch.setattr(edd_importer, "append_records_idempotent",
                        lambda gdb, table, records, qa, batch:
                        (len(records), 0))
    monkeypatch.setattr(
        edd_importer, "finalize_batch",
        lambda gdb, batch, qa, counts, status:
            seen.update(counts=counts, status=status))
    monkeypatch.setattr(edd_importer, "write_qa_to_gdb", lambda *a, **k: None)
    monkeypatch.setattr(
        edd_importer, "read_edd_file",
        lambda path, profile, qa=None: [_flat_row(),
                                        _flat_row(an="Benzene")])

    edd_importer.run_edd_import(
        tmp_path / "f.csv", _flat_profile(), tmp_path / "g.gdb",
        "site", {}, {})

    assert seen["status"] == "PASS"
    assert seen["counts"]["analytical_results"] == 2
    assert seen["counts"]["analytical_skipped"] == 0
