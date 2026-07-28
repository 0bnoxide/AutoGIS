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

from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit, QPushButton

import autogis.adapters.gui.app as app_mod
import autogis.adapters.gui.runner as runner_mod
from autogis.adapters.gui import settings as settings_mod
from autogis.adapters.gui.app import MainWindow, _dialog_kind, _window_forms
from autogis.adapters.gui.executor import (
    Decision, StepResult, build_argv, needs_arcpy_env,
)
from autogis.adapters.gui.forms import build_step
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


def test_window_forms_stamp_class1_unreachable_reason():
    forms = {f.label: f for f in _window_forms()}
    assert "envmon inspect" in forms                    # headless, always
    # class-2 LOCAL tool: shown, runnable once local_python is set (no reason)
    assert forms["envmon import-edd"].unreachable_reason is None
    assert needs_arcpy_env(forms["envmon import-edd"].path)
    # class-1 redirect-only: raw introspect still stamps the reason (the window
    # uses it to *hide* the command -- see test below).
    assert forms["envmon import-gdb"].unreachable_reason


def test_class1_redirect_only_tools_hidden_from_picker(qapp, tmp_path):
    """Class-1 redirect-only tools always HALT via the CLI, so the window omits
    them from the command picker entirely rather than offering a greyed,
    always-HALTing button ('only show what can run')."""
    win, _ = _win_with_store(tmp_path)
    labels = {win._command_box.itemText(i) for i in range(win._command_box.count())}
    assert "envmon import-gdb" not in labels             # class-1, hidden
    assert "envmon import-gdb" not in win._forms
    assert "envmon compare-drone-surfaces" not in labels  # newly-marked class-1
    assert "envmon validate-db" in labels                # class-2 LOCAL stays
    assert "envmon inspect" in labels                    # headless stays


def test_local_python_does_not_unhide_redirect_only_tools(qapp, tmp_path):
    """Setting a local_python makes class-2 arcpy tools runnable but must never
    surface a class-1 redirect-only tool -- it can only ever HALT."""
    win, _ = _win_with_store(tmp_path, local_python="C:/pro/python.exe")
    labels = {win._command_box.itemText(i) for i in range(win._command_box.count())}
    assert "envmon import-gdb" not in labels


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


def test_xor_group_field_gets_required_marker(qapp):
    win = MainWindow()
    form = next(f for f in win._forms.values()
               if any(fld.xor_group for fld in f.fields))
    win._command_box.setCurrentText(form.label)
    # pick the checkbox side of the xor pair -- its widget is added directly
    # (not wrapped in a Browse-button row), so labelForField resolves it.
    xor_field = next(fld for fld in form.fields
                     if fld.xor_group and fld.kind == "flag")
    label_widget = win._form_layout.labelForField(
        win._field_widgets[xor_field.name])
    assert label_widget.text() == xor_field.label + " *"


def test_typing_unmatched_command_text_disables_run(qapp):
    # The command box is now editable (with a completer) so typing can leave
    # it on text that matches no real command -- Run must disable and report
    # it instead of silently keeping the previous command's gated state.
    win = MainWindow()
    win._command_box.setCurrentText(_first_runnable(win).label)
    assert win._run_button.isEnabled()
    win._command_box.setCurrentText("not a real command")
    assert not win._run_button.isEnabled()
    assert win._status.text() == "No command selected."


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


def test_report_out_path_surfaced_in_output(qapp, monkeypatch):
    # #205: a successful copy-out of qa.csv to the user's --report path must be
    # shown -- the old behavior silently discarded the typed path.
    monkeypatch.setattr(
        runner_mod, "run_step",
        lambda step, job_dir, **kw: StepResult(
            Decision.CONTINUE, "ok", exit_code=0, stdout="hi",
            report_out=r"C:\out\REPORT_CLEAN"))
    win = MainWindow()
    _fill_required_fields(win, _first_runnable(win))
    win._on_run()
    _pump_until(lambda: win._run_button.isEnabled())
    assert r"C:\out\REPORT_CLEAN" in win._output.toPlainText()


def test_report_copy_error_surfaced_in_output(qapp, monkeypatch):
    # A failed copy-out must not stay silent (that was the original bug); the
    # QA decision is unaffected (still CONTINUE), the failure is just shown.
    monkeypatch.setattr(
        runner_mod, "run_step",
        lambda step, job_dir, **kw: StepResult(
            Decision.CONTINUE, "ok", exit_code=0,
            report_error="could not write report to C:\\bad\\x: denied"))
    win = MainWindow()
    _fill_required_fields(win, _first_runnable(win))
    win._on_run()
    _pump_until(lambda: win._run_button.isEnabled())
    assert "could not write report" in win._output.toPlainText()


# --- output-pane colorization (#205 comment) --------------------------------

def test_colorize_output_colors_lines_by_keyword():
    from autogis.adapters.gui.app import _colorize_output
    out = _colorize_output(
        "Decision: HALT\n"
        "[WARNING] vrms: high\n"
        "[INFO] done: 1/6 QA pass.\n"   # 'pass' must NOT override the INFO tag
        "Status: PASS")
    assert '#d32f2f">Decision: HALT' in out       # red for HALT/FAIL/ERROR
    assert '#ed6c02">[WARNING]' in out            # orange for WARNING/PAUSE
    assert '#1976d2">[INFO]' in out               # blue for INFO (not green)
    assert '#2e7d32">Status: PASS' in out         # green for CONTINUE/PASS


