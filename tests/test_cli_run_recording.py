"""Tests for CLI-seam run-history recording (ADR-0054).

Every leaf command reached through the ``autogis`` root group is a
RecordingCommand (via the Group.command_class / group_class cascade), so a
RunRecord is written for every executed run -- success, guard refusal, QA
FAIL, or crash -- but never for parse-time UsageErrors. ``agol promote``
is skip-listed because it self-logs a richer record via _log_promotion.

AUTOGIS_RUN_HISTORY is "off" suite-wide (tests/conftest.py); tests here
re-point it at a tmp_path file per case.
"""
from unittest.mock import MagicMock, patch

import yaml
from click.testing import CliRunner

from autogis.adapters.cli import autogis
from autogis.core.common.run_history import RunHistory


def _records(path):
    return RunHistory(path).query()


def test_clean_success_writes_success_record(tmp_path, monkeypatch):
    rh = tmp_path / "rh.csv"
    monkeypatch.setenv("AUTOGIS_RUN_HISTORY", str(rh))

    result = CliRunner().invoke(autogis, ["envmon", "list-tools"])

    assert result.exit_code == 0
    records = _records(rh)
    assert len(records) == 1
    rec = records[0]
    assert rec.status == "success"
    assert rec.tool_name == "list-tools"
    assert (rec.qa_count_error, rec.qa_count_warning, rec.qa_count_info) == (0, 0, 0)


def test_guard_refused_local_tool_writes_error_record(tmp_path, monkeypatch):
    rh = tmp_path / "rh.csv"
    monkeypatch.setenv("AUTOGIS_RUN_HISTORY", str(rh))
    cfg = tmp_path / "site.yaml"
    wb = tmp_path / "wb.xlsx"
    cfg.write_text("x", encoding="utf-8")
    wb.write_text("x", encoding="utf-8")

    result = CliRunner().invoke(
        autogis, ["envmon", "import-gdb", str(cfg), str(wb)])

    assert result.exit_code != 0
    records = _records(rh)
    assert len(records) == 1
    rec = records[0]
    assert rec.status == "error"
    assert rec.tool_name == "import-gdb"
    assert rec.message


def test_nested_command_records_canonical_tool_and_site(tmp_path, monkeypatch):
    rh = tmp_path / "rh.csv"
    monkeypatch.setenv("AUTOGIS_RUN_HISTORY", str(rh))

    with patch("autogis.adapters.cli.require_runtime"), patch(
        "autogis.core.envmon.manage_callout_overrides.load_overrides",
        return_value={},
    ):
        result = CliRunner().invoke(autogis, [
            "envmon", "manage-callout-overrides", "list", str(tmp_path),
            "--site", "S1", "--spec", "FIG-1",
        ])

    assert result.exit_code == 0
    rec = _records(rh)[0]
    assert rec.tool_name == "manage-callout-overrides"
    assert rec.site_id == "S1"


def test_site_config_command_records_site_id(tmp_path, monkeypatch):
    rh = tmp_path / "rh.csv"
    monkeypatch.setenv("AUTOGIS_RUN_HISTORY", str(rh))
    cfg = tmp_path / "site.yaml"
    cfg.write_text("site_id: S1\n", encoding="utf-8")
    figure = tmp_path / "figure.yaml"
    figure.write_text("x", encoding="utf-8")

    with patch("autogis.adapters.cli.require_runtime"):
        result = CliRunner().invoke(
            autogis, ["envmon", "build-callouts", str(cfg), str(figure)])

    assert result.exit_code == 1
    rec = _records(rh)[0]
    assert rec.tool_name == "build-callouts"
    assert rec.site_id == "S1"


