"""Desktop groundwater-model approval action (#384)."""
import json
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

import autogis.adapters.gui.gw_model_approval as approval_mod
import autogis.adapters.gui.gw_model_approval_dialog as dialog_mod
from autogis.adapters.gui.app import MainWindow
from autogis.adapters.gui.executor import Decision, StepResult
from autogis.adapters.gui.gw_model_approval_dialog import (
    GWModelApprovalDialog,
)


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def _run(status="DRAFT", approved=""):
    return {
        "RunID": "GWM_QA", "SiteID": "QASITE", "EventDate": "2026-07-01",
        "ExecutedMethods": ["TIN", "IDW", "EBK"],
        "ApprovedModel": approved, "ReviewStatus": status,
        "Models": [
            {"Rank": 1, "ModelName": "TIN", "NPoints": 14, "RMSE": 0.02,
             "MeanError": 0.0, "MAE": 0.01, "PctWithinTolerance": 100.0},
            {"Rank": 2, "ModelName": "IDW", "NPoints": 14, "RMSE": 0.14,
             "MeanError": 0.01, "MAE": 0.1, "PctWithinTolerance": 90.0},
        ],
    }


def test_dialog_lists_drafts_and_all_executed_models(qapp, monkeypatch):
    monkeypatch.setattr(
        dialog_mod.gw_model_approval, "load_review_runs",
        lambda *_a, **_k: [_run(), {
            **_run(status="APPROVED", approved="TIN"), "RunID": "OLD",
        }])
    dlg = GWModelApprovalDialog("pro-python.exe")
    dlg._gdb.setText("QASITE.gdb")
    assert dlg._on_refresh()
    qapp.processEvents()
    assert dlg._runs.rowCount() == 1  # initial list is DRAFT-only
    assert [dlg._model.itemText(i) for i in range(dlg._model.count())] == [
        "TIN", "IDW", "EBK",
    ]
    assert dlg._stats.rowCount() == 2  # EBK remains choosable without CV row
    assert dlg._approve.isEnabled() is False  # reviewer still required


def test_dialog_confirms_approves_and_refreshes_status(qapp, monkeypatch):
    state = [_run()]
    calls = []
    monkeypatch.setattr(
        dialog_mod.gw_model_approval, "load_review_runs",
        lambda *_a, **_k: state)

    def approve(*args, **kwargs):
        calls.append((args, kwargs))
        state[0] = _run(status="APPROVED", approved="EBK")
        return "approved"

    monkeypatch.setattr(
        dialog_mod.gw_model_approval, "approve_model", approve)
    monkeypatch.setattr(
        dialog_mod.QMessageBox, "question",
        lambda *_a, **_k: QMessageBox.Yes)

    dlg = GWModelApprovalDialog("pro-python.exe")
    dlg._gdb.setText("QASITE.gdb")
    dlg._on_refresh()
    qapp.processEvents()
    dlg._model.setCurrentText("EBK")  # any executed model, regardless of rank
    dlg._reviewer.setText("AB")
    assert dlg._approve.isEnabled()
    dlg._on_approve()
    qapp.processEvents()

    assert calls[0][0][2:5] == ("GWM_QA", "EBK", "AB")
    assert dlg._runs.item(0, 4).text() == "EBK"
    assert dlg._runs.item(0, 5).text() == "APPROVED"
    assert "refreshed ApprovedModel and ReviewStatus" in dlg._status.text()


def test_dialog_no_confirmation_makes_no_change(qapp, monkeypatch):
    monkeypatch.setattr(
        dialog_mod.gw_model_approval, "load_review_runs",
        lambda *_a, **_k: [_run()])
    monkeypatch.setattr(
        dialog_mod.QMessageBox, "question",
        lambda *_a, **_k: QMessageBox.No)
    monkeypatch.setattr(
        dialog_mod.gw_model_approval, "approve_model",
        lambda *_a, **_k: pytest.fail("approval ran without confirmation"))
    dlg = GWModelApprovalDialog("pro-python.exe")
    dlg._gdb.setText("QASITE.gdb")
    dlg._on_refresh()
    dlg._reviewer.setText("AB")
    dlg._on_approve()


def test_review_reader_parses_structured_child_output(monkeypatch):
    payload = [_run()]
    monkeypatch.setattr(
        approval_mod.subprocess, "run",
        lambda *_a, **_k: SimpleNamespace(
            returncode=0,
            stdout="ArcGIS startup noise\nAUTOGIS_GW_MODEL_REVIEWS="
                   + json.dumps(payload) + "\n",
            stderr=""))
    assert approval_mod.load_review_runs(
        "pro-python.exe", "QASITE.gdb") == payload


def test_approval_adapter_uses_existing_cli_backend(monkeypatch):
    seen = {}

    def run_step(step, _job, *, local_python):
        seen["step"] = step
        seen["python"] = local_python
        return StepResult(
            Decision.CONTINUE, "ok", exit_code=0, stdout="approved")

    monkeypatch.setattr(approval_mod, "run_step", run_step)
    out = approval_mod.approve_model(
        "pro-python.exe", "QASITE.gdb", "GWM_QA", "EBK", "AB",
        site_id="QASITE", event_id="2026-07-01")
    assert out == "approved"
    assert seen["step"].command == ("envmon", "approve-gw-model")
    assert seen["step"].values["reviewer"] == "AB"
    assert seen["python"] == "pro-python.exe"


def test_main_window_has_dedicated_action_not_generic_form(qapp, tmp_path):
    store = QSettings(str(tmp_path / "settings.ini"),
                      QSettings.Format.IniFormat)
    win = MainWindow(settings_store=store)
    assert "envmon approve-gw-model" not in win._forms
    button = win.findChild(QPushButton, "approve-gw-model")
    assert button is not None
    button.click()
    assert "Set the arcgispro-py3" in win._status.text()