def test_colorize_output_escapes_html():
    from autogis.adapters.gui.app import _colorize_output
    out = _colorize_output("weird <tag> & stuff")
    assert "&lt;tag&gt;" in out and "&amp;" in out
    assert "<tag>" not in out                      # raw markup can't slip through


def test_output_pane_is_rich_text_and_colored(qapp, monkeypatch):
    monkeypatch.setattr(
        runner_mod, "run_step",
        lambda step, job_dir, **kw: StepResult(
            Decision.HALT, "QA FAIL: bad", exit_code=1, stdout="[ERROR] x: y"))
    win = MainWindow()
    _fill_required_fields(win, _first_runnable(win))
    win._on_run()
    _pump_until(lambda: win._run_button.isEnabled())
    assert "#d32f2f" in win._output.toHtml()       # HALT/FAIL/ERROR rendered red
    assert "QA FAIL" in win._output.toPlainText()  # plain text still readable


def test_failure_message_is_colorized_and_escaped(qapp, monkeypatch):
    # The failure pane is the same lower panel -- it must colorize (an
    # exception name reads red) and escape markup, not render raw.
    monkeypatch.setattr(
        runner_mod, "run_step",
        lambda step, job_dir, **kw: (_ for _ in ()).throw(ValueError("boom <x>")))
    win = MainWindow()
    _fill_required_fields(win, _first_runnable(win))
    win._on_run()
    _pump_until(lambda: win._run_button.isEnabled())
    assert "#d32f2f" in win._output.toHtml()         # "ValueError" -> red
    assert "boom <x>" in win._output.toPlainText()   # escaped, then round-trips
    assert win._status.text() == "Failed to run"


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


def test_suggested_choice_combo_is_editable_and_accepts_typed_text(qapp):
    win = MainWindow()
    win._command_box.setCurrentText("envmon build-conc-surface")
    w = win._field_widgets["matrix"]
    assert w.isEditable() is True
    w.setCurrentText("SED")                     # not in the suggestion list
    assert win._raw_values()["matrix"] == "SED"


def test_strict_choice_stays_non_editable(qapp):
    win = MainWindow()
    win._command_box.setCurrentText("envmon run-history")
    assert win._field_widgets["fmt"].isEditable() is False


def test_multichoice_renders_a_checklist_in_one_row(qapp):
    win = MainWindow()
    win._command_box.setCurrentText("envmon gen-synthetic-workbook")
    form = win._forms["envmon gen-synthetic-workbook"]
    assert win._form_layout.rowCount() == len(form.fields)   # still 1 row/field
    w = win._field_widgets["features"]
    w.item(0).setCheckState(Qt.Checked)
    w.item(1).setCheckState(Qt.Checked)
    assert "," in win._raw_values()["features"]


# ---- repeatable (multiple=True) fields -- #350 ----------------------------

def test_repeatable_field_emits_the_option_once_per_value(qapp):
    from autogis.adapters.gui.executor import build_argv
    from autogis.adapters.gui.forms import build_step
    win = MainWindow()
    win._command_box.setCurrentText("envmon coc advance")
    w = win._field_widgets["set_pairs"]
    w.set_values(["temperature_c=4.0", "carrier=FedEx"])   # helper on the container
    assert win._raw_values()["set_pairs"] == ["temperature_c=4.0", "carrier=FedEx"]
    form = win._forms["envmon coc advance"]
    step = build_step(form, {**win._raw_values(), "store_path": "s.json",
                             "to_state": "released", "actor": "t", "coc": "C-1"})
    assert build_argv(step.command, step.values).count("--set") == 2


def test_repeatable_container_is_one_form_row(qapp):
    win = MainWindow()
    win._command_box.setCurrentText("envmon coc advance")
    form = win._forms["envmon coc advance"]
    assert win._form_layout.rowCount() == len(form.fields)


def test_repeatable_values_skip_blank_rows(qapp):
    """An empty middle row is not an empty-string argument -- it's just not
    there, matching CommaList/build_argv's own "skip nothing" contract."""
    win = MainWindow()
    win._command_box.setCurrentText("envmon coc advance")
    w = win._field_widgets["set_pairs"]
    w.set_values(["a=1", "", "b=2"])
    assert w.values() == ["a=1", "b=2"]
    assert win._raw_values()["set_pairs"] == ["a=1", "b=2"]


def test_repeatable_empty_container_is_omitted(qapp):
    """No rows filled in -> field.repeatable's own _is_empty(()) -> None, so
    the option never reaches argv (same contract as every other blank field)."""
    win = MainWindow()
    win._command_box.setCurrentText("envmon coc advance")
    assert win._raw_values()["set_pairs"] == []


def test_repeatable_plus_button_adds_a_row_with_its_own_minus(qapp):
    win = MainWindow()
    win._command_box.setCurrentText("envmon coc advance")
    w = win._field_widgets["set_pairs"]
    assert len(w.findChildren(QPushButton, "repeatable-remove")) == 0  # lone row
    add = w.findChild(QPushButton, "repeatable-add")
    add.click()
    assert len(w.findChildren(QPushButton, "repeatable-remove")) == 1
    minus = w.findChildren(QPushButton, "repeatable-remove")[0]
    minus.click()
    assert len(w.findChildren(QPushButton, "repeatable-remove")) == 0
    assert w.values() == []  # both rows blank again


