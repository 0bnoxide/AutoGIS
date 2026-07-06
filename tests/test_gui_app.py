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

from PySide6.QtCore import QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton

import autogis.adapters.gui.app as app_mod
import autogis.adapters.gui.runner as runner_mod
from autogis.adapters.gui import settings as settings_mod
from autogis.adapters.gui.app import MainWindow, _dialog_kind, _window_forms
from autogis.adapters.gui.executor import Decision, StepResult, needs_arcpy_env
from autogis.adapters.gui.introspect import FormField


def _path_field(**kw):
    base = dict(name="p", label="P", kind="path", required=False, default=None)
    base.update(kw)
    return FormField(**base)


def _first_runnable(win):
    """First headless, reachable form -- one the window runs without a
    local_python (LOCAL/arcpy tools are now shown but Run-gated). Restores the
    old 'first headless form' the run tests relied on before LOCAL tools were
    listed."""
    return next(f for f in win._forms.values()
               if not f.unreachable_reason and not needs_arcpy_env(f.path))


def _win_with_store(tmp_path, local_python=None):
    """A MainWindow backed by a temp-ini QSettings (never the real registry),
    optionally pre-seeded with a local_python."""
    store = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    if local_python:
        settings_mod.set_local_python(local_python, store)
    return MainWindow(settings_store=store), store


