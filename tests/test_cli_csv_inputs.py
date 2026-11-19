"""CSV inputs that pass ``click.Path(exists=True)`` but cannot be read -- a
directory, a non-UTF-8 file -- are a clean CLI error, not a traceback (#573).
"""
from pathlib import Path

import pytest
from click.testing import CliRunner

from autogis.adapters.cli import autogis


@pytest.mark.parametrize(("command", "flag", "csv_body"), [
    (
        "drone-checkpoint-qa", "--checkpoints",
        "gcp_id,expected_x,expected_y,expected_z,measured_x,measured_y,measured_z\n"
        "GCP-1,1,2,3,1,2,3\n",
    ),
    (
        "rtk-control-check", "--control-points",
        "control_id,published_x,published_y,published_z,surveyed_x,surveyed_y,surveyed_z\n"
        "CP-1,1,2,3,1,2,3\n",
    ),
])
def test_checkpoint_commands_accept_utf8_bom_csv(tmp_path, command, flag, csv_body):
    csv_path = tmp_path / "excel-export.csv"
    csv_path.write_text(csv_body, encoding="utf-8-sig")

    result = CliRunner().invoke(autogis, ["envmon", command, flag, str(csv_path)])
    assert result.exit_code == 0, result.output
    assert "Overall: PASS" in result.output


def _bad_inputs(tmp_path):
    a_dir = tmp_path / "a dir é"
    a_dir.mkdir()
    latin1 = tmp_path / "latin1.csv"
    latin1.write_bytes(b"sample_id,qc_type\n\xff\xfe,trip_blank\n")
    return a_dir, latin1


@pytest.mark.parametrize("argv", [
    ["envmon", "generate-qc-summary", "--results"],
    ["envmon", "build-gwe-event", "--event-date", "2025-01-01",
     "--water-levels"],
])
def test_unreadable_csv_input_is_a_clean_error(tmp_path, argv):
    for bad in _bad_inputs(tmp_path):
        result = CliRunner().invoke(
            autogis, argv + [str(bad), "--out", str(tmp_path / "o.out")])
        assert result.exit_code == 1, result.output
        assert result.exception is None or isinstance(result.exception,
                                                      SystemExit)
        assert "cannot read" in result.output and str(bad) in result.output


def test_generate_qc_summary_rejects_a_directory_out(tmp_path):
    results = tmp_path / "r.csv"
    results.write_text("sample_id,qc_type\n", encoding="utf-8")
    result = CliRunner().invoke(autogis, [
        "envmon", "generate-qc-summary", "--results", str(results),
        "--out", str(tmp_path)])
    assert result.exit_code == 2, result.output
    assert result.exception is None or isinstance(result.exception,
                                                  SystemExit)


def test_batch_import_workbooks_bad_inputs_are_clean_errors(tmp_path):
    """#601: a bad --manifest / --analytes / --screening was a traceback."""
    a_dir, latin1 = _bad_inputs(tmp_path)
    wrong_cols = tmp_path / "wrong.csv"
    wrong_cols.write_text("foo,bar\n1,2\n", encoding="utf-8")
    broken_yaml = tmp_path / "broken.yaml"
    broken_yaml.write_text("a: [\n", encoding="utf-8")
    manifest = tmp_path / "m.csv"
    manifest.write_text("workbook_path,profile_path,site_id\nx.xlsx,p.yaml,S1\n",
                        encoding="utf-8")
    cases = [(["--manifest", str(p)], p) for p in (a_dir, latin1, wrong_cols)]
    cases += [(["--manifest", str(manifest), opt, str(p)], p)
              for opt in ("--analytes", "--screening")
              for p in (a_dir, latin1, broken_yaml)]
    for args, bad in cases:
        result = CliRunner().invoke(autogis, [
            "envmon", "batch-import-workbooks", *args,
            "--output-dir", str(tmp_path / "out")])
        assert result.exit_code == 1, (args, result.output)
        assert result.exception is None or isinstance(result.exception,
                                                      SystemExit), args
        assert result.output.startswith("Error:") and str(bad) in result.output