def test_repeatable_path_field_gets_its_own_browse_not_field_browse(qapp):
    """7-of-10-are-path constraint (#350): a repeatable path field's row(s)
    get a Browse button, but it must not be counted by the single-field
    ``field-browse`` probes (test_path_fields_render_a_browse_button_each &
    friends) -- envmon lab-qa-trends mixes a repeatable path (qc_paths) with
    3 plain path fields, so it exercises both counts at once."""
    win = MainWindow()
    win._command_box.setCurrentText("envmon lab-qa-trends")
    form = win._forms["envmon lab-qa-trends"]
    n_plain_path = sum(1 for f in form.fields if f.kind == "path" and not f.repeatable)
    w = win._field_widgets["qc_paths"]
    assert len(win.findChildren(QPushButton, "field-browse")) == n_plain_path
    assert len(w.findChildren(QPushButton, "repeatable-browse")) == 1
    w.findChild(QPushButton, "repeatable-add").click()
    assert len(w.findChildren(QPushButton, "repeatable-browse")) == 2
    assert len(win.findChildren(QPushButton, "field-browse")) == n_plain_path  # unaffected


def test_repeatable_choice_field_does_not_collapse_to_a_single_combo(qapp):
    """evaluate-readiness/portfolio-metrics --required-tool is a repeatable
    SuggestedChoice: the container keeps multiple values while each row offers
    the registry suggestions in an editable combo."""
    win = MainWindow()
    win._command_box.setCurrentText("envmon evaluate-readiness")
    w = win._field_widgets["required_tools"]
    assert not isinstance(w, QComboBox)
    w.set_values(["coc", "qualify"])
    combos = w.findChildren(QComboBox)
    assert len(combos) == 2
    assert all(combo.isEditable() for combo in combos)
    assert all(combo.findText("qualify") >= 0 for combo in combos)
    assert win._raw_values()["required_tools"] == ["coc", "qualify"]


def test_repeatable_container_gets_help_text_tooltip(qapp):
    win = MainWindow()
    win._command_box.setCurrentText("envmon coc advance")
    form = win._forms["envmon coc advance"]
    field = next(f for f in form.fields if f.name == "set_pairs")
    assert field.help_text  # sanity: this field actually has help
    assert win._field_widgets["set_pairs"].toolTip() == field.help_text


@pytest.mark.parametrize(
    ("state", "expected_flag"),
    [
        (None, None),
        (Qt.CheckState.Checked, "--incremental"),
        (Qt.CheckState.Unchecked, "--no-incremental"),
    ],
)
def test_harvest_incremental_checkbox_state_to_argv(
        qapp, state, expected_flag):
    win = MainWindow()
    form = win._forms["harvest"]
    win._command_box.setCurrentText(form.label)
    win._field_widgets["config_path"].setText("site.yaml")

    checkbox = win._field_widgets["incremental"]
    if state is None:
        assert checkbox.checkState() == Qt.CheckState.PartiallyChecked
    else:
        checkbox.setCheckState(state)

    step = build_step(form, win._raw_values())
    argv = build_argv(step.command, step.values)
    actual = {"--incremental", "--no-incremental"}.intersection(argv)

    assert actual == ({expected_flag} if expected_flag else set())


def test_ordinary_flags_stay_two_state(qapp):
    """Only a default=None flag becomes tri-state.

    Without this the suite would still pass if *every* checkbox were made
    tri-state -- and an ordinary default=False flag rendered partially
    checked would start omitting itself instead of sending False. harvest
    carries the only nullable flag in the tree, so the negative control has
    to come from a different command.
    """
    win = MainWindow()
    form = win._forms["envmon init-site"]
    win._command_box.setCurrentText(form.label)

    two_state = [f for f in form.fields
                 if f.kind == "flag" and f.default is not None]
    assert two_state, "expected at least one ordinary flag on init-site"
    values = win._raw_values()
    for field in two_state:
        widget = win._field_widgets[field.name]
        assert not widget.isTristate(), field.name
        assert values[field.name] is bool(field.default), field.name


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


def test_single_run_finishes_and_clears_run_state(qapp, monkeypatch):
    # The drive-loop refactor (ADR-0063): a single Run is a 1-step workflow
    # through the shared loop -- it must end with the runner cleared and the
    # shared job dir removed, and keep today's decision-label status.
    monkeypatch.setattr(
        runner_mod, "run_step",
        lambda step, job_dir, **kw: StepResult(
            Decision.CONTINUE, "ok", exit_code=0, stdout="hi"))
    win = MainWindow()
    form = next(iter(win._forms.values()))
    _fill_required_fields(win, form)
    win._on_run()
    _pump_until(lambda: win._run_button.isEnabled())
    assert "CONTINUE" in win._status.text()   # single-run keeps decision label
    assert win._runner is None                # run finished, state cleared
    assert win._job_root is None              # shared job dir cleaned up


# --- single Run honors pause-on-warning (#205) -------------------------------

