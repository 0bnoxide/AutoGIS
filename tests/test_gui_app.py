"""PySide6 walking-skeleton smoke tests (ADR-0057).

Runs against Qt's ``offscreen`` platform plugin -- no real display needed,
but a REAL QApplication/QMainWindow/QThread, not mocks of Qt itself.
``run_step`` is monkeypatched (same technique as test_gui_runner.py) since
its own subprocess correctness is covered by test_gui_executor.py; this
suite is about the widget <-> WorkflowRunner <-> worker-thread wiring.

This is automated confidence, not a substitute for a human actually
launching ``autogis-gui`` and looking at it -- offscreen rendering proves
the window builds and the threading bridge delivers signals correctly, not
that the layout looks right.
"""
import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit

import autogis.adapters.gui.runner as runner_mod
from autogis.adapters.gui.app import MainWindow, _headless_forms
from autogis.adapters.gui.executor import Decision, StepResult


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def _pump_until(condition, timeout_ms=5000, step_ms=10):
    waited = 0
    while not condition() and waited < timeout_ms:
        QTest.qWait(step_ms)
        waited += step_ms
    assert condition(), "timed out waiting for condition"


def _fill_required_fields(win, form):
    win._command_box.setCurrentText(form.label)
    for field in form.fields:
        if field.required:
            widget = win._field_widgets[field.name]
            if isinstance(widget, QLineEdit):
                widget.setText("dummy")


def test_headless_forms_excludes_arcpy_tools():
    labels = {f.label for f in _headless_forms()}
    assert "envmon inspect" in labels
    assert "envmon import-gdb" not in labels  # LOCAL/arcpy tool


def test_window_constructs_and_populates_command_list(qapp):
    win = MainWindow()
    assert win._command_box.count() > 0
    assert win._form_layout.rowCount() == len(
        win._forms[win._command_box.currentText()].fields)


def test_selecting_command_rebuilds_form(qapp):
    win = MainWindow()
    labels = sorted(win._forms)
    for label in labels[:3]:
        win._command_box.setCurrentText(label)
        assert win._form_layout.rowCount() == len(win._forms[label].fields)


def test_run_with_missing_required_field_shows_inline_error_no_thread(qapp):
    win = MainWindow()
    form = next(f for f in win._forms.values()
               if any(fld.required for fld in f.fields))
    win._command_box.setCurrentText(form.label)  # required fields left blank
    win._on_run()
    assert "Fix before running" in win._status.text()
    assert win._worker is None


def test_run_happy_path_updates_output_via_worker_thread(qapp, monkeypatch):
    monkeypatch.setattr(
        runner_mod, "run_step",
        lambda step, job_dir, **kw: StepResult(
            Decision.CONTINUE, "ok", exit_code=0, stdout="hello from stub"))
    win = MainWindow()
    form = next(iter(win._forms.values()))
    _fill_required_fields(win, form)

    win._on_run()
    assert win._worker is not None
    _pump_until(lambda: win._run_button.isEnabled())
    assert "CONTINUE" in win._status.text()
    assert "hello from stub" in win._output.toPlainText()


def test_run_button_disabled_while_in_flight_then_reenabled(qapp, monkeypatch):
    release = threading.Event()

    def fake_run_step(step, job_dir, **kw):
        release.wait(timeout=5)
        return StepResult(Decision.CONTINUE, "ok", exit_code=0)

    monkeypatch.setattr(runner_mod, "run_step", fake_run_step)
    win = MainWindow()
    form = next(iter(win._forms.values()))
    _fill_required_fields(win, form)

    win._on_run()
    QTest.qWait(50)  # let the worker thread actually start and block
    assert not win._run_button.isEnabled()

    release.set()
    _pump_until(lambda: win._run_button.isEnabled())
    assert "CONTINUE" in win._status.text()


def test_run_failure_path_reenables_button_and_shows_message(qapp, monkeypatch):
    monkeypatch.setattr(
        runner_mod, "run_step",
        lambda step, job_dir, **kw: (_ for _ in ()).throw(ValueError("boom")))
    win = MainWindow()
    form = next(iter(win._forms.values()))
    _fill_required_fields(win, form)

    win._on_run()
    _pump_until(lambda: win._run_button.isEnabled())
    assert win._status.text() == "Failed to run"
    assert "boom" in win._output.toPlainText()


def test_choice_field_preselects_click_default(qapp):
    """A QComboBox always sits on item 0 unless told otherwise -- an
    untouched form must run with Click's real default (e.g. 'warning'),
    not silently substitute whatever choice happens to be listed first."""
    win = MainWindow()
    form = win._forms["envmon validate-rtk-survey"]
    win._command_box.setCurrentText(form.label)
    widget = win._field_widgets["fail_on"]
    assert widget.currentText() == "warning"  # the real Click default


