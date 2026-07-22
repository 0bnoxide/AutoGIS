"""Tests for Phase 5 slice 2 — recipe->Workflow mapping + headless run-recipe.

Uses review-checkpoint steps (command: null) to exercise the run loop, pause
handling and exit codes without spawning subprocesses (the subprocess execution
path is covered by tests/test_gui_executor.py).
"""
from pathlib import Path

import yaml
from click.testing import CliRunner

from autogis.adapters.cli import autogis as autogis_cli
from autogis.adapters.gui.executor import Step
from autogis.adapters.recipe_workflow import recipe_to_workflow


def test_recipe_to_workflow_maps_fields():
    wf = recipe_to_workflow({
        "name": "wf",
        "steps": [
            {"command": ["envmon", "inspect"], "values": {"scan_rows": 10},
             "fail_on": "error", "pause_on_warning": True, "message": "m"},
            {"command": None, "message": "review"},
        ],
    })
    assert wf.name == "wf" and len(wf.steps) == 2
    s0, s1 = wf.steps
    assert isinstance(s0, Step)
    assert s0.command == ("envmon", "inspect")   # list -> tuple
    assert s0.values == {"scan_rows": 10} and s0.fail_on == "error"
    assert s0.pause_on_warning is True and s0.message == "m"
    assert s1.command is None                     # checkpoint preserved


def _write(tmp_path, steps, name="R"):
    p = tmp_path / "recipe.yaml"
    p.write_text(yaml.safe_dump({"name": name, "steps": steps}), encoding="utf-8")
    return p


def test_run_recipe_stops_at_review_checkpoint(tmp_path):
    recipe = _write(tmp_path, [{"command": None, "message": "review layouts"}])
    r = CliRunner().invoke(autogis_cli, [
        "envmon", "run-recipe", str(recipe), "--job-root", str(tmp_path / "j")])
    assert r.exit_code == 2, r.output          # paused-for-review
    assert "pause_for_review" in r.output
    assert "Final: paused" in r.output


def test_run_recipe_continue_through_review_completes(tmp_path):
    recipe = _write(tmp_path, [
        {"command": None, "message": "first"},
        {"command": None, "message": "second"},
    ])
    r = CliRunner().invoke(autogis_cli, [
        "envmon", "run-recipe", str(recipe), "--job-root", str(tmp_path / "j"),
        "--continue-through-review"])
    assert r.exit_code == 0, r.output          # resumed past both -> done
    assert "Final: done" in r.output
    assert "[step 0]" in r.output and "[step 1]" in r.output


def test_run_recipe_ctrl_c_exits_130(tmp_path, monkeypatch):
    """Ctrl-C during a step must return the standard cancellation code 130,
    not Click's Abort (exit 1). Codex P2."""
    from autogis.adapters.gui.runner import WorkflowRunner

    def _interrupt(self):
        raise KeyboardInterrupt
    monkeypatch.setattr(WorkflowRunner, "advance", _interrupt)

    recipe = _write(tmp_path, [{"command": ["envmon", "inspect"]}])
    r = CliRunner().invoke(autogis_cli, [
        "envmon", "run-recipe", str(recipe), "--job-root", str(tmp_path / "j")])
    assert r.exit_code == 130
    assert "Interrupted" in r.output


def test_classify_exit_130_is_cancelled():
    """A Ctrl-C run-recipe exits 130; run-history must record it as cancelled,
    not error, so readiness/history consumers don't misreport it. Codex P2."""
    from autogis.adapters.cli import _classify_exit
    assert _classify_exit(SystemExit(130)) == "cancelled"
    assert _classify_exit(SystemExit(1)) == "error"
    assert _classify_exit(SystemExit(0)) == "success"


def test_run_recipe_bad_recipe_is_clean_error(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("name: x\nsteps: []\n", encoding="utf-8")
    r = CliRunner().invoke(autogis_cli, ["envmon", "run-recipe", str(bad)])
    assert r.exit_code != 0
    assert "steps" in r.output and "Traceback" not in r.output