def test_site_path_dest_command_records_site_id(tmp_path, monkeypatch):
    # build-survey-form / create-sampling-event / build-fieldmaps take the
    # site config under the dest `site_path` (not `site_config`); readiness
    # must still see a resolved site_id (ADR-0076).
    rh = tmp_path / "rh.csv"
    monkeypatch.setenv("AUTOGIS_RUN_HISTORY", str(rh))
    cfg = tmp_path / "site.yaml"
    cfg.write_text("site_id: S1\n", encoding="utf-8")
    empty = tmp_path / "empty.yaml"
    empty.write_text("{}\n", encoding="utf-8")

    result = CliRunner().invoke(autogis, [
        "envmon", "build-survey-form",
        "--site", str(cfg), "--analytes", str(empty),
        "--event", str(empty), "--out", str(tmp_path / "form.xlsx"),
    ])

    # command may pass or fail downstream; either way a record is written and
    # the site identity resolves from the site_path config.
    assert result.exit_code in (0, 1)
    rec = _records(rh)[0]
    assert rec.tool_name == "build-survey-form"
    assert rec.site_id == "S1"


def test_qa_fail_records_error_with_counts(tmp_path, monkeypatch):
    # AUTOGIS_RUN_HISTORY target is deliberately a DIFFERENT file than the
    # --run-history argument the tool itself reads.
    rh = tmp_path / "rh.csv"
    monkeypatch.setenv("AUTOGIS_RUN_HISTORY", str(rh))

    result = CliRunner().invoke(autogis, [
        "envmon", "evaluate-readiness",
        "--site-id", "S1",
        "--run-history", str(tmp_path / "empty.csv"),
        "--required-tool", "import-edd",
    ])

    assert result.exit_code == 1  # _render_qa's SystemExit(1) on FAIL
    records = _records(rh)
    assert len(records) == 1
    rec = records[0]
    assert rec.status == "error"
    assert rec.qa_count_error >= 1
    assert rec.site_id == "S1"


def test_usage_error_writes_nothing(tmp_path, monkeypatch):
    rh = tmp_path / "rh.csv"
    monkeypatch.setenv("AUTOGIS_RUN_HISTORY", str(rh))

    result = CliRunner().invoke(autogis, ["envmon", "evaluate-readiness"])

    assert result.exit_code == 2
    assert not rh.exists()


def test_agol_promote_self_logs_exactly_one_record(tmp_path, monkeypatch):
    # Both the tool's own --run-history and the seam recorder's env var
    # point at the SAME file: without the skip-list this run would be
    # double-logged. The one record present must be _log_promotion's
    # ("agol-promote"), not the hook's ("promote").
    rh = tmp_path / "rh.csv"
    monkeypatch.setenv("AUTOGIS_RUN_HISTORY", str(rh))

    stage_map = tmp_path / "stage_map.yaml"
    stage_map.write_text(yaml.safe_dump(
        {"wells": {"dev": "dev-item", "qa": "qa-item", "prod": "prod-item"}}),
        encoding="utf-8")

    # Same seam-patching pattern as tests/test_agol_promote.py: MagicMock
    # gis, fetch_layer_schema patched at its point of use in promote.py.
    schema = {"fields": [{"name": "WellType", "type": "esriFieldTypeString",
                          "nullable": True, "domain": None}]}
    gis = MagicMock()
    src_layer, dst_layer = MagicMock(), MagicMock()
    src_layer.query.return_value.features = ["f1", "f2"]
    src_layer.properties = {"id": 0}
    dst_layer.properties = {"id": 0}
    gis.content.get.side_effect = lambda iid: {
        "dev-item": MagicMock(layers=[src_layer], tables=[]),
        "qa-item": MagicMock(layers=[dst_layer], tables=[]),
    }[iid]
    monkeypatch.setattr("autogis.adapters.cli.agol_from_profile",
                        lambda profile: gis)

    with patch("autogis.core.agol.promote.fetch_layer_schema",
               return_value=schema):
        result = CliRunner().invoke(autogis, [
            "agol", "promote",
            "--stage-map", str(stage_map),
            "--layer", "wells",
            "--from", "dev", "--to", "qa",  # no approval needed
            "--run-history", str(rh),
        ])

    assert result.exit_code == 0
    records = _records(rh)
    assert len(records) == 1
    assert records[0].tool_name == "agol-promote"