def test_optional_choice_field_with_no_default_starts_blank(qapp):
    """An optional choice field with no Click default (e.g. list-tools'
    --runtime-filter) must be left unset, not forced onto its first choice
    -- forcing it would make the unfiltered command unreachable from the
    GUI entirely."""
    win = MainWindow()
    form = win._forms["envmon list-tools"]
    win._command_box.setCurrentText(form.label)
    widget = win._field_widgets["runtime_filter"]
    assert widget.currentText() == ""
    assert win._raw_values()["runtime_filter"] == ""


def test_close_while_step_running_is_refused(qapp, monkeypatch):
    release = threading.Event()
    monkeypatch.setattr(
        runner_mod, "run_step",
        lambda step, job_dir, **kw: (release.wait(timeout=5),
                                     StepResult(Decision.CONTINUE, "ok",
                                               exit_code=0))[1])
    win = MainWindow()
    form = next(iter(win._forms.values()))
    _fill_required_fields(win, form)
    win._on_run()
    QTest.qWait(50)  # let the worker thread actually start and block

    assert not win.close()  # closeEvent must ignore -> close() returns False
    assert "still running" in win._status.text()

    release.set()
    _pump_until(lambda: win._run_button.isEnabled())
    assert win.close()  # idle now -- close succeeds


def test_close_while_idle_succeeds(qapp):
    win = MainWindow()
    assert win.close()


def test_on_run_ignores_reentrant_call_while_step_in_flight(qapp, monkeypatch):
    """A second _on_run() while a step is already in flight must not
    replace self._worker out from under the first (programmatic misuse
    the disabled Run button doesn't guard against by itself)."""
    release = threading.Event()
    monkeypatch.setattr(
        runner_mod, "run_step",
        lambda step, job_dir, **kw: (release.wait(timeout=5),
                                     StepResult(Decision.CONTINUE, "ok",
                                               exit_code=0))[1])
    win = MainWindow()
    form = next(iter(win._forms.values()))
    _fill_required_fields(win, form)

    win._on_run()
    QTest.qWait(50)
    first_worker = win._worker
    win._on_run()  # ignored: a step is already running
    assert win._worker is first_worker

    release.set()
    _pump_until(lambda: win._run_button.isEnabled())
    assert "CONTINUE" in win._status.text()


def _run_with_qa_rows(qapp, monkeypatch, rows):
    monkeypatch.setattr(
        runner_mod, "run_step",
        lambda step, job_dir, **kw: StepResult(
            Decision.HALT, "QA FAIL", exit_code=1, qa_rows=rows))
    win = MainWindow()
    form = next(iter(win._forms.values()))
    _fill_required_fields(win, form)
    win._on_run()
    _pump_until(lambda: win._run_button.isEnabled())
    return win


def test_qa_rows_render_as_table_sorted_worst_first(qapp, monkeypatch):
    # location_id is empty in every row -> its column must be dropped;
    # site_id/recommended_action each have one non-empty value -> kept.
    rows = (
        {"severity": "INFO", "category": "count", "message": "3 points",
         "recommended_action": "", "site_id": "", "location_id": ""},
        {"severity": "ERROR", "category": "hrms", "message": "over threshold",
         "recommended_action": "recollect", "site_id": "S1", "location_id": ""},
        {"severity": "WARNING", "category": "vrms", "message": "high vrms",
         "recommended_action": "", "site_id": "", "location_id": ""},
    )
    win = _run_with_qa_rows(qapp, monkeypatch, rows)
    tbl = win._qa_table

    assert not tbl.isHidden()  # a run with QA rows shows the table
    assert tbl.rowCount() == 3
    # worst severity first (CRITICAL/ERROR/WARNING/INFO order), not CSV order
    assert [tbl.item(i, 0).text() for i in range(3)] == \
        ["ERROR", "WARNING", "INFO"]

    headers = [tbl.horizontalHeaderItem(j).text()
               for j in range(tbl.columnCount())]
    assert headers[:3] == ["severity", "category", "message"]
    assert "site_id" in headers               # one non-empty value -> kept
    assert "recommended_action" in headers
    assert "location_id" not in headers       # empty everywhere -> dropped
    # stdout pane is unaffected; the table is an addition, not a replacement
    assert "QA FAIL" in win._output.toPlainText()


def test_qa_table_hidden_when_run_produces_no_qa_rows(qapp, monkeypatch):
    win = _run_with_qa_rows(qapp, monkeypatch, ())  # no --report -> no rows
    assert win._qa_table.isHidden()
    assert win._qa_table.rowCount() == 0