def test_single_run_passes_pause_on_warning_from_checkbox(qapp, monkeypatch):
    # The checkbox next to Run must reach a single Run's Step, not only steps
    # added to a workflow (the silent-ignore the screenshot in #205 showed).
    captured = {}

    def fake_run_step(step, job_dir, **kw):
        captured["pause"] = step.pause_on_warning
        return StepResult(Decision.CONTINUE, "ok", exit_code=0)

    monkeypatch.setattr(runner_mod, "run_step", fake_run_step)
    win = MainWindow()
    _fill_required_fields(win, _first_runnable(win))
    win._pause_on_warning.setChecked(True)
    win._on_run()
    _pump_until(lambda: win._run_button.isEnabled())
    assert captured["pause"] is True


def test_single_run_pauses_on_warning_and_resumes(qapp, monkeypatch):
    monkeypatch.setattr(
        runner_mod, "run_step",
        lambda step, job_dir, **kw: StepResult(
            Decision.PAUSE_FOR_REVIEW, "warnings", exit_code=0))
    win = MainWindow()
    _fill_required_fields(win, _first_runnable(win))
    win._pause_on_warning.setChecked(True)
    win._on_run()
    _pump_until(lambda: win._resume_button.isEnabled())
    assert win._runner is not None                 # paused, NOT finished
    assert "PAUSED" in win._status.text()
    win._on_resume()                                # 1-step workflow -> DONE
    _pump_until(lambda: win._runner is None)
    assert "complete" in win._status.text().lower()


def test_single_run_cancel_while_paused_ends_run(qapp, monkeypatch):
    monkeypatch.setattr(
        runner_mod, "run_step",
        lambda step, job_dir, **kw: StepResult(
            Decision.PAUSE_FOR_REVIEW, "warnings", exit_code=0))
    win = MainWindow()
    _fill_required_fields(win, _first_runnable(win))
    win._pause_on_warning.setChecked(True)
    win._on_run()
    _pump_until(lambda: win._resume_button.isEnabled())
    win._on_cancel()
    _pump_until(lambda: win._runner is None)
    assert "Cancelled" in win._status.text()
    assert win._job_root is None                   # job dir cleaned on cancel


def test_single_run_cancel_while_running_shows_cancelled(qapp, monkeypatch):
    # Enabling Cancel for single Run (#205 C) makes mid-flight cancel reachable;
    # a deferred cancel lets the step finish, so the status must read "Cancelled",
    # not the completed step's decision label.
    release = threading.Event()

    def fake(step, job_dir, **kw):
        release.wait(timeout=5)
        return StepResult(Decision.CONTINUE, "ok", exit_code=0)

    monkeypatch.setattr(runner_mod, "run_step", fake)
    win = MainWindow()
    _fill_required_fields(win, _first_runnable(win))
    win._on_run()
    QTest.qWait(50)                                # step in flight
    win._on_cancel()                                # deferred: step still running
    release.set()
    _pump_until(lambda: win._runner is None)
    assert "Cancelled" in win._status.text()


# --- workflow builder: authoring (Task 2, ADR-0063) --------------------------

def test_add_step_appends_to_list(qapp):
    win = MainWindow()
    form = win._forms["envmon validate-rtk-survey"]
    win._command_box.setCurrentText(form.label)
    win._field_widgets["csv_path"].setText("rtk.csv")
    win._on_add_step()
    assert len(win._steps) == 1
    assert win._step_list.count() == 1
    assert "validate-rtk-survey" in win._step_list.item(0).text()
    assert win._run_wf_button.isEnabled()     # a step exists -> runnable


def test_save_recipe_writes_valid_reloadable_recipe(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    from autogis.adapters.recipe_workflow import recipe_to_workflow
    from autogis.core.common.workflow_recipe import load_recipe

    win = MainWindow()
    form = win._forms["envmon validate-rtk-survey"]
    win._command_box.setCurrentText(form.label)
    win._field_widgets["csv_path"].setText("rtk.csv")
    win._on_add_step()
    assert win._save_button.isEnabled()          # enabled once a step exists

    out = tmp_path / "wf.yaml"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(out), "")))
    win._on_save_recipe()

    assert out.exists()
    data = load_recipe(out)                       # written file validates
    assert data["steps"][0]["command"] == ["envmon", "validate-rtk-survey"]
    assert recipe_to_workflow(data).steps == tuple(win._steps)   # round-trips to the built steps


def test_save_recipe_disabled_during_active_run(qapp):
    """Save must be disabled while a run is active/paused (like the other step
    controls), not merely no-op when clicked. Codex P2."""
    win = MainWindow()
    win._command_box.setCurrentText(win._forms["envmon validate-rtk-survey"].label)
    win._field_widgets["csv_path"].setText("rtk.csv")
    win._on_add_step()
    assert win._save_button.isEnabled()
    win._set_authoring_enabled(False)          # a run starts
    assert not win._save_button.isEnabled()
    win._set_authoring_enabled(True)           # run finished, steps remain
    assert win._save_button.isEnabled()