@pytest.mark.parametrize("argv", [
    ["envmon", "drone-checkpoint-qa", "--checkpoints"],
    ["envmon", "rtk-control-check", "--control-points"],
])
def test_checkpoint_csv_bad_input_is_a_clean_error(tmp_path, argv):
    """#595: unreadable files and malformed rows exit 1 with a message."""
    wrong_columns = tmp_path / "wrong.csv"
    wrong_columns.write_text("a,b\n1,2\n", encoding="utf-8")
    short_row = tmp_path / "short.csv"
    short_row.write_text(
        "gcp_id,control_id,expected_x,published_x\nG1\n", encoding="utf-8")
    after_blank = tmp_path / "blank.csv"  # bad row on file line 3
    after_blank.write_text("a,b\n\n1,2\n", encoding="utf-8")
    huge_field = tmp_path / "huge.csv"  # over csv's 131072-char field limit
    huge_field.write_text('a\n"' + "x" * 200_000 + '"\n', encoding="utf-8")
    for bad, expected in [*((b, "cannot read") for b in _bad_inputs(tmp_path)),
                          (huge_field, "cannot read"),
                          (wrong_columns, "line 2"), (short_row, "line 2"),
                          (after_blank, "line 3")]:
        result = CliRunner().invoke(autogis, argv + [str(bad)])
        assert result.exit_code == 1, result.output
        assert result.exception is None or isinstance(result.exception,
                                                      SystemExit)
        assert expected in result.output and str(bad) in result.output


def test_batch_import_workbooks_ragged_or_empty_manifest_is_clean_error(tmp_path):
    """#611: short rows tracebacked; empty/header-only manifests were a false PASS."""
    header = "workbook_path,profile_path,site_id\n"
    for name, text in [("empty.csv", ""), ("header.csv", header),
                       ("short.csv", header + "x.xlsx\n"),
                       ("blank_site.csv", header + "x.xlsx,p.yaml,\n")]:
        bad = tmp_path / name
        bad.write_text(text, encoding="utf-8")
        result = CliRunner().invoke(autogis, [
            "envmon", "batch-import-workbooks", "--manifest", str(bad),
            "--output-dir", str(tmp_path / "out")])
        assert result.exit_code == 1, (name, result.output)
        assert result.exception is None or isinstance(result.exception,
                                                      SystemExit), name
        assert result.output.startswith("Error:") and str(bad) in result.output
        assert "PASS" not in result.output
        assert not (tmp_path / "out").exists()


def test_batch_import_workbooks_all_rows_skipped_is_not_pass(tmp_path):
    """#621: every workbook missing gave 0/N OK but Status: PASS, exit 0."""
    manifest = tmp_path / "m.csv"
    manifest.write_text("workbook_path,profile_path,site_id\nnope.xlsx,nope.yaml,S1\n",
                        encoding="utf-8")
    result = CliRunner().invoke(autogis, [
        "envmon", "batch-import-workbooks", "--manifest", str(manifest),
        "--output-dir", str(tmp_path / "out")])
    assert result.exit_code == 1, result.output
    assert "no_workbooks_imported" in result.output
    assert "Status: PASS" not in result.output


def test_batch_import_workbooks_unwraps_shipped_yaml(tmp_path, monkeypatch):
    """#638: wrapped analyte/screening YAML reached run_batch_import raw."""
    from types import SimpleNamespace
    import autogis.core.envmon.batch_workbook_importer as bwi
    seen = {}

    def fake_run(rows, **kw):
        seen.update(kw)
        return SimpleNamespace(manifest=[], all_samples=[], all_results=[])

    monkeypatch.setattr(bwi, "run_batch_import", fake_run)
    manifest = tmp_path / "m.csv"
    manifest.write_text("workbook_path,profile_path,site_id\nx.xlsx,p.yaml,S1\n",
                        encoding="utf-8")
    cfg = Path(__file__).resolve().parents[1] / "autogis" / "config"
    CliRunner().invoke(autogis, [
        "envmon", "batch-import-workbooks", "--manifest", str(manifest),
        "--analytes", str(cfg / "analytes" / "analyte_dictionary.yaml"),
        "--screening", str(cfg / "screening_levels" / "screening_levels.yaml"),
        "--output-dir", str(tmp_path / "out")])
    assert "Benzene" in seen["analyte_dictionary"]
    assert "screening_levels" not in seen["screening_levels"]


