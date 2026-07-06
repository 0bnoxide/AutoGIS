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
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QPlainTextEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .executor import Decision, StepResult, _SEV_ORDER, needs_arcpy_env
from .forms import FormValidationError, build_step
from .introspect import CommandForm, introspect_cli
from .runner import Workflow, WorkflowRunner

__all__ = ["MainWindow", "main"]


def _headless_forms() -> list[CommandForm]:
    """Commands runnable under plain ``sys.executable`` -- no LOCAL (arcpy)
    tool, no ``unreachable_reason``. LOCAL tools need a ``local_python``
    (arcgispro-py3 clone) picker, which is a later slice."""
    return [f for f in introspect_cli()
           if not f.unreachable_reason and not needs_arcpy_env(f.path)]


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

        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)

        self._command_box = QComboBox()
        self._command_box.addItems(sorted(self._forms))
        self._command_box.currentTextChanged.connect(self._rebuild_form)
        outer.addWidget(QLabel("Command:"))
        outer.addWidget(self._command_box)

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

    def _rebuild_form(self, label: str) -> None:
        while self._form_layout.rowCount():
            self._form_layout.removeRow(0)
        self._field_widgets.clear()
        form = self._forms.get(label)
        if form is None:
            return
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
            self._form_layout.addRow(label_text, widget)
            self._field_widgets[field.name] = widget

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
        runner = WorkflowRunner(workflow, self._job_root)
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
        self._run_button.setEnabled(True)
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
        self._run_button.setEnabled(True)
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