def test_save_recipe_noop_when_dialog_cancelled(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    win = MainWindow()
    win._command_box.setCurrentText(win._forms["envmon validate-rtk-survey"].label)
    win._field_widgets["csv_path"].setText("rtk.csv")
    win._on_add_step()
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: ("", "")))   # cancelled
    win._on_save_recipe()
    assert list(tmp_path.iterdir()) == []         # nothing written


def test_add_step_invalid_form_shows_error_adds_nothing(qapp):
    win = MainWindow()
    form = next(f for f in win._forms.values()
               if any(fld.required for fld in f.fields))
    win._command_box.setCurrentText(form.label)   # required left blank
    win._on_add_step()
    assert "Fix before adding" in win._status.text()
    assert win._steps == []
    assert win._step_list.count() == 0


def test_pause_on_warning_checkbox_sets_step_flag(qapp):
    win = MainWindow()
    form = win._forms["envmon validate-rtk-survey"]
    win._command_box.setCurrentText(form.label)
    win._field_widgets["csv_path"].setText("rtk.csv")
    win._pause_on_warning.setChecked(True)
    win._on_add_step()
    assert win._steps[0].pause_on_warning is True
    assert "[pause-on-warn]" in win._step_list.item(0).text()


def _add_step(win, label, csv="x.csv", pause=False):
    win._command_box.setCurrentText(label)
    if "csv_path" in win._field_widgets:
        win._field_widgets["csv_path"].setText(csv)
    win._pause_on_warning.setChecked(pause)
    win._on_add_step()


def test_move_and_remove_reorder_steps_and_list_in_lockstep(qapp):
    win = MainWindow()
    _add_step(win, "envmon validate-rtk-survey", csv="a.csv")
    _add_step(win, "envmon validate-rtk-survey", csv="b.csv")
    assert len(win._steps) == 2
    top_before = win._steps[0]
    win._step_list.setCurrentRow(0)
    win._move_step(1)                       # swap rows 0 and 1
    assert win._step_list.currentRow() == 1
    assert win._steps[1] is top_before      # the step object moved down
    win._step_list.setCurrentRow(0)
    win._on_remove_step()
    assert len(win._steps) == 1 and win._step_list.count() == 1
    assert win._steps[0] is top_before      # the other one was removed


def test_clear_empties_steps_and_disables_run_workflow(qapp):
    win = MainWindow()
    _add_step(win, "envmon validate-rtk-survey")
    assert win._run_wf_button.isEnabled()
    win._on_clear_steps()
    assert win._steps == [] and win._step_list.count() == 0
    assert not win._run_wf_button.isEnabled()


# --- workflow builder: running (Task 3, ADR-0063) ----------------------------

def _script_run_step(monkeypatch, results):
    """Make run_step return `results` in order across successive calls; the
    returned dict's ["n"] counts how many steps actually ran."""
    it = iter(results)
    calls = {"n": 0}

    def fake(step, job_dir, **kw):
        calls["n"] += 1
        return next(it)

    monkeypatch.setattr(runner_mod, "run_step", fake)
    return calls


def test_two_step_workflow_runs_both_to_done(qapp, monkeypatch):
    calls = _script_run_step(monkeypatch, [
        StepResult(Decision.CONTINUE, "ok", exit_code=0),
        StepResult(Decision.CONTINUE, "ok", exit_code=0)])
    win = MainWindow()
    _add_step(win, "envmon validate-rtk-survey", csv="a.csv")
    _add_step(win, "envmon validate-rtk-survey", csv="b.csv")
    win._on_run_workflow()
    _pump_until(lambda: win._runner is None)
    assert calls["n"] == 2
    assert "complete" in win._status.text().lower()
    assert win._step_list.item(0).text().startswith("✓")
    assert win._step_list.item(1).text().startswith("✓")
    assert win._add_button.isEnabled()          # authoring re-enabled


def test_halt_stops_before_later_steps(qapp, monkeypatch):
    calls = _script_run_step(monkeypatch, [
        StepResult(Decision.HALT, "QA FAIL", exit_code=1),
        StepResult(Decision.CONTINUE, "ok", exit_code=0)])  # must never run
    win = MainWindow()
    _add_step(win, "envmon validate-rtk-survey", csv="a.csv")
    _add_step(win, "envmon validate-rtk-survey", csv="b.csv")
    win._on_run_workflow()
    _pump_until(lambda: win._runner is None)
    assert calls["n"] == 1                       # second step never ran
    assert "HALTED at step 1" in win._status.text()
    assert win._step_list.item(0).text().startswith("✗")


def test_pause_on_warning_then_resume_runs_next(qapp, monkeypatch):
    calls = _script_run_step(monkeypatch, [
        StepResult(Decision.PAUSE_FOR_REVIEW, "warnings", exit_code=0),
        StepResult(Decision.CONTINUE, "ok", exit_code=0)])
    win = MainWindow()
    _add_step(win, "envmon validate-rtk-survey", csv="a.csv", pause=True)
    _add_step(win, "envmon validate-rtk-survey", csv="b.csv")
    win._on_run_workflow()
    _pump_until(lambda: win._resume_button.isEnabled())
    assert "PAUSED" in win._status.text()
    assert calls["n"] == 1                       # paused before step 2
    assert not win._add_button.isEnabled()       # authoring stays locked
    win._on_resume()
    _pump_until(lambda: win._runner is None)
    assert calls["n"] == 2
    assert "complete" in win._status.text().lower()