def test_import_edd_unwraps_shipped_yaml(tmp_path, monkeypatch):
    """#638: import-edd passed wrapped analyte/screening YAML to run_edd_import raw."""
    import autogis.adapters.cli as cli_mod
    import autogis.core.envmon.edd_importer as ei
    import autogis.core.envmon.edd_profile as ep
    seen = {}
    monkeypatch.setattr(cli_mod, "_guard", lambda name: None)
    monkeypatch.setattr(ep.LabEDDProfile, "load", classmethod(lambda cls, p: None))
    monkeypatch.setattr(ei, "run_edd_import", lambda **kw: seen.update(kw) or "B1")
    edd = tmp_path / "e.csv"
    edd.write_text("x", encoding="utf-8")
    cfg = Path(__file__).resolve().parents[1] / "autogis" / "config"
    r = CliRunner().invoke(autogis, [
        "envmon", "import-edd", "--edd", str(edd), "--profile-path", str(edd),
        "--site", "S1", "--gdb", str(tmp_path / "o.gdb"),
        "--analytes", str(cfg / "analytes" / "analyte_dictionary.yaml"),
        "--screening", str(cfg / "screening_levels" / "screening_levels.yaml")])
    assert r.exit_code == 0, r.output
    assert "Benzene" in seen["analyte_dictionary"]
    assert "screening_levels" not in seen["screening_levels"]


@pytest.mark.parametrize("body", [
    "sites: [\n",
    "sites: []\nsites: []\n",
    "args: {event_date: 2026-02-30}",
    r'sites: ["\U00110000"]',
    "args: {approved: !!bool maybe}",
    "args: {event_date: !!timestamp tomorrow}",
    "args: {count: !!int ''}",
])
def test_direct_yaml_load_malformed_is_clean_error(tmp_path, body):
    """#635: malformed / duplicate-key YAML escaped as a raw parser traceback."""
    bad = tmp_path / "bad.yaml"
    bad.write_text(body, encoding="utf-8")
    output = tmp_path / "queue.json"
    output.write_bytes(b"previous queue")
    r = CliRunner().invoke(autogis, ["envmon", "generate-job-queue", "--manifest", str(bad),
                                     "--output", str(output)], catch_exceptions=False)
    assert r.exit_code == 1, r.output
    assert f"Error: cannot read {bad}:" in r.output
    assert output.read_bytes() == b"previous queue"


def test_validate_db_bad_analyte_dictionary_is_clean_error(tmp_path, monkeypatch):
    """#639: a malformed --analytes escaped validate-db as a ConfigError traceback."""
    import autogis.adapters.cli as cli_mod
    monkeypatch.setattr(cli_mod, "_guard", lambda name: None)
    bad = tmp_path / "a.yaml"
    bad.write_text("analytes: [1]\n", encoding="utf-8")
    r = CliRunner().invoke(autogis, ["envmon", "validate-db", str(tmp_path / "x.gdb"),
                                     "--analytes", str(bad)])
    assert r.exit_code == 1 and "Error:" in r.output, r.output
    assert not r.exception or isinstance(r.exception, SystemExit)


@pytest.mark.parametrize("body", ["", "- 1\n"])
def test_direct_yaml_load_non_mapping_is_clean_error(tmp_path, body):
    """#647: an empty or list YAML crashed validate-schedule with AttributeError."""
    p = tmp_path / "s.yaml"
    p.write_text(body, encoding="utf-8")
    r = CliRunner().invoke(autogis, ["envmon", "validate-schedule", "--schedule", str(p)])
    assert r.exit_code == 1 and "expected a YAML mapping" in r.output, r.output
