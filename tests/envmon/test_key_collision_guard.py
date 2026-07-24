"""Within-file key-collision guard (PR #229 review / issue #230).

Rows that collide under the frozen dedup keys would be silently dropped by
the idempotent writer while the batch reported PASS. The guard turns that
into blocking QA, and run_edd_import finalizes with the writer's actual
inserted/skipped counts instead of pre-dedup list lengths.
"""
from autogis.core.common.qa import QACollector, SEV_ERROR
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


def test_same_cell_on_distinct_sheets_does_not_collide():
    results = _analytical([_flat_row(), _flat_row(res="2.4")])
    results[0].SourceSheet = "GW Quality"
    results[1].SourceSheet = "GW Quality (2)"
    results[0].SourceCell = results[1].SourceCell = "C9"
    qa = QACollector()
    assert detect_within_file_key_collisions(
        results, "Env_AnalyticalResults", qa, "B1") == 0
    assert not qa.records


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


def test_qc_surrogate_rerun_collides_and_blocks():
    # The real #230 QC case: two surrogate rows identical on every frozen key
    # part but the measured value. Fail-safe policy (ADR-0084 post-merge
    # review, P1b): value equality cannot prove a genuine duplicate vs. a
    # distinct rerun, so the collision blocks for adjudication rather than
    # silently collapsing one row away. Auto-resolution is reopened, pending a
    # source-provided run identity.
    qa = QACollector()
    qc = normalize_qc_rows([{**_QC_BASE, "res": "96"},
                            {**_QC_BASE, "res": "101"}],
                           _qc_profile(), "site", "batch", {}, qa)
    assert len(qc) == 2
    guard_qa = QACollector()
    assert detect_within_file_key_collisions(
        qc, "Env_QCResults", guard_qa, "B1") == 1
    assert guard_qa.has_blocking()                   # ERROR, never silent
    cats = [r.category for r in guard_qa.records]
    assert cats == ["edd_key_collision"]


def test_overlength_method_dilution_key_blocks():
    # P2 (ADR-0084 post-merge review): a MethodDilutionKey over the TEXT(64)
    # schema slot would truncate on write and break dedup — reject it before
    # the append instead of storing a silently-broken key.
    from autogis.core.envmon.edd_importer import detect_overlength_keys

    results = _analytical([_flat_row()])
    results[0].MethodDilutionKey = "x" * 65          # one over the 64 limit
    qa = QACollector()
    assert detect_overlength_keys(
        results, "Env_AnalyticalResults", qa, "B1") == 1
    assert qa.has_blocking()
    assert [r.category for r in qa.records] == ["edd_key_too_long"]

    clean = _analytical([_flat_row()])
    clean[0].MethodDilutionKey = "x" * 64            # exactly at the limit is fine
    clean_qa = QACollector()
    assert detect_overlength_keys(
        clean, "Env_AnalyticalResults", clean_qa, "B1") == 0
    assert not clean_qa.has_blocking()


def _import_harness(monkeypatch, rows):
    """Stub the GDB seams; return (seen, appended) trackers. `appended` stays
    empty when the write is correctly gated (PR #236 review)."""
    from autogis.core.envmon import edd_importer

    seen = {}
    appended = []
    monkeypatch.setattr(edd_importer, "create_or_update_gdb_schema",
                        lambda gdb, qa=None: None)
    monkeypatch.setattr(edd_importer, "create_edd_import_batch",
                        lambda *a, **k: "B1")
    monkeypatch.setattr(
        edd_importer, "append_records_idempotent",
        lambda gdb, table, records, qa, batch: (
            appended.append(table), (len(records), 0))[1])
    monkeypatch.setattr(
        edd_importer, "finalize_batch",
        lambda gdb, batch, qa, counts, status:
            seen.update(counts=counts, status=status))
    monkeypatch.setattr(edd_importer, "write_qa_to_gdb", lambda *a, **k: None)
    monkeypatch.setattr(edd_importer, "read_edd_file",
                        lambda path, profile, qa=None: rows)
    return edd_importer, seen, appended


def test_run_edd_import_collision_aborts_write_entirely(monkeypatch, tmp_path):
    # A within-file collision must gate the write, not just flag QA: the writer
    # never inspects qa, so a partial-collision write would otherwise still
    # land (PR #236 review). Assert append is never invoked and nothing counts.
    edd_importer, seen, appended = _import_harness(
        monkeypatch, [_flat_row(meth="8015"),
                      _flat_row(meth="8015M", res="2.4")])

    edd_importer.run_edd_import(
        tmp_path / "f.csv", _flat_profile(), tmp_path / "g.gdb",
        "site", {}, {})

    assert appended == []                      # writer never invoked
    assert seen["status"] == "ERROR"           # collision can never PASS
    assert seen["counts"]["analytical_results"] == 0
    assert seen["counts"]["samples"] == 0


def test_run_edd_import_overlength_key_aborts_write(monkeypatch, tmp_path):
    # An overlength MethodDilutionKey would truncate at InsertCursor; the guard
    # must abort the write before that happens (PR #236 review, P2 gating).
    row = _flat_row(dil="x" * 65)               # -> MethodDilutionKey, 65 chars
    edd_importer, seen, appended = _import_harness(monkeypatch, [row])
    profile = LabEDDProfile(
        profile_id="p", lab_name="l", format="flat_csv",
        date_format="%m/%d/%Y", encoding="utf-8",
        columns={"sample_id": "sid", "location_id": "loc", "event_date": "dt",
                 "matrix": "mx", "analyte": "an", "result": "res",
                 "units": "un", "method": "meth", "dilution_factor": "dil"},
        matrix_map={}, nondetect_qualifiers=[])

    edd_importer.run_edd_import(
        tmp_path / "f.csv", profile, tmp_path / "g.gdb", "site", {}, {})

    assert appended == []                      # writer never invoked
    assert seen["status"] == "ERROR"
    assert seen["counts"]["analytical_results"] == 0


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


def test_run_edd_import_test_key_collision_gates_write(monkeypatch, tmp_path):
    # PR #253 P1: the equis reader flags a duplicate-test-key collision (two TST
    # rows, same 7-col key, conflicting dilution) as blocking QA. run_edd_import
    # must fold that into the batch-integrity abort — like a within-file key
    # collision — so the order-dependent dilution/prep metadata never lands.
    edd_importer, seen, appended = _import_harness(monkeypatch, [_flat_row()])

    def _read(path, profile, qa=None):
        qa.add(SEV_ERROR, "equis_test_key_collision", "conflicting test key")
        return [_flat_row()]
    monkeypatch.setattr(edd_importer, "read_edd_file", _read)

    edd_importer.run_edd_import(
        tmp_path / "f.csv", _flat_profile(), tmp_path / "g.gdb",
        "site", {}, {})

    assert appended == []                      # writer never invoked
    assert seen["status"] == "ERROR"
    assert seen["counts"]["analytical_results"] == 0