def test_pause_on_last_step_resume_completes(qapp, monkeypatch):
    _script_run_step(monkeypatch, [
        StepResult(Decision.PAUSE_FOR_REVIEW, "warnings", exit_code=0)])
    win = MainWindow()
    _add_step(win, "envmon validate-rtk-survey", pause=True)   # single, pauses
    win._on_run_workflow()
    _pump_until(lambda: win._resume_button.isEnabled())
    win._on_resume()                              # nothing left -> straight to DONE
    _pump_until(lambda: win._runner is None)
    assert "complete" in win._status.text().lower()


def test_cancel_when_paused_ends_run(qapp, monkeypatch):
    _script_run_step(monkeypatch, [
        StepResult(Decision.PAUSE_FOR_REVIEW, "warnings", exit_code=0),
        StepResult(Decision.CONTINUE, "ok", exit_code=0)])
    win = MainWindow()
    _add_step(win, "envmon validate-rtk-survey", csv="a.csv", pause=True)
    _add_step(win, "envmon validate-rtk-survey", csv="b.csv")
    win._on_run_workflow()
    _pump_until(lambda: win._resume_button.isEnabled())
    win._on_cancel()
    _pump_until(lambda: win._runner is None)
    assert "Cancelled" in win._status.text()
    assert win._add_button.isEnabled()           # authoring re-enabled after cancel


def test_cancel_during_running_step_ends_after_it_completes(qapp, monkeypatch):
    # Deferred cancel: a step is in flight, so _on_cancel must NOT finish the
    # run (a worker exists -> its _on_result will); the run ends CANCELLED once
    # that step completes, and later steps never run.
    release = threading.Event()
    calls = {"n": 0}

    def fake(step, job_dir, **kw):
        calls["n"] += 1
        release.wait(timeout=5)
        return StepResult(Decision.CONTINUE, "ok", exit_code=0)

    monkeypatch.setattr(runner_mod, "run_step", fake)
    win = MainWindow()
    _add_step(win, "envmon validate-rtk-survey", csv="a.csv")
    _add_step(win, "envmon validate-rtk-survey", csv="b.csv")
    win._on_run_workflow()
    QTest.qWait(50)                        # step 1 in flight, blocked on release
    win._on_cancel()
    assert win._runner is not None         # NOT finished -- a worker is in flight
    release.set()
    _pump_until(lambda: win._runner is None)
    assert "Cancelled" in win._status.text()
    assert calls["n"] == 1                 # step 2 never ran


def test_second_workflow_run_resets_output_and_glyphs(qapp, monkeypatch):
    # Regression coverage for #293: a second "Run workflow" in the same
    # session reported stale stdout and stale checkmarks carried over from
    # the first run. No test ever ran a workflow twice on one MainWindow
    # before this. Run 1 completes both steps (✓✓); run 2 HALTs on step 1,
    # so step 2 never re-renders in run 2 -- its glyph must come back to the
    # original unrun text, not keep run 1's stale ✓.
    orig_texts = None
    _script_run_step(monkeypatch, [
        StepResult(Decision.CONTINUE, "run1-step1", exit_code=0),
        StepResult(Decision.CONTINUE, "run1-step2", exit_code=0)])
    win = MainWindow()
    _add_step(win, "envmon validate-rtk-survey", csv="a.csv")
    _add_step(win, "envmon validate-rtk-survey", csv="b.csv")
    orig_texts = [win._step_list.item(i).text() for i in range(2)]
    win._on_run_workflow()
    _pump_until(lambda: win._runner is None)
    assert win._step_list.item(0).text().startswith("✓")
    assert win._step_list.item(1).text().startswith("✓")
    assert "run1-step2" in win._output.toPlainText()

    _script_run_step(monkeypatch, [
        StepResult(Decision.HALT, "run2-step1-fail", exit_code=1)])
    win._on_run_workflow()
    # Reset happens synchronously in _on_run_workflow/_start_run, before the
    # worker thread for step 1 has even started.
    assert win._output.toPlainText() == ""
    assert win._step_list.item(0).text() == orig_texts[0]
    assert win._step_list.item(1).text() == orig_texts[1]
    _pump_until(lambda: win._runner is None)
    assert win._step_list.item(0).text().startswith("✗")
    assert win._step_list.item(1).text() == orig_texts[1]   # never re-ran in run 2
    assert "run2-step1-fail" in win._output.toPlainText()
    assert "run1-step2" not in win._output.toPlainText()


def test_workflow_repaints_reset_and_each_completed_step(qapp, monkeypatch):
    # #293 reproduced on a real display even though widget state was already
    # correct: a fast step could queue the next worker before Qt painted the
    # reset or the completed step. Pin the two visible repaint boundaries.
    _script_run_step(monkeypatch, [
        StepResult(Decision.CONTINUE, "step1", exit_code=0),
        StepResult(Decision.CONTINUE, "step2", exit_code=0)])
    win = MainWindow()
    _add_step(win, "envmon validate-rtk-survey", csv="a.csv")
    _add_step(win, "envmon validate-rtk-survey", csv="b.csv")
    snapshots = []
    monkeypatch.setattr(
        win, "_repaint_run_widgets",
        lambda: snapshots.append((
            win._output.toPlainText(),
            tuple(win._step_list.item(i).text() for i in range(2)),
        )),
        raising=False,
    )

    win._on_run_workflow()
    _pump_until(lambda: win._runner is None)

    assert snapshots[0][0] == ""
    assert not snapshots[0][1][0].startswith("✓")
    assert "step1" in snapshots[1][0]
    assert snapshots[1][1][0].startswith("✓")