@pytest.fixture(autouse=True)
def _isolate_qsettings(tmp_path, monkeypatch):
    """No GUI test may touch the real per-user QSettings. Redirect the default
    store to a per-test temp ini so a bare ``MainWindow()`` (settings_store=None)
    never falls through to the real registry -- a bare-window test once wrote a
    stray value there before this guard existed."""
    store = QSettings(str(tmp_path / "qsettings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(settings_mod, "_default_store", lambda: store)


def test_dialog_kind_folder_for_dir_output_for_save_open_for_input():
    # a directory-only param opens a folder picker even if also output-shaped
    assert _dialog_kind(_path_field(is_dir=True, is_path_output=True)) == "dir"
    # a bare click.Path() output -> save picker
    assert _dialog_kind(_path_field(is_path_output=True)) == "save"
    # an existing-input path -> open picker
    assert _dialog_kind(_path_field(is_path_output=False)) == "open"


def test_browse_uses_dialog_kind_and_populates_field(qapp, monkeypatch):
    seen = {}

    def fake_pick(kind, parent, title, start):
        seen["kind"] = kind
        seen["start"] = start
        return "C:/picked/path"

    monkeypatch.setattr(app_mod, "_pick_path", fake_pick)
    win = MainWindow()
    line = QLineEdit()
    line.setText("prev")
    win._browse(_path_field(is_dir=True), line)
    assert seen["kind"] == "dir"          # decided by _dialog_kind
    assert seen["start"] == "prev"        # seeds the dialog from current text
    assert line.text() == "C:/picked/path"


def test_browse_cancel_leaves_field_untouched(qapp, monkeypatch):
    monkeypatch.setattr(app_mod, "_pick_path", lambda *a, **k: "")
    win = MainWindow()
    line = QLineEdit()
    line.setText("orig")
    win._browse(_path_field(is_path_output=True), line)
    assert line.text() == "orig"          # cancelled dialog must not clear it


def test_path_fields_render_a_browse_button_each(qapp):
    win = MainWindow()
    form = win._forms["envmon reconcile-locations"]  # has site_config + report
    win._command_box.setCurrentText(form.label)
    n_path = sum(1 for f in form.fields if f.kind == "path")
    assert n_path >= 2
    browse = win.findChildren(QPushButton, "field-browse")
    assert len(browse) == n_path


def test_each_browse_button_fills_its_own_field(qapp, monkeypatch):
    # echo the dialog title (which embeds the field label) back as the picked
    # path, so each field's text reveals which field its button targeted
    monkeypatch.setattr(app_mod, "_pick_path",
                       lambda kind, parent, title, start: title)
    win = MainWindow()
    form = win._forms["envmon reconcile-locations"]
    win._command_box.setCurrentText(form.label)
    for b in win.findChildren(QPushButton, "field-browse"):
        b.click()
    for f in form.fields:
        if f.kind == "path":
            assert win._field_widgets[f.name].text() == f"Select {f.label}"


def test_browse_buttons_do_not_accumulate_across_command_switches(qapp):
    """removeRow must delete a path field's nested QLineEdit+Browse layout on
    every rebuild -- otherwise ghost Browse buttons pile up across command
    switches (the widget-lifecycle failure mode this window has hit before).
    Revisit each command to force repeated rebuilds; the live Browse count
    must always equal the current command's path-field count, never grow."""
    win = MainWindow()
    path_heavy = max(win._forms.values(),
                    key=lambda f: sum(1 for x in f.fields if x.kind == "path"))
    labels = sorted(win._forms)[:5] + [path_heavy.label]
    for label in labels * 2:
        win._command_box.setCurrentText(label)
        QTest.qWait(5)
        n_path = sum(1 for f in win._forms[label].fields if f.kind == "path")
        browse = win.findChildren(QPushButton, "field-browse")
        assert len(browse) == n_path, (label, len(browse), n_path)


def test_command_help_text_is_shown_and_updates_on_switch(qapp):
    win = MainWindow()
    with_help = [f for f in win._forms.values() if f.help_text]
    a, b = with_help[0], next(f for f in with_help if f.help_text != with_help[0].help_text)
    win._command_box.setCurrentText(a.label)
    assert win._help_label.text() == a.help_text
    win._command_box.setCurrentText(b.label)
    assert win._help_label.text() == b.help_text


def test_help_label_clears_when_switching_to_command_without_help(qapp):
    """'harvest' is the one headless command with no help text. Selecting it
    after a command that has help must EMPTY the label, not leave the prior
    command's help stale -- pins _rebuild_form's `or ""` clear behavior."""
    win = MainWindow()
    with_help = next(f for f in win._forms.values() if f.help_text)
    win._command_box.setCurrentText(with_help.label)
    assert win._help_label.text()  # precondition: label shows something
    win._command_box.setCurrentText("harvest")
    assert win._help_label.text() == ""


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


def test_window_forms_include_local_tools_with_class1_greyed():
    forms = {f.label: f for f in _window_forms()}
    assert "envmon inspect" in forms                    # headless, always
    # class-2 LOCAL tool: shown, runnable once local_python is set (no reason)
    assert forms["envmon import-edd"].unreachable_reason is None
    assert needs_arcpy_env(forms["envmon import-edd"].path)
    # class-1 redirect-only: shown but greyed, carries the reason
    assert forms["envmon import-gdb"].unreachable_reason


def test_class1_tool_disables_run_and_shows_reason(qapp, tmp_path):
    win, _ = _win_with_store(tmp_path)
    win._command_box.setCurrentText("envmon import-gdb")  # class-1 redirect-only
    assert not win._run_button.isEnabled()
    assert ".pyt" in win._status.text()


def test_class1_tool_stays_blocked_even_with_local_python(qapp, tmp_path):
    """local_python must NOT un-block a redirect-only (unreachable) tool --
    _run_blocked_reason checks unreachable before the local_python gate. Pins
    that precedence against a future reorder."""
    win, _ = _win_with_store(tmp_path, local_python="C:/pro/python.exe")
    win._command_box.setCurrentText("envmon import-gdb")  # class-1
    assert not win._run_button.isEnabled()
    assert ".pyt" in win._status.text()


def test_class2_local_tool_gated_until_local_python_set(qapp, tmp_path):
    win, _ = _win_with_store(tmp_path)  # no local_python
    win._command_box.setCurrentText("envmon validate-db")  # class-2 LOCAL
    assert not win._run_button.isEnabled()
    assert "arcgispro-py3" in win._status.text()


def test_class2_local_tool_runnable_with_local_python(qapp, tmp_path):
    win, _ = _win_with_store(tmp_path, local_python="C:/pro/python.exe")
    win._command_box.setCurrentText("envmon validate-db")
    assert win._run_button.isEnabled()


def test_headless_tool_runnable_without_local_python(qapp, tmp_path):
    win, _ = _win_with_store(tmp_path)
    win._command_box.setCurrentText("envmon inspect")
    assert win._run_button.isEnabled()


def test_setting_local_python_regates_run_and_persists(qapp, tmp_path):
    win, store = _win_with_store(tmp_path)          # no local_python
    win._command_box.setCurrentText("envmon validate-db")
    assert not win._run_button.isEnabled()          # blocked: needs local_python
    win._local_python_edit.setText("C:/pro/python.exe")
    win._on_local_python_changed()
    assert win._run_button.isEnabled()              # re-gated live
    assert settings_mod.get_local_python(store) == "C:/pro/python.exe"  # persisted


def test_browse_local_python_sets_state_and_persists(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(app_mod, "_pick_path", lambda *a, **k: "C:/pro/py.exe")
    win, store = _win_with_store(tmp_path)
    win._browse_local_python()
    assert win._local_python_edit.text() == "C:/pro/py.exe"
    assert win._local_python == "C:/pro/py.exe"
    assert settings_mod.get_local_python(store) == "C:/pro/py.exe"


def test_local_python_threaded_into_run_step(qapp, tmp_path, monkeypatch):
    captured = {}

    def fake_run_step(step, job_dir, **kw):
        captured.update(kw)
        return StepResult(Decision.CONTINUE, "ok", exit_code=0)

    monkeypatch.setattr(runner_mod, "run_step", fake_run_step)
    win, _ = _win_with_store(tmp_path, local_python="C:/pro/python.exe")
    _fill_required_fields(win, win._forms["envmon validate-db"])  # class-2 LOCAL
    win._on_run()
    _pump_until(lambda: win._run_button.isEnabled())
    assert captured.get("local_python") == "C:/pro/python.exe"


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
    form = _first_runnable(win)
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
    form = _first_runnable(win)
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
    form = _first_runnable(win)
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
    form = _first_runnable(win)
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
    form = _first_runnable(win)
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
    form = _first_runnable(win)
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
