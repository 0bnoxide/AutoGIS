"""PySide6 walking skeleton for the unified GUI adapter (ADR-0057, ADR-0062).

One window: pick a command from ``introspect_cli()``, fill its form, run it,
see the result. Exercises the full toolkit-free chain (``introspect`` ->
``forms`` -> ``runner`` -> ``executor``) through a real Qt event loop.
Headless commands run under ``sys.executable``; LOCAL (arcpy) tools run under
a user-set ``local_python`` (a cloned arcgispro-py3 ``python.exe``, persisted
via ``settings.py`` -- ADR-0062), with the Run button gated until one is set.
Class-1 redirect-only LOCAL tools (``reachability.UNREACHABLE``) are shown
greyed with the reason, since they never execute via the CLI anyway.

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
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QPlainTextEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from . import settings
from .executor import Decision, StepResult, _SEV_ORDER, needs_arcpy_env
from .forms import FormValidationError, build_step
from .introspect import CommandForm, FormField, introspect_cli
from .reachability import UNREACHABLE
from .runner import Workflow, WorkflowRunner

__all__ = ["MainWindow", "main"]


def _window_forms() -> list[CommandForm]:
    """Every leaf command the window offers. Class-1 redirect-only LOCAL tools
    are stamped ``unreachable_reason`` (``reachability.UNREACHABLE``) so they
    render greyed; headless and class-2 (arcpy-executable) LOCAL tools carry no
    reason -- the latter become runnable once a ``local_python`` is set."""
    return introspect_cli(unreachable=UNREACHABLE)


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
    def __init__(self, settings_store=None):
        super().__init__()
        self.setWindowTitle("AutoGIS -- GUI adapter (walking skeleton)")
        self._settings = settings_store  # None -> real per-user QSettings
        self._local_python = settings.get_local_python(settings_store)
        self._forms = {f.label: f for f in _window_forms()}
        self._field_widgets: dict[str, QWidget] = {}
        self._worker: _StepWorker | None = None
        self._job_root: Path | None = None

        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)

        # local_python: the arcgispro-py3 python.exe LOCAL (arcpy) tools run
        # under. Persisted (settings.py) so it survives launches; editing or
        # browsing re-gates the Run button for the current command.
        lp_row = QHBoxLayout()
        lp_row.addWidget(QLabel("local_python:"))
        self._local_python_edit = QLineEdit(self._local_python or "")
        self._local_python_edit.setPlaceholderText(
            "arcgispro-py3 python.exe -- needed to run LOCAL (arcpy) tools")
        self._local_python_edit.editingFinished.connect(
            self._on_local_python_changed)
        lp_row.addWidget(self._local_python_edit)
        lp_browse = QPushButton("Browse…")
        lp_browse.clicked.connect(self._browse_local_python)
        lp_row.addWidget(lp_browse)
        outer.addLayout(lp_row)

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

    def _current_form(self) -> CommandForm | None:
        return self._forms.get(self._command_box.currentText())

    def _browse_local_python(self) -> None:
        path = _pick_path("open", self, "Select arcgispro-py3 python.exe",
                         self._local_python_edit.text())
        if path:
            self._local_python_edit.setText(path)
            self._on_local_python_changed()

    def _on_local_python_changed(self) -> None:
        text = self._local_python_edit.text().strip()
        self._local_python = text or None
        settings.set_local_python(self._local_python, self._settings)
        self._sync_run_availability(show_reason=True)

    def _run_blocked_reason(self) -> str | None:
        """Why the current command can't run here, or ``None`` if it can. A
        class-1 redirect-only tool carries an ``unreachable_reason``; a class-2
        LOCAL (arcpy) tool needs a ``local_python``; headless tools always
        run."""
        form = self._current_form()
        if form is None:
            return "No command selected."
        if form.unreachable_reason:
            return form.unreachable_reason
        if needs_arcpy_env(form.path) and not self._local_python:
            return ("LOCAL (arcpy) tool: set the arcgispro-py3 python.exe "
                   "above to run it.")
        return None

    def _sync_run_availability(self, *, show_reason: bool) -> None:
        """Enable Run only when the current command is runnable and no step is
        in flight. ``show_reason`` surfaces the block reason in the status
        label (on a command switch or a local_python edit) -- kept False after
        a just-finished run so its decision text stays visible."""
        running = self._worker is not None and self._worker.isRunning()
        reason = self._run_blocked_reason()
        self._run_button.setEnabled(reason is None and not running)
        if show_reason and not running:
            self._status.setText(reason or "")

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
                browse.setObjectName("field-browse")  # distinct from the
                # single local_python Browse button in the settings row
                browse.clicked.connect(
                    lambda _=False, f=field, le=widget: self._browse(f, le))
                row = QHBoxLayout()
                row.addWidget(widget)
                row.addWidget(browse)
                self._form_layout.addRow(label_text, row)
            else:
                self._form_layout.addRow(label_text, widget)
            self._field_widgets[field.name] = widget
        self._sync_run_availability(show_reason=True)

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
        if self._worker is not None and self._worker.isRunning():
            return  # defense in depth: the Run button is already disabled
        form = self._current_form()
        if form is None:
            return
        blocked = self._run_blocked_reason()
        if blocked:  # defense in depth: Run is already disabled when blocked
            self._status.setText(blocked)
            return
        try:
            step = build_step(form, self._raw_values())
        except FormValidationError as exc:
            self._status.setText(f"Fix before running: {exc}")
            return

        self._status.setText("Running...")
        self._output.clear()
        self._qa_table.setVisible(False)
        self._run_button.setEnabled(False)

        self._job_root = Path(tempfile.mkdtemp(prefix="autogis-gui-"))
        workflow = Workflow(form.label, (step,))
        runner = WorkflowRunner(workflow, self._job_root,
                               local_python=self._local_python)
        self._worker = _StepWorker(runner)
        self._worker.finished_result.connect(self._on_result)
        self._worker.failed.connect(self._on_failure)
        self._worker.start()

    def _join_worker(self) -> None:
        # finished_result/failed are emitted from inside run(), an instant
        # before the underlying OS thread actually terminates -- so by the
        # time this queued-connection handler runs on the main thread, the
        # thread is *usually* done but not provably so yet. wait() blocks
        # until it truly is (near-instant in practice). Skipping this is
        # undefined behavior: a QThread destroyed (e.g. via Python GC
        # dropping the last reference, as happens when a MainWindow is
        # replaced) while its underlying OS thread hasn't fully settled can
        # crash the process (reproduced: back-to-back MainWindow()+run
        # cycles segfaulted 0xC0000005 intermittently without this --
        # connecting Qt's own `finished` signal to .wait() instead of
        # calling it here was NOT enough, since that queued delivery isn't
        # guaranteed to land before a test/caller moves on and drops the
        # last reference).
        self._worker.wait()
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
        if self._worker is not None:
            # isRunning() can flip False a moment before the OS thread has
            # truly settled (Qt marks it not-running slightly ahead of the
            # tail end of thread teardown). Harmless on its own, but if
            # _join_worker's queued handler never got to run first (e.g. the
            # window is closing right in that gap), its job-dir cleanup
            # wouldn't either -- wait() here is an instant no-op if already
            # joined, so this just guarantees the cleanup always happens.
            self._join_worker()
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

    def _on_result(self, result: StepResult) -> None:
        self._join_worker()
        # re-gate on the current command (still runnable? still needs local_python?)
        # without clobbering the decision text set just below.
        self._sync_run_availability(show_reason=False)
        self._status.setText(_DECISION_LABEL[result.decision])
        text = [f"Decision: {_DECISION_LABEL[result.decision]}",
               f"Reason: {result.reason}"]
        if result.stdout:
            text += ["", "-- stdout --", result.stdout]
        if result.stderr:
            text += ["", "-- stderr --", result.stderr]
        self._output.setPlainText("\n".join(text))
        self._show_qa(result.qa_rows)

    def _on_failure(self, message: str) -> None:
        self._join_worker()
        self._sync_run_availability(show_reason=False)
        self._status.setText("Failed to run")
        self._output.setPlainText(message)
        self._show_qa(())


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