def test_close_while_paused_cleans_up_job_dir(qapp, monkeypatch):
    _script_run_step(monkeypatch, [
        StepResult(Decision.PAUSE_FOR_REVIEW, "warnings", exit_code=0),
        StepResult(Decision.CONTINUE, "ok", exit_code=0)])
    win = MainWindow()
    _add_step(win, "envmon validate-rtk-survey", csv="a.csv", pause=True)
    _add_step(win, "envmon validate-rtk-survey", csv="b.csv")
    win._on_run_workflow()
    _pump_until(lambda: win._resume_button.isEnabled())   # PAUSED
    assert win._job_root is not None       # temp job dir exists while paused
    assert win.close()                     # no worker in flight -> close allowed
    assert win._runner is None
    assert win._job_root is None           # job dir cleaned on close


def test_editing_local_python_while_paused_keeps_run_gated(qapp, monkeypatch):
    # Merge seam (ADR-0062 x ADR-0063): _sync_run_availability must treat a
    # live runner (incl. PAUSED, where _worker is None) as "running" -- editing
    # local_python mid-pause must NOT enable Run or wipe the pause prompt.
    _script_run_step(monkeypatch, [
        StepResult(Decision.PAUSE_FOR_REVIEW, "warnings", exit_code=0),
        StepResult(Decision.CONTINUE, "ok", exit_code=0)])
    win = MainWindow()
    _add_step(win, "envmon validate-rtk-survey", csv="a.csv", pause=True)
    _add_step(win, "envmon validate-rtk-survey", csv="b.csv")
    win._on_run_workflow()
    _pump_until(lambda: win._resume_button.isEnabled())   # PAUSED
    assert "PAUSED" in win._status.text()
    win._local_python_edit.setText("C:/x/python.exe")
    win._on_local_python_changed()                        # edit while paused
    assert not win._run_button.isEnabled()                # Run stays gated
    assert "PAUSED" in win._status.text()                 # pause prompt intact
    win._on_resume()                                       # finish cleanly
    _pump_until(lambda: win._runner is None)


def test_every_field_widget_gets_its_help_as_a_tooltip(qapp):
    win = MainWindow()
    # envmon run-history has a flag-free mix incl. a choice with help text.
    win._command_box.setCurrentText("envmon run-history")
    form = win._forms["envmon run-history"]
    for field in form.fields:
        if not field.help_text:
            continue
        assert win._field_widgets[field.name].toolTip() == field.help_text, field.name


def test_tooltip_reaches_choice_and_flag_widgets(qapp):
    """Regression for #356: the choice/flag branches never touched help_text."""
    win = MainWindow()
    win._command_box.setCurrentText("envmon run-history")
    status = win._field_widgets["status"]          # QComboBox, has help
    assert status.toolTip() == "Filter by run status."
    # Verify flag widgets also get help text as tooltip (the #356 regression
    # for flags: init-site --force is a flag with help text).
    win._command_box.setCurrentText("envmon init-site")
    force = win._field_widgets["force"]                   # QCheckBox, has help
    assert force.toolTip() == "Overwrite existing target files (default: refuse)."


def test_raw_values_rejects_an_unknown_widget_type(qapp):
    """A widget class nobody taught _raw_values about must fail loudly, not
    fall through to .text() and ship whatever string Qt happens to render.
    QLabel is the stand-in -- it will never be a form *value* widget, so
    unlike QSpinBox (Task 10) and QDateEdit (Task 11) before it, this probe
    can't go stale as more kinds get handled."""
    from PySide6.QtWidgets import QLabel
    win = MainWindow()
    win._command_box.setCurrentText("envmon run-history")
    win._field_widgets["limit"] = QLabel()  # never a value widget
    with pytest.raises(TypeError, match="QLabel"):
        win._raw_values()


def test_open_ended_numeric_stays_text_and_starts_blank(qapp):
    """A finite Qt range would narrow Click's open-ended timeout contract."""
    win = MainWindow()
    win._command_box.setCurrentText("envmon run-recipe")
    w = win._field_widgets["timeout"]
    assert isinstance(w, QLineEdit)
    assert win._raw_values()["timeout"] == ""   # -> omitted by forms._normalize


def test_closed_range_number_round_trips_to_argv(qapp):
    from PySide6.QtWidgets import QDoubleSpinBox

    win = MainWindow()
    win._command_box.setCurrentText("envmon reconcile-locations")
    threshold = win._field_widgets["threshold"]
    assert isinstance(threshold, QDoubleSpinBox)
    threshold.setValue(0.75)
    argv = build_argv(
        ("envmon", "reconcile-locations"),
        {"threshold": win._raw_values()["threshold"]},
    )
    assert argv[argv.index("--threshold") + 1] == "0.75"


