"""PySide6 walking skeleton for the unified GUI adapter (ADR-0057).

One window: pick a headless command from ``introspect_cli()``, fill its
form, run it, see the result. Exercises the full toolkit-free chain built
so far (``introspect`` -> ``forms`` -> ``runner`` -> ``executor``) through a
real Qt event loop for the first time. Deliberately scoped to headless
(non-arcpy) commands only, so this first slice never needs a
``local_python`` (arcgispro-py3 clone) settings UI -- that is a later slice.

Threading: ``WorkflowRunner.advance()`` blocks for the length of one child
process. ``_StepWorker`` (a ``QThread``) runs it off the UI thread and
reports back via Qt signals (``finished``/``failed``) -- signals are the one
thread-safe way to touch widgets from another thread in Qt, which is why
``runner.py`` (ADR-0055) exposes a lock-guarded ``advance()``/``.status``
surface instead of inventing its own callback mechanism: this class is that
bridge, chosen now that there is an actual window to build it against.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow,
    QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from .executor import Decision, Step, StepResult, _SEV_ORDER, needs_arcpy_env
from .forms import FormValidationError, build_step
from .introspect import CommandForm, FormField, introspect_cli
from .runner import RunState, Workflow, WorkflowRunner

__all__ = ["MainWindow", "main"]


def _headless_forms() -> list[CommandForm]:
    """Commands runnable under plain ``sys.executable`` -- no LOCAL (arcpy)
    tool, no ``unreachable_reason``. LOCAL tools need a ``local_python``
    (arcgispro-py3 clone) picker, which is a later slice."""
    return [f for f in introspect_cli()
           if not f.unreachable_reason and not needs_arcpy_env(f.path)]


def _dialog_kind(field: FormField) -> str:
    """Which QFileDialog a path field's Browse button opens: a folder-only
    param always wants a directory picker; a bare-output path a save picker;
    anything else (an existing input) an open picker. ``is_dir`` wins over
    ``is_path_output`` because a directory is picked the same way whether it
    is read or written."""
    if field.is_dir:
        return "dir"
    return "save" if field.is_path_output else "open"


def _pick_path(kind: str, parent, title: str, start: str) -> str:
    """Open the native folder/save/open dialog for ``kind`` and return the
    chosen path, or "" if cancelled. Thin QFileDialog glue -- the one piece
    here a headless test can't drive (a modal native dialog); the ``kind``
    decision it acts on is :func:`_dialog_kind`, which is unit-tested, and
    the wiring around it (:meth:`MainWindow._browse`) is tested by stubbing
    this function out."""
    if kind == "dir":
        return QFileDialog.getExistingDirectory(parent, title, start)
    if kind == "save":
        return QFileDialog.getSaveFileName(parent, title, start)[0]
    return QFileDialog.getOpenFileName(parent, title, start)[0]


class _StepWorker(QThread):
    """Runs one WorkflowRunner.advance() off the UI thread."""

    finished_result = Signal(object)  # StepResult
    failed = Signal(str)

    def __init__(self, runner: WorkflowRunner, parent=None):
        super().__init__(parent)
        self._runner = runner

    def run(self) -> None:
        try:
            result = self._runner.advance()
        except Exception as exc:  # noqa: BLE001 -- report, don't crash the thread
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.finished_result.emit(result)


_DECISION_LABEL = {
    Decision.CONTINUE: "CONTINUE",
    Decision.HALT: "HALT",
    Decision.PAUSE_FOR_REVIEW: "PAUSE FOR REVIEW",
}

# QA severity -> cell-text color, chosen to read on both light and dark Qt
# themes (a saturated red/orange, a muted gray for INFO).
_SEV_COLOR = {"CRITICAL": "#d32f2f", "ERROR": "#d32f2f",
              "WARNING": "#ed6c02", "INFO": "#9e9e9e"}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AutoGIS -- GUI adapter (walking skeleton)")
        self._forms = {f.label: f for f in _headless_forms()}
        self._field_widgets: dict[str, QWidget] = {}
        self._worker: _StepWorker | None = None
        self._job_root: Path | None = None
        self._runner: WorkflowRunner | None = None
        self._steps: list[Step] = []
        self._run_is_workflow = False  # True during Run workflow; marks list rows

        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)

        self._command_box = QComboBox()
        self._command_box.addItems(sorted(self._forms))
        self._command_box.currentTextChanged.connect(self._rebuild_form)
        outer.addWidget(QLabel("Command:"))
        outer.addWidget(self._command_box)

        self._help_label = QLabel()
        self._help_label.setWordWrap(True)
        outer.addWidget(self._help_label)

        self._form_layout = QFormLayout()
        form_container = QWidget()
        form_container.setLayout(self._form_layout)
        outer.addWidget(form_container)

        row = QHBoxLayout()
        self._run_button = QPushButton("Run")
        self._run_button.clicked.connect(self._on_run)
        row.addWidget(self._run_button)
        outer.addLayout(row)

        # --- workflow builder (v1, ADR-0061) -----------------------------
        # The same command + form above configures each step; Add appends it
        # to an in-memory workflow the WorkflowRunner drives as one sequence.
        add_row = QHBoxLayout()
        self._add_button = QPushButton("+ Add to workflow")
        self._add_button.clicked.connect(self._on_add_step)
        self._pause_on_warning = QCheckBox("pause on warning")
        add_row.addWidget(self._add_button)
        add_row.addWidget(self._pause_on_warning)
        outer.addLayout(add_row)

        outer.addWidget(QLabel("Steps:"))
        self._step_list = QListWidget()
        outer.addWidget(self._step_list)

        wf_row = QHBoxLayout()
        self._remove_button = QPushButton("Remove")
        self._remove_button.clicked.connect(self._on_remove_step)
        self._up_button = QPushButton("↑")
        self._up_button.clicked.connect(lambda: self._move_step(-1))
        self._down_button = QPushButton("↓")
        self._down_button.clicked.connect(lambda: self._move_step(1))
        self._run_wf_button = QPushButton("Run workflow")
        self._run_wf_button.clicked.connect(self._on_run_workflow)
        self._clear_button = QPushButton("Clear")
        self._clear_button.clicked.connect(self._on_clear_steps)
        self._cancel_button = QPushButton("Cancel")
        self._cancel_button.clicked.connect(self._on_cancel)
        self._resume_button = QPushButton("Resume")
        self._resume_button.clicked.connect(self._on_resume)
        for _b in (self._remove_button, self._up_button, self._down_button,
                   self._run_wf_button, self._clear_button,
                   self._cancel_button, self._resume_button):
            wf_row.addWidget(_b)
        outer.addLayout(wf_row)
        # -----------------------------------------------------------------

        self._status = QLabel("")
        outer.addWidget(self._status)

        # Structured QA view: the executor already parses the injected
        # qa.csv into StepResult.qa_rows -- render it here as a sorted
        # (worst-severity-first), per-column, color-coded table (stdout only
        # shows it as flat text). Hidden until a run produces QA rows.
        self._qa_table = QTableWidget()
        self._qa_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._qa_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._qa_table.setVisible(False)
        outer.addWidget(self._qa_table)

        self._output = QPlainTextEdit()
        self._output.setReadOnly(True)
        outer.addWidget(self._output)

        if self._command_box.count():
            self._rebuild_form(self._command_box.currentText())
        self._refresh_step_controls()   # no steps yet -> step buttons disabled

    def _current_form(self) -> CommandForm | None:
        return self._forms.get(self._command_box.currentText())

    def _rebuild_form(self, label: str) -> None:
        while self._form_layout.rowCount():
            self._form_layout.removeRow(0)
        self._field_widgets.clear()
        form = self._forms.get(label)
        if form is None:
            self._help_label.clear()
            return
        self._help_label.setText(form.help_text or "")
        for field in form.fields:
            if field.kind == "flag":
                widget: QWidget = QCheckBox()
                widget.setChecked(bool(field.default))
            elif field.kind == "choice":
                widget = QComboBox()
                # A leading blank item: an untouched combo box otherwise
                # always sits on item 0, silently running the command with
                # a value that can differ from Click's own default (or, for
                # an optional field with no default, forcing a choice the
                # command would otherwise treat as unset) -- blank maps to
                # omitted via forms.py's own empty-string handling.
                widget.addItem("")
                widget.addItems(field.choices or ())
                if field.default is not None:
                    widget.setCurrentText(str(field.default))
            else:
                widget = QLineEdit()
                if field.default is not None:
                    widget.setText(str(field.default))
                if field.help_text:
                    widget.setPlaceholderText(field.help_text)
            label_text = field.label + (" *" if field.required else "")
            if field.kind == "path":
                # line edit stays the value widget (_raw_values reads it) and
                # stays editable -- Browse is a convenience over typing, which
                # is the only option for the many click.Path() params that are
                # file-or-dir ambiguous (see introspect.py).
                browse = QPushButton("Browse…")
                browse.clicked.connect(
                    lambda _=False, f=field, le=widget: self._browse(f, le))
                row = QHBoxLayout()
                row.addWidget(widget)
                row.addWidget(browse)
                self._form_layout.addRow(label_text, row)
            else:
                self._form_layout.addRow(label_text, widget)
            self._field_widgets[field.name] = widget

    def _browse(self, field: FormField, line: QLineEdit) -> None:
        """Open the right file/folder dialog for ``field`` and, if the user
        picks something, drop it into ``line``. The field stays editable, so
        a cancelled dialog (empty return) leaves whatever was typed."""
        path = _pick_path(_dialog_kind(field), self,
                          f"Select {field.label}", line.text())
        if path:
            line.setText(path)

    def _raw_values(self) -> dict[str, object]:
        values: dict[str, object] = {}
        for name, widget in self._field_widgets.items():
            if isinstance(widget, QCheckBox):
                values[name] = widget.isChecked()
            elif isinstance(widget, QComboBox):
                values[name] = widget.currentText()
            else:
                values[name] = widget.text()
        return values

    def _on_run(self) -> None:
        if self._runner is not None:
            return  # a run is already active
        form = self._current_form()
        if form is None:
            return
        try:
            step = build_step(form, self._raw_values())
        except FormValidationError as exc:
            self._status.setText(f"Fix before running: {exc}")
            return
        self._run_is_workflow = False
        self._start_run((step,), form.label)

    def _start_run(self, steps: "tuple[Step, ...]", name: str) -> None:
        """Shared entry for single Run and Run workflow: kick off a
        WorkflowRunner over ``steps`` and advance the first step. The drive
        loop (``_on_result``) carries it to a terminal/paused stop."""
        self._status.setText("Running...")
        self._output.clear()
        self._qa_table.setVisible(False)
        self._set_authoring_enabled(False)
        self._job_root = Path(tempfile.mkdtemp(prefix="autogis-gui-"))
        self._runner = WorkflowRunner(Workflow(name, steps), self._job_root)
        self._advance()

    def _advance(self) -> None:
        """Run the runner's next step off the UI thread on a fresh worker."""
        self._worker = _StepWorker(self._runner)
        self._worker.finished_result.connect(self._on_result)
        self._worker.failed.connect(self._on_failure)
        self._worker.start()

    def _set_authoring_enabled(self, enabled: bool) -> None:
        """Toggle every control that authors or starts a run. Disabled for the
        duration of a run (including while PAUSED); re-enabled by _finish_run.
        Step-list buttons defer to _refresh_step_controls so they only light up
        when there are actually steps to act on."""
        self._run_button.setEnabled(enabled)
        self._add_button.setEnabled(enabled)
        self._command_box.setEnabled(enabled)
        if enabled:
            self._refresh_step_controls()
        else:
            for b in (self._run_wf_button, self._clear_button,
                      self._remove_button, self._up_button, self._down_button):
                b.setEnabled(False)

    def _refresh_step_controls(self) -> None:
        """Enable the step-list buttons only when idle and steps exist."""
        active = bool(self._steps) and self._runner is None
        self._run_wf_button.setEnabled(active)
        self._clear_button.setEnabled(active)
        for b in (self._remove_button, self._up_button, self._down_button):
            b.setEnabled(active)

    def _step_summary(self, form_label: str, values: dict, pause: bool) -> str:
        """One-line row label: command + first non-empty text arg + pause tag."""
        hint = next((str(v) for v in values.values()
                     if isinstance(v, str) and v.strip()), "")
        hint = f" ({hint})" if hint else ""
        return f"{form_label}{hint}{'  [pause-on-warn]' if pause else ''}"

    def _on_add_step(self) -> None:
        if self._runner is not None:
            return
        form = self._current_form()
        if form is None:
            return
        values = self._raw_values()
        try:
            step = build_step(form, values)
        except FormValidationError as exc:
            self._status.setText(f"Fix before adding: {exc}")
            return
        step = replace(step,
                       pause_on_warning=self._pause_on_warning.isChecked())
        self._steps.append(step)
        self._step_list.addItem(
            self._step_summary(form.label, values, step.pause_on_warning))
        self._refresh_step_controls()

    def _on_remove_step(self) -> None:
        i = self._step_list.currentRow()
        if self._runner is not None or i < 0:
            return
        del self._steps[i]
        self._step_list.takeItem(i)
        self._refresh_step_controls()

    def _move_step(self, delta: int) -> None:
        i = self._step_list.currentRow()
        j = i + delta
        if self._runner is not None or i < 0 or not (0 <= j < len(self._steps)):
            return
        self._steps[i], self._steps[j] = self._steps[j], self._steps[i]
        self._step_list.insertItem(j, self._step_list.takeItem(i))
        self._step_list.setCurrentRow(j)

    def _on_clear_steps(self) -> None:
        if self._runner is not None:
            return
        self._steps.clear()
        self._step_list.clear()
        self._refresh_step_controls()

    def _on_run_workflow(self) -> None:
        if self._runner is not None or not self._steps:
            return
        self._run_is_workflow = True
        for i in range(self._step_list.count()):   # clear any prior-run glyphs
            item = self._step_list.item(i)
            item.setText(item.text().lstrip("✓⏸✗ "))
        self._cancel_button.setEnabled(True)
        self._resume_button.setEnabled(False)
        self._start_run(tuple(self._steps), "gui-workflow")

    def _on_cancel(self) -> None:
        if self._runner is None:
            return
        self._runner.cancel()
        self._cancel_button.setEnabled(False)
        self._resume_button.setEnabled(False)
        if self._runner.status is not RunState.RUNNING:
            # Cancel took effect immediately (idle/paused, no in-flight step):
            # no _on_result will fire to finish the run, so finish it here.
            self._status.setText("Cancelled")
            self._finish_run()

    def _on_resume(self) -> None:
        if self._runner is None or self._runner.status is not RunState.PAUSED:
            return
        self._runner.resume()
        self._resume_button.setEnabled(False)
        if self._runner.status is RunState.DONE:
            # Pause was on the LAST step -> resume() goes straight to DONE
            # (runner.resume docstring); nothing left to advance to.
            self._status.setText("Workflow complete")
            self._finish_run()
        else:
            self._advance()

    def _join_worker(self) -> None:
        # Thread-join ONLY (job-dir cleanup moved to _finish_run). A
        # multi-step workflow shares one job dir across its steps, so cleanup
        # must wait until the whole run ends, not fire after each step.
        #
        # finished_result/failed are emitted from inside run(), an instant
        # before the underlying OS thread actually terminates -- so by the
        # time this queued-connection handler runs on the main thread, the
        # thread is *usually* done but not provably so yet. wait() blocks
        # until it truly is (near-instant in practice). Skipping this is
        # undefined behavior: a QThread destroyed while its OS thread hasn't
        # fully settled can crash the process (0xC0000005; connecting Qt's own
        # `finished` signal to .wait() instead was NOT enough -- that queued
        # delivery isn't guaranteed to land before a caller drops the ref).
        if self._worker is not None:
            self._worker.wait()
            self._worker = None

    def _finish_run(self) -> None:
        """End the current run: clear the runner, re-enable authoring, and
        remove the shared job dir. Safe to call when already idle (guards on
        None) -- used by the terminal branches and by ``closeEvent``."""
        self._runner = None
        self._set_authoring_enabled(True)
        self._cancel_button.setEnabled(False)
        self._resume_button.setEnabled(False)
        if self._job_root is not None:
            shutil.rmtree(self._job_root, ignore_errors=True)
            self._job_root = None

    def closeEvent(self, event) -> None:
        # Closing while a step's subprocess is in flight would destroy the
        # still-running _StepWorker underneath it -- the same undefined-
        # behavior crash class _join_worker exists to prevent, but that
        # guard only runs once the worker's own signal is delivered, which
        # never happens if the event loop is already tearing down. Refuse
        # the close instead of blocking indefinitely for a subprocess this
        # code cannot force-kill (ADR-0055's documented limitation).
        if self._worker is not None and self._worker.isRunning():
            self._status.setText(
                "A step is still running -- please wait for it to finish "
                "before closing.")
            event.ignore()
            return
        # Idle or PAUSED (no thread in flight): join (a no-op when _worker is
        # None) then finish, so the shared job dir is cleaned up even for a
        # PAUSED workflow -- whose _worker is already None but whose
        # _runner/_job_root are still live and would otherwise leak on close.
        self._join_worker()
        self._finish_run()
        event.accept()

    def _show_qa(self, rows: "tuple[dict, ...]") -> None:
        """Render StepResult.qa_rows (parsed qa.csv) as a table -- worst
        severity first, with columns that are empty across every row dropped
        so the 15-field QARecord schema stays readable in a narrow window.
        Hidden when a run produced no QA rows (a command with no --report
        option, or a crash before any check ran)."""
        tbl = self._qa_table
        tbl.setRowCount(0)      # deletes every item + header (setColumnCount too)
        tbl.setColumnCount(0)
        if not rows:
            tbl.setVisible(False)
            return
        # csv.DictReader gives every row the same keys in qa.csv header order
        # (severity, category, message, ... from QARecord's field order).
        cols = [c for c in rows[0].keys()
                if any((r.get(c) or "").strip() for r in rows)]
        ordered = sorted(
            rows, key=lambda r: _SEV_ORDER.get(r.get("severity", ""), 9))
        tbl.setColumnCount(len(cols))
        tbl.setHorizontalHeaderLabels(cols)
        tbl.setRowCount(len(ordered))
        sev_col = cols.index("severity") if "severity" in cols else -1
        for i, row in enumerate(ordered):
            for j, col in enumerate(cols):
                # `or ""` (not a .get default): csv.DictReader fills a short
                # row's missing trailing fields with None, which str() would
                # otherwise render as the literal "None".
                item = QTableWidgetItem(str(row.get(col) or ""))
                if j == sev_col:
                    color = _SEV_COLOR.get(row.get("severity", ""))
                    if color is not None:
                        item.setForeground(QColor(color))
                tbl.setItem(i, j, item)
        # ponytail: full-scan resize on the UI thread; add a row cap if a tool
        # ever emits thousands of QA records (walking-skeleton scope: fine).
        tbl.resizeColumnsToContents()
        tbl.setVisible(True)

    def _render_result(self, result: StepResult, index: int) -> None:
        """Show one step's result in the shared status/output/QA widgets.
        ``index`` is the 0-based position of the step that just ran."""
        self._status.setText(_DECISION_LABEL[result.decision])
        text = [f"Decision: {_DECISION_LABEL[result.decision]}",
               f"Reason: {result.reason}"]
        if result.stdout:
            text += ["", "-- stdout --", result.stdout]
        if result.stderr:
            text += ["", "-- stderr --", result.stderr]
        self._output.setPlainText("\n".join(text))
        self._show_qa(result.qa_rows)
        if self._run_is_workflow and index < self._step_list.count():
            glyph = {Decision.CONTINUE: "✓", Decision.HALT: "✗",
                     Decision.PAUSE_FOR_REVIEW: "⏸"}[result.decision]
            item = self._step_list.item(index)
            item.setText(f"{glyph} {item.text().lstrip('✓⏸✗ ')}")

    def _terminal_message(self, state: RunState, index: int,
                          result: StepResult) -> str:
        if state is RunState.HALTED:
            return f"HALTED at step {index + 1}: {result.reason}"
        if state is RunState.CANCELLED:
            return "Cancelled"
        return "Workflow complete"  # DONE

    def _on_result(self, result: StepResult) -> None:
        self._join_worker()
        index = len(self._runner.results) - 1  # the step that just ran
        self._render_result(result, index)     # sets status to the decision label
        state = self._runner.status
        if state is RunState.PENDING:
            self._advance()                     # loop to the next step
        elif state is RunState.PAUSED:
            if self._run_is_workflow:
                self._status.setText(
                    f"PAUSED after step {index + 1} -- Resume or Cancel")
                self._resume_button.setEnabled(True)
        else:                                   # DONE / HALTED / CANCELLED
            if self._run_is_workflow:
                self._status.setText(
                    self._terminal_message(state, index, result))
            # A single Run keeps the decision label _render_result set
            # (today's UX: "CONTINUE"/"HALT"); only a workflow shows a
            # run-level message.
            self._finish_run()

    def _on_failure(self, message: str) -> None:
        self._join_worker()
        self._output.setPlainText(message)
        self._show_qa(())
        self._status.setText("Failed to run")
        self._finish_run()


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