def test_coc_group_does_not_write_run_history(tmp_path, monkeypatch):
    rh = tmp_path / "rh.csv"
    monkeypatch.setenv("AUTOGIS_RUN_HISTORY", str(rh))
    store = tmp_path / "custody.json"
    store.write_text("{}\n", encoding="utf-8")

    result = CliRunner().invoke(
        autogis, ["envmon", "coc", "status", "--store", str(store)])

    assert result.exit_code == 0
    assert not rh.exists()


def test_import_edd_event_tag_reaches_record(tmp_path, monkeypatch):
    # Producer event tagging (ADR-0093): --event must land on the run-history
    # record so event-status scopes canonical-import to the right event. arcpy
    # is absent, so the guard refuses and an ERROR record is written -- but the
    # tag flows through ctx.params before the guard fires.
    rh = tmp_path / "rh.csv"
    monkeypatch.setenv("AUTOGIS_RUN_HISTORY", str(rh))
    edd = tmp_path / "edd.csv"
    prof = tmp_path / "profile.yaml"
    edd.write_text("x", encoding="utf-8")
    prof.write_text("x", encoding="utf-8")

    result = CliRunner().invoke(autogis, [
        "envmon", "import-edd", "--edd", str(edd), "--profile-path", str(prof),
        "--site", "H281", "--gdb", str(tmp_path / "out.gdb"),
        "--event", "2026-Q2",
    ])

    assert result.exit_code != 0  # guard refusal (no arcpy)
    rec = _records(rh)[0]
    assert rec.tool_name == "import-edd"
    assert rec.site_id == "H281"
    assert rec.event_id == "2026-Q2"


def test_apply_screening_site_and_event_tags_reach_record(tmp_path, monkeypatch):
    # apply-screening is headless with no site concept of its own; --site/--event
    # exist purely so its record is findable by event-status (without --site the
    # record carried site_id="" and the checker never matched it -- ADR-0093).
    rh = tmp_path / "rh.csv"
    monkeypatch.setenv("AUTOGIS_RUN_HISTORY", str(rh))
    results = tmp_path / "results.csv"
    screening = tmp_path / "screening.yaml"
    results.write_text("", encoding="utf-8")
    screening.write_text("{}\n", encoding="utf-8")

    result = CliRunner().invoke(autogis, [
        "envmon", "apply-screening", "--results-csv", str(results),
        "--screening", str(screening), "--output", str(tmp_path / "out.csv"),
        "--site", "H281", "--event", "2026-Q2",
    ])

    # Tag flow is independent of screening internals; assert on the record only.
    assert result.exit_code in (0, 1)
    rec = _records(rh)[0]
    assert rec.tool_name == "apply-screening"
    assert rec.site_id == "H281"
    assert rec.event_id == "2026-Q2"


def test_approve_gw_model_site_and_event_tags_reach_record(tmp_path, monkeypatch):
    # approve-gw-model feeds event-status's approved-model review overlay, which
    # queries it site+event-scoped. Run history is append-only, so an untagged
    # approval is permanently unmatchable (ADR-0093). Guard refuses (no arcpy)
    # but the tags flow into the error record.
    rh = tmp_path / "rh.csv"
    monkeypatch.setenv("AUTOGIS_RUN_HISTORY", str(rh))

    result = CliRunner().invoke(autogis, [
        "envmon", "approve-gw-model", "--gdb", str(tmp_path / "x.gdb"),
        "--run-id", "R1", "--model", "M1", "--reviewer", "QA",
        "--site", "H281", "--event", "2026-Q2",
    ])

    assert result.exit_code != 0  # guard refusal (no arcpy)
    rec = _records(rh)[0]
    assert rec.tool_name == "approve-gw-model"
    assert rec.site_id == "H281"
    assert rec.event_id == "2026-Q2"


def test_default_path_is_cwd_run_history_csv(tmp_path, monkeypatch):
    monkeypatch.delenv("AUTOGIS_RUN_HISTORY", raising=False)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(autogis, ["envmon", "list-tools"])

    assert result.exit_code == 0
    assert (tmp_path / "run_history.csv").exists()