def test_large_unbounded_coordinate_is_not_clamped(qapp):
    win = MainWindow()
    win._command_box.setCurrentText("envmon manage-callout-overrides lock")
    anchor_x = win._field_widgets["anchor_x"]
    assert isinstance(anchor_x, QLineEdit)
    anchor_x.setText("2500000.125")
    assert win._raw_values()["anchor_x"] == "2500000.125"


def test_float_uses_c_locale_so_a_comma_decimal_machine_cannot_break_it(qapp):
    from PySide6.QtCore import QLocale
    win = MainWindow()
    win._command_box.setCurrentText("envmon reconcile-locations")
    w = win._field_widgets["threshold"]
    assert w.locale() == QLocale.c()


def test_window_can_shrink_below_the_form_height(qapp):
    """#357: the layout minimum pinned the window to ~874x871, putting the Run
    button and output pane permanently off-screen on a 768p display."""
    win = MainWindow()
    win._command_box.setCurrentText("envmon build-conc-surface")  # 15 fields
    win.resize(400, 300)
    qapp.processEvents()
    assert win.minimumSizeHint().height() < 700


def test_date_field_is_a_calendar_and_defaults_to_none(qapp):
    from PySide6.QtWidgets import QDateEdit
    win = MainWindow()
    win._command_box.setCurrentText("envmon gw-level-summary")
    w = win._field_widgets["event_date"]
    assert isinstance(w, QDateEdit)
    assert w.calendarPopup() is True
    assert win._raw_values()["event_date"] == ""


def test_picked_date_serializes_as_iso(qapp):
    from PySide6.QtCore import QDate
    win = MainWindow()
    win._command_box.setCurrentText("envmon gw-level-summary")
    win._field_widgets["event_date"].setDate(QDate(2026, 7, 25))
    assert win._raw_values()["event_date"] == "2026-07-25"


def test_sync_survey123_preserves_timestamp_and_uses_folder_picker(qapp):
    """The Phase 2 command landed after this branch's original inventory."""
    win = MainWindow()
    form = win._forms["envmon sync-survey123"]
    win._command_box.setCurrentText(form.label)
    fields = {field.name: field for field in form.fields}

    since = win._field_widgets["since_date"]
    assert isinstance(since, QLineEdit)
    since.setText("2026-07-26T14:30:00-06:00")
    assert win._raw_values()["since_date"] == "2026-07-26T14:30:00-06:00"
    assert fields["out_dir"].is_dir is True
    assert _dialog_kind(fields["out_dir"]) == "dir"


# ---- Task 14: nargs>1, tri-state flag, xor greying ------------------------

def test_bbox_nargs4_stays_a_line_edit_and_emits_four_separate_tokens(qapp):
    """#351: --bbox is nargs=4 float -- if the numeric branch claimed it
    first it would render a QDoubleSpinBox, which can only hold one number.
    The nargs>1 check must win so it stays a plain QLineEdit."""
    from PySide6.QtWidgets import QDoubleSpinBox

    win = MainWindow()
    win._command_box.setCurrentText("envmon download-dem")
    bbox_widget = win._field_widgets["bbox"]
    assert isinstance(bbox_widget, QLineEdit)
    assert not isinstance(bbox_widget, QDoubleSpinBox)
    bbox_widget.setText("-105 39 -104 40")
    step = build_step(win._forms["envmon download-dem"],
                      {**win._raw_values(), "out_path": "x.tif"})
    argv = build_argv(step.command, step.values)
    i = argv.index("--bbox")
    assert argv[i + 1:i + 5] == ["-105", "39", "-104", "40"]


def test_filling_one_xor_side_disables_the_other_but_keeps_its_text(qapp):
    """Owner decision (spec Sec 4.1a): filling one xor sibling disables the
    complete control but preserves its typed text; clearing re-enables both."""
    win = MainWindow()
    win._command_box.setCurrentText("envmon update-well-elevations")
    gdb, csv = win._field_widgets["gdb"], win._field_widgets["wells_csv"]
    gdb_browse = win._field_browse_buttons["gdb"]
    csv_browse = win._field_browse_buttons["wells_csv"]
    gdb.setText("C:/old/site.gdb")
    qapp.processEvents()
    assert csv.isEnabled() is False
    assert csv_browse.isEnabled() is False
    csv.setText("C:/data/wells.csv")
    qapp.processEvents()
    assert gdb.isEnabled() is False
    assert gdb_browse.isEnabled() is False
    assert gdb.text() == "C:/old/site.gdb"      # preserved, per owner decision
    csv.clear()
    qapp.processEvents()
    assert gdb.isEnabled() is True
    assert gdb_browse.isEnabled() is True


def test_reconcile_locations_gdb_flag_pair_is_left_ungreyed(qapp):
    """reconcile-locations' --gdb unconditionally HALTs ("use the .pyt
    toolbox" -- cli.py's reconcile_locations_cmd): greying its wells_csv
    sibling would steer the user into that dead end, so this specific pair
    is deliberately left alone (see app.py's ponytail comment)."""
    win = MainWindow()
    win._command_box.setCurrentText("envmon reconcile-locations")
    gdb, wells_csv = win._field_widgets["gdb"], win._field_widgets["wells_csv"]
    gdb.setChecked(True)
    qapp.processEvents()
    assert wells_csv.isEnabled() is True
