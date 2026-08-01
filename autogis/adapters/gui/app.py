"""PySide6 window for the unified GUI adapter (ADR-0057, ADR-0062, ADR-0063).

Pick a command from ``introspect_cli()``, fill its form, and either run it
(single **Run**) or add it to a multi-step **workflow** the ``WorkflowRunner``
drives end to end -- per-step QA, pause-on-warning, HALT, and Cancel (the
workflow builder, ADR-0063). Workflows can be saved to and reopened from the
Phase-5 recipe format. A single Run is just a 1-step workflow through the same
advance-until-terminal loop. Headless commands run under
``sys.executable``; LOCAL (arcpy) tools run under a user-set ``local_python``
(a cloned arcgispro-py3 ``python.exe``, persisted via ``settings.py`` --
ADR-0062), with the single-Run button gated until one is set, and class-1
redirect-only LOCAL tools (``reachability.UNREACHABLE``) shown greyed. A
workflow may include LOCAL steps too; the runner is handed the same
``local_python``. Exercises the full toolkit-free chain (``introspect`` ->
``forms`` -> ``runner`` -> ``executor``) through a real Qt event loop.

Threading: ``WorkflowRunner.advance()`` blocks for the length of one child
process. ``_StepWorker`` (a ``QThread``) runs it off the UI thread and
reports back via Qt signals (``finished``/``failed``) -- signals are the one
thread-safe way to touch widgets from another thread in Qt, which is why
``runner.py`` (ADR-0055) exposes a lock-guarded ``advance()``/``.status``
surface instead of inventing its own callback mechanism: this class is that
bridge, chosen now that there is an actual window to build it against.
"""
from __future__ import annotations

import html
import shutil
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QLocale, Qt, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QCompleter,
    QDateEdit, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QPushButton,
    QScrollArea, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout, QWidget,
)

from . import settings
from .config_builder_dialog import ConfigBuilderDialog
from .executor import (
    Decision, Step, StepResult, _SEV_ORDER, build_argv, needs_arcpy_env,
)
from .forms import FormValidationError, build_step
from .gw_model_approval_dialog import GWModelApprovalDialog
from .introspect import CommandForm, FormField, introspect_cli
from .reachability import UNREACHABLE
from .runner import RunState, Workflow, WorkflowRunner

__all__ = ["MainWindow", "main"]

_LOCAL_PYTHON_REQUIRED = (
    "LOCAL (arcpy) tool: set the arcgispro-py3 python.exe above to run it.")


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


class _RepeatableRows(QWidget):
    """One :class:`QFormLayout` row for a ``multiple=True`` field (#350): a
    value row plus a ``+`` button; every row after the first gets its own
    ``−`` to remove itself. ``values()``/``set_values()`` are the container's
    list round-trip -- ``forms._normalize``/``executor.build_argv`` already
    handle a list correctly, so this is the only piece #350 needed.

    Rows use editable combos when Click provides suggestions and plain
    ``QLineEdit`` otherwise. ``on_browse``, when given, adds a Browse… button
    to every line-edit row (objectName
    ``repeatable-browse``, distinct from the single-field ``field-browse`` the
    browse-count tests target) -- used for the 5 repeatable path fields.
    """

    def __init__(self, on_browse=None, choices=(), *, editable=True, parent=None):
        super().__init__(parent)
        self._on_browse = on_browse  # Callable[[QLineEdit], None] | None
        self._choices = tuple(choices)
        self._editable = editable
        self._rows: list[tuple[QWidget, QWidget]] = []
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        add_btn = QPushButton("+")
        add_btn.setObjectName("repeatable-add")
        add_btn.clicked.connect(lambda: self._add_row())
        self._layout.addWidget(add_btn)
        self._add_row()  # baseline: one row, no remove button yet

    def _add_row(self, text: str = "") -> None:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        if self._choices:
            value: QWidget = QComboBox()
            value.addItem("")
            value.addItems(self._choices)
            value.setEditable(self._editable)
            if self._editable:
                value.setInsertPolicy(QComboBox.NoInsert)
            value.setCurrentText(text)
        else:
            value = QLineEdit(text)
        row_layout.addWidget(value)
        if self._on_browse is not None:
            browse = QPushButton("Browse…")
            browse.setObjectName("repeatable-browse")
            browse.clicked.connect(lambda _=False, le=value: self._on_browse(le))
            row_layout.addWidget(browse)
        if self._rows:  # every row after the first can remove itself
            minus = QPushButton("−")
            minus.setObjectName("repeatable-remove")
            minus.clicked.connect(lambda _=False, r=row: self._remove_row(r))
            row_layout.addWidget(minus)
        self._layout.insertWidget(self._layout.count() - 1, row)  # before "+"
        self._rows.append((row, value))

    def _remove_row(self, row: QWidget) -> None:
        self._rows = [(r, le) for r, le in self._rows if r is not row]
        self._layout.removeWidget(row)
        # removeWidget only unmanages it from the layout -- it stays a child
        # of this container (and findable via findChildren) until reparented.
        row.setParent(None)
        row.deleteLater()

    def values(self) -> list[str]:
        """Non-empty row values, in row order -- a blank middle row is
        skipped entirely, never emitted as an empty-string argument."""
        def text(widget):
            return (widget.currentText() if isinstance(widget, QComboBox)
                    else widget.text()).strip()

        return [text(widget) for _, widget in self._rows if text(widget)]

    def set_values(self, values: list[str]) -> None:
        """Replace every row with one per item in ``values`` (at least one
        blank row if ``values`` is empty), matching the container's own
        just-built layout."""
        for row, _ in list(self._rows):
            self._remove_row(row)
        for v in (values or [""]):
            self._add_row(v)


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

# Line-level coloring for the raw output/decision pane (#205 comment).
# Distinct from _SEV_COLOR (the QA *table*, INFO=gray): here INFO is blue and
# CONTINUE/PASS green, per the issue. First matching group wins; the order is
# the precedence -- a red signal beats a warning, and INFO stays blue even on
# an "...QA pass." line where "pass" would otherwise read as green.
_LINE_COLORS = (
    ("#d32f2f", ("CRITICAL", "ERROR", "FAIL", "HALT")),   # red
    ("#ed6c02", ("WARNING", "PAUSE")),                     # orange
    ("#1976d2", ("INFO",)),                                # blue
    ("#2e7d32", ("CONTINUE", "PASS")),                     # green
)


def _colorize_output(text: str) -> str:
    """Render raw output/decision text as HTML, coloring each line by the first
    severity/decision keyword it contains (#205). Every line is escaped so
    arbitrary child-process stdout can't inject markup; the whole is wrapped in
    ``<pre>`` to keep console monospacing and the ``[SEVERITY] category``
    alignment."""
    lines = []
    for line in text.split("\n"):
        upper = line.upper()
        color = next((c for c, words in _LINE_COLORS
                      if any(w in upper for w in words)), None)
        esc = html.escape(line)
        lines.append(f'<span style="color:{color}">{esc}</span>' if color else esc)
    return "<pre>" + "\n".join(lines) + "</pre>"


class MainWindow(QMainWindow):
    def __init__(self, settings_store=None):
        super().__init__()
        self.setWindowTitle("AutoGIS -- GUI adapter (walking skeleton)")
        self._settings = settings_store  # None -> real per-user QSettings
        self._local_python = settings.get_local_python(settings_store)
        # Only offer commands that can actually run here: class-1 redirect-only
        # LOCAL tools (stamped unreachable_reason) always HALT with "use the
        # .pyt toolbox", so they are hidden from the picker rather than shown
        # disabled. Headless + class-2 (arcpy-executable, runnable once a
        # local_python is set) tools stay listed.
        self._forms = {
            f.label: f for f in _window_forms()
            if not f.unreachable_reason
            and f.label != "envmon approve-gw-model"
        }
        self._field_widgets: dict[str, QWidget] = {}
        self._field_browse_buttons: dict[str, QPushButton] = {}
        self._worker: _StepWorker | None = None
        self._job_root: Path | None = None
        self._runner: WorkflowRunner | None = None
        self._steps: list[Step] = []
        self._workflow_name = "gui-workflow"
        self._run_is_workflow = False  # True during Run workflow; marks list rows

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
        # Site Config Builder (ADR-0065): author a harvest config.yaml via a
        # guided form instead of hand-writing YAML / inspecting item.layers.
        self._config_dialog: ConfigBuilderDialog | None = None
        build_config_btn = QPushButton("Build Site Config…")
        build_config_btn.clicked.connect(self._on_build_config)
        lp_row.addWidget(build_config_btn)
        self._approval_dialog: GWModelApprovalDialog | None = None
        approve_model_btn = QPushButton("Approve GW Model…")
        approve_model_btn.setObjectName("approve-gw-model")
        approve_model_btn.clicked.connect(self._on_approve_gw_model)
        lp_row.addWidget(approve_model_btn)
        outer.addLayout(lp_row)

        self._command_box = QComboBox()
        self._command_box.addItems(sorted(self._forms))
        # Editable + a substring-matching completer so typing "sync" finds
        # "agol sync-to-gdb" without knowing which group it's under or
        # scrolling ~130 entries -- NoInsert keeps a typed non-match from
        # becoming a bogus new item.
        self._command_box.setEditable(True)
        self._command_box.setInsertPolicy(QComboBox.NoInsert)
        completer = QCompleter(sorted(self._forms), self._command_box)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        self._command_box.setCompleter(completer)
        self._command_box.currentTextChanged.connect(self._rebuild_form)
        outer.addWidget(QLabel("Command:"))
        outer.addWidget(self._command_box)

        self._help_label = QLabel()
        self._help_label.setWordWrap(True)
        outer.addWidget(self._help_label)

        self._form_layout = QFormLayout()
        form_container = QWidget()
        form_container.setLayout(self._form_layout)
        # Without a scroll area the layout minimum pins the window at ~874x871
        # for a 15-field command, pushing Run and the output pane off a 768p
        # screen with no way to shrink (#357).
        form_scroll = QScrollArea()
        form_scroll.setWidgetResizable(True)
        form_scroll.setWidget(form_container)
        outer.addWidget(form_scroll)

        row = QHBoxLayout()
        self._run_button = QPushButton("Run")
        self._run_button.clicked.connect(self._on_run)
        row.addWidget(self._run_button)
        outer.addLayout(row)

        # --- workflow builder (v1, ADR-0063) -----------------------------
        # The same command + form above configures each step; Add appends it
        # to an in-memory workflow the WorkflowRunner drives as one sequence.
        add_row = QHBoxLayout()
        self._add_button = QPushButton("+ Add to workflow")
        self._add_button.clicked.connect(self._on_add_step)
        self._pause_on_warning = QCheckBox("pause on warning")
        add_row.addWidget(self._add_button)
        add_row.addWidget(self._pause_on_warning)
        outer.addLayout(add_row)

        steps_container = QWidget()
        steps_layout = QVBoxLayout(steps_container)
        steps_layout.setContentsMargins(0, 0, 0, 0)
        steps_layout.addWidget(QLabel("Steps:"))
        self._step_list = QListWidget()
        steps_layout.addWidget(self._step_list)

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
        self._load_button = QPushButton("Load recipe…")
        self._load_button.clicked.connect(self._on_load_recipe)
        self._save_button = QPushButton("Save recipe…")
        self._save_button.clicked.connect(self._on_save_recipe)
        self._cancel_button = QPushButton("Cancel")
        self._cancel_button.clicked.connect(self._on_cancel)
        self._resume_button = QPushButton("Resume")
        self._resume_button.clicked.connect(self._on_resume)
        for _b in (self._remove_button, self._up_button, self._down_button,
                   self._run_wf_button, self._clear_button,
                   self._cancel_button, self._resume_button):
            wf_row.addWidget(_b)
        steps_layout.addLayout(wf_row)
        recipe_row = QHBoxLayout()
        recipe_row.addWidget(self._load_button)
        recipe_row.addWidget(self._save_button)
        recipe_row.addStretch()
        steps_layout.addLayout(recipe_row)
        # -----------------------------------------------------------------

        results_container = QWidget()
        results_layout = QVBoxLayout(results_container)
        results_layout.setContentsMargins(0, 0, 0, 0)

        self._status = QLabel("")
        results_layout.addWidget(self._status)

        # Structured QA view: the executor already parses the injected
        # qa.csv into StepResult.qa_rows -- render it here as a sorted
        # (worst-severity-first), per-column, color-coded table (stdout only
        # shows it as flat text). Hidden until a run produces QA rows.
        self._qa_table = QTableWidget()
        self._qa_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._qa_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._qa_table.setVisible(False)
        results_layout.addWidget(self._qa_table)

        # QTextEdit (not QPlainTextEdit) so decision/QA lines can be colored via
        # setHtml/_colorize_output (#205 comment); read-only, still monospaced
        # by the <pre> wrapper the colorizer emits.
        self._output = QTextEdit()
        self._output.setReadOnly(True)
        results_layout.addWidget(self._output)

        # Steps (often empty for a single Run) and the output/QA area below
        # compete for the same fixed vertical space -- a splitter lets the
        # user reclaim it instead of a static, often-wasted allocation (#173).
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(steps_container)
        splitter.addWidget(results_container)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([120, 400])
        outer.addWidget(splitter)

        if self._command_box.count():
            self._rebuild_form(self._command_box.currentText())
        self._refresh_step_controls()   # no steps yet -> step buttons disabled

    def _current_form(self) -> CommandForm | None:
        return self._forms.get(self._command_box.currentText())

    def _on_build_config(self) -> None:
        """Open the Site Config Builder (window-modal, non-blocking --
        ``open()`` keeps the event loop free, unlike ``exec()``)."""
        self._config_dialog = ConfigBuilderDialog(self)
        self._config_dialog.open()

    def _on_approve_gw_model(self) -> None:
        """Open the dedicated review UI; the generic CLI form cannot list
        DRAFT runs or show ranked cross-validation statistics."""
        if not self._local_python:
            self._status.setText(
                "Set the arcgispro-py3 python.exe before approving a "
                "groundwater model.")
            return
        self._approval_dialog = GWModelApprovalDialog(
            self._local_python, self)
        self._approval_dialog.open()

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
        self._refresh_step_controls()

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
            return _LOCAL_PYTHON_REQUIRED
        return None

    def _sync_run_availability(self, *, show_reason: bool) -> None:
        """Enable Run only when the current command is runnable and no step is
        in flight. ``show_reason`` surfaces the block reason in the status
        label (on a command switch or a local_python edit) -- kept False after
        a just-finished run so its decision text stays visible."""
        # "running" must count a live runner, not just a live worker: a PAUSED
        # workflow (introduced by ADR-0063) has _worker None while _runner is
        # still active, and the local_python row stays editable during a run --
        # so editing it while paused must NOT re-enable Run or wipe the pause
        # prompt. _finish_run nulls _runner before its own sync call, so this
        # stays correct at run end.
        running = self._runner is not None or (
            self._worker is not None and self._worker.isRunning())
        reason = self._run_blocked_reason()
        self._run_button.setEnabled(reason is None and not running)
        if show_reason and not running:
            self._status.setText(reason or "")

    def _rebuild_form(self, label: str) -> None:
        while self._form_layout.rowCount():
            self._form_layout.removeRow(0)
        self._field_widgets.clear()
        self._field_browse_buttons.clear()
        form = self._forms.get(label)
        if form is None:
            self._help_label.clear()
            self._sync_run_availability(show_reason=True)
            return
        self._help_label.setText(form.help_text or "")
        for field in form.fields:
            # Must precede every kind-specific branch below (#350): a
            # repeatable path/choice field would otherwise be captured by
            # the path/choice branch and rendered as a single-value widget.
            if field.repeatable:
                on_browse = ((lambda le, f=field: self._browse(f, le))
                            if field.kind == "path" else None)
                choices = field.choices if field.kind == "choice" else ()
                widget = _RepeatableRows(
                    on_browse=on_browse,
                    choices=choices,
                    editable=not field.strict,
                )
                if field.help_text:
                    widget.setToolTip(field.help_text)
                label_text = field.label + (
                    " *" if (field.required or field.xor_group) else "")
                self._form_layout.addRow(label_text, widget)
                self._field_widgets[field.name] = widget
                continue
            if field.nargs > 1:
                # Must precede the int/float branch (#351): --bbox etc. are
                # kind=="float" but a QDoubleSpinBox can only hold ONE
                # number, so an nargs>1 field stays a plain QLineEdit --
                # the user types the N values space-separated (forms.py
                # splits and count-checks them).
                widget: QWidget = QLineEdit()
                widget.setPlaceholderText(
                    f"{field.nargs} space-separated values")
            elif field.kind == "flag":
                widget = QCheckBox()
                if field.default is None:
                    # A nullable flag (Click `--x/--no-x` with default=None)
                    # carries three meanings, not two: on, off, and "leave
                    # whatever the config file says alone". bool(None)
                    # collapsed the third into "off", so an untouched form
                    # emitted --no-incremental and silently overrode the
                    # config (#352). setTristate must come first -- Qt
                    # ignores a partial state on a two-state box.
                    widget.setTristate(True)
                    widget.setCheckState(Qt.CheckState.PartiallyChecked)
                else:
                    widget.setChecked(bool(field.default))
                if field.help_text:
                    # flags have no placeholder to carry their help the way
                    # QLineEdit does below; without this the partial state is
                    # a half-filled box with no explanation
                    widget.setToolTip(field.help_text)
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
                if not field.strict:
                    # SuggestedChoice: pick from the list or type a value the
                    # CLI hasn't seen yet -- NoInsert keeps typed text from
                    # permanently growing the dropdown's own item list.
                    widget.setEditable(True)
                    widget.setInsertPolicy(QComboBox.NoInsert)
            elif field.kind == "multichoice":
                # CommaList: a checkable list, one widget in one form row.
                # Height is fixed (not scaled to item count) so the 11-item
                # MESSINESS vocabulary can't dominate the form -- shorter
                # lists (e.g. 4-tier) just leave blank space below their
                # items; QListWidget scrolls internally past the cap.
                widget = QListWidget()
                widget.setMaximumHeight(120)
                for choice in field.choices or ():
                    item = QListWidgetItem(choice)
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                    item.setCheckState(Qt.Unchecked)
                    widget.addItem(item)
            elif (field.kind in ("int", "float")
                  and (field.minimum is None or field.maximum is None)):
                # A Qt spin box requires a finite range. Inventing one (the
                # original implementation used +/-1,000,000) silently clamps
                # valid open-ended values such as state-plane coordinates.
                # Keep these fields textual; Click remains the validator.
                widget = QLineEdit()
                if field.default is not None:
                    widget.setText(str(field.default))
                if field.help_text:
                    widget.setPlaceholderText(field.help_text)
            elif field.kind in ("int", "float"):
                widget = QSpinBox() if field.kind == "int" else QDoubleSpinBox()
                # A comma-decimal locale renders e.g. "0,800", which Click's
                # FLOAT parser in the child process rejects with a usage
                # error the user has no way to connect back to this field.
                widget.setLocale(QLocale.c())
                if isinstance(widget, QDoubleSpinBox):
                    # Qt's default (2) truncates a real tolerance like 0.001;
                    # 6 covers that and finer geospatial/ratio values without
                    # per-field tuning.
                    widget.setDecimals(6)
                low, high = field.minimum, field.maximum
                if field.default is None:
                    # A spin box always holds a number, but blank->omitted is
                    # the contract (forms._normalize). Qt's own answer: put a
                    # sentinel one step below the floor and label it -- this
                    # applies even to a required field with no default (e.g.
                    # a coordinate argument): the sentinel round-trips to ""
                    # -> None, and build_step's own required check catches it
                    # with a clear "is required" message before any process
                    # launches, so the softer label costs nothing real.
                    widget.setRange(low - 1, high)
                    widget.setSpecialValueText("(use default)")
                    widget.setValue(low - 1)
                else:
                    widget.setRange(low, high)
                    widget.setValue(field.default)
            elif field.kind == "date" and field.allow_time:
                # datetime.fromisoformat accepts more than a date-only picker
                # can represent (time, seconds, offsets). Keep that full CLI
                # contract reachable rather than silently truncating to a day.
                widget = QLineEdit()
                if field.help_text:
                    widget.setPlaceholderText(field.help_text)
            elif field.kind == "date":
                widget = QDateEdit()
                widget.setCalendarPopup(True)
                widget.setDisplayFormat("yyyy-MM-dd")
                widget.setLocale(QLocale.c())
                # All current IsoDate options (verified via introspect_cli())
                # have default=None -- unlike int/float, there's no "has a
                # real default" case to branch on, so building one here would
                # be untestable dead code. Park the value at minimumDate() and
                # label it: round-trips to "" -> omitted by forms._normalize.
                widget.setSpecialValueText("(none)")
                widget.setDate(widget.minimumDate())
            else:
                widget = QLineEdit()
                if field.default is not None:
                    widget.setText(str(field.default))
                if field.help_text:
                    widget.setPlaceholderText(field.help_text)
            # Help reaches the screen for EVERY kind, not just line edits: the
            # flag/choice branches never set it, and setPlaceholderText above is
            # a no-op whenever a default was already written into the field (#356).
            if field.help_text:
                widget.setToolTip(field.help_text)
            # xor_group fields aren't individually `required` (Click sees them
            # as optional; the CLI body enforces "choose exactly one"), but
            # from the user's perspective they're just as required -- reuse
            # the same marker rather than leaving them looking optional.
            label_text = field.label + (
                " *" if (field.required or field.xor_group) else "")
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
                self._field_browse_buttons[field.name] = browse
            else:
                self._form_layout.addRow(label_text, widget)
            self._field_widgets[field.name] = widget
        self._wire_xor_groups(form)
        self._sync_run_availability(show_reason=True)

    def _wire_xor_groups(self, form: CommandForm) -> None:
        """Grey out an xor sibling once its pair is filled (reuses the shape
        of ``config_builder_dialog._sync_xor``): fill one side and the other
        control disables but keeps its typed text; clear it and both re-enable
        (owner decision, spec Sec 4.1a). Driven off each widget's own
        ``textChanged`` -- never ``labelForField()``, which returns None for
        a path row (wrapped in its own Browse-button ``QHBoxLayout``, not
        added to the form layout directly)."""
        # ponytail: envmon reconcile-locations' --gdb unconditionally HALTs
        # ("use the .pyt toolbox" -- cli.py's reconcile_locations_cmd), so
        # greying its --wells-csv sibling would steer the user into that
        # dead end. Leave this one pair as it is today.
        if form.label == "envmon reconcile-locations":
            return
        groups: dict[str, list[FormField]] = {}
        for field in form.fields:
            if field.xor_group:
                groups.setdefault(field.xor_group, []).append(field)
        for members in groups.values():
            widgets = [self._field_widgets[f.name] for f in members]
            browse_buttons = [
                self._field_browse_buttons.get(f.name) for f in members
            ]
            # Every live xor pair today (besides the reconcile-locations
            # exception above) is two plain path QLineEdits -- verified via
            # introspect_cli() before writing this. A repeatable/choice/flag
            # xor member would need its own signal wired here; skip rather
            # than guess at one with no real case to test against yet.
            if not all(isinstance(w, QLineEdit) for w in widgets):
                continue

            def _sync(_text: str = "", widgets=widgets,
                      browse_buttons=browse_buttons) -> None:
                filled = [bool(w.text().strip()) for w in widgets]
                for i, (w, browse) in enumerate(zip(widgets, browse_buttons)):
                    other_filled = any(f for j, f in enumerate(filled) if j != i)
                    enabled = not other_filled
                    w.setEnabled(enabled)
                    if browse is not None:
                        browse.setEnabled(enabled)

            for w in widgets:
                w.textChanged.connect(_sync)

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
                state = widget.checkState()
                values[name] = (
                    None
                    if state == Qt.CheckState.PartiallyChecked
                    else state == Qt.CheckState.Checked
                )
            elif isinstance(widget, QComboBox):
                values[name] = widget.currentText()
            elif isinstance(widget, QListWidget):
                # CommaList round-trip: checked items, list order, joined --
                # matches exactly what the CLI's CommaList type parses back.
                checked = [widget.item(i).text() for i in range(widget.count())
                          if widget.item(i).checkState() == Qt.Checked]
                values[name] = ",".join(checked)
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                # The sentinel means "unset" -> "" -> omitted by _normalize.
                values[name] = ("" if widget.text() == widget.specialValueText()
                                else widget.value())
            elif isinstance(widget, QDateEdit):
                values[name] = ("" if widget.text() == widget.specialValueText()
                                else widget.date().toString("yyyy-MM-dd"))
            elif isinstance(widget, QLineEdit):
                values[name] = widget.text()
            elif isinstance(widget, _RepeatableRows):
                values[name] = widget.values()
            else:
                # QSpinBox/QDoubleSpinBox/QDateEdit all inherit .text(), so an
                # unhandled widget class falling through here would silently
                # ship a sentinel label or a comma-decimal render to the child
                # process. Fail loudly instead.
                raise TypeError(
                    f"_raw_values has no rule for {type(widget).__name__} "
                    f"(field {name!r})")
        return values

    def _on_run(self) -> None:
        if self._runner is not None:
            return  # a run is already active
        form = self._current_form()
        if form is None:
            return
        blocked = self._run_blocked_reason()
        if blocked:  # defense in depth: Run is already disabled when blocked
            self._status.setText(blocked)
            return
        try:
            step = build_step(
                form, self._raw_values(),
                pause_on_warning=self._pause_on_warning.isChecked())
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
        # Cancel/Resume apply to any run, single Run included (#205): reset them
        # here so the pause branch can light Resume for a single Run too.
        self._cancel_button.setEnabled(True)
        self._resume_button.setEnabled(False)
        self._job_root = Path(tempfile.mkdtemp(prefix="autogis-gui-"))
        self._runner = WorkflowRunner(Workflow(name, steps), self._job_root,
                                      local_python=self._local_python)
        self._repaint_run_widgets()
        self._advance()

    def _repaint_run_widgets(self) -> None:
        """Paint run state before a fast worker queues the next transition."""
        self._status.repaint()
        self._output.repaint()
        self._step_list.viewport().repaint()

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
                      self._load_button, self._save_button,
                      self._remove_button, self._up_button,
                      self._down_button):
                b.setEnabled(False)

    def _refresh_step_controls(self) -> None:
        """Enable the step-list buttons only when idle and steps exist."""
        active = bool(self._steps) and self._runner is None
        self._run_wf_button.setEnabled(
            active and self._workflow_blocked_reason() is None)
        self._clear_button.setEnabled(active)
        self._save_button.setEnabled(active)
        self._load_button.setEnabled(self._runner is None)
        for b in (self._remove_button, self._up_button, self._down_button):
            b.setEnabled(active)

    def _workflow_blocked_reason(self) -> str | None:
        for step in self._steps:
            if step.command:
                reason = UNREACHABLE.get(" ".join(step.command))
                if reason:
                    return reason
        if not self._local_python and any(
                step.command and needs_arcpy_env(step.command)
                for step in self._steps):
            return _LOCAL_PYTHON_REQUIRED
        return None

    def _on_load_recipe(self) -> None:
        """Replace the current step list with a validated workflow recipe."""
        if self._runner is not None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Load workflow recipe", "",
            "Workflow recipe (*.yaml *.yml *.json)")
        if not path:
            return
        from autogis.adapters.recipe_workflow import recipe_to_workflow
        from autogis.core.common.workflow_recipe import load_recipe
        try:
            workflow = recipe_to_workflow(load_recipe(Path(path)))
            forms_by_path = {form.path: form for form in _window_forms()}
            steps: list[Step] = []
            for step in workflow.steps:
                if step.command:
                    build_argv(step.command, step.values,
                               fail_on=step.fail_on)
                    if " ".join(step.command) not in UNREACHABLE:
                        # Keep the normalized values, don't just validate and
                        # drop them (#398): forms._normalize is where an
                        # nargs>1 value written as one YAML string ("W S E N")
                        # is split into its tuple, so discarding the result
                        # left a loaded step diverging from the identical step
                        # built through the GUI form.
                        normalized = build_step(
                            forms_by_path[step.command], step.values,
                            fail_on=step.fail_on,
                            pause_on_warning=step.pause_on_warning)
                        step = replace(step, values=normalized.values)
                steps.append(step)
        except Exception as exc:  # noqa: BLE001 - surface parse/map error in-UI
            self._status.setText(f"Load failed: {exc}")
            return
        self._workflow_name = workflow.name
        self._steps[:] = steps
        self._step_list.clear()
        for step in self._steps:
            self._step_list.addItem(self._step_row_text(step))
        self._refresh_step_controls()
        loaded = f"Loaded recipe: {workflow.name} ({len(workflow.steps)} steps)"
        reason = self._workflow_blocked_reason()
        self._status.setText(f"{loaded} — {reason}" if reason else loaded)

    def _on_save_recipe(self) -> None:
        """Serialize the built or loaded workflow to a reusable recipe YAML."""
        if self._runner is not None or not self._steps:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save workflow recipe", "", "YAML recipe (*.yaml *.yml)")
        if not path:
            return
        from autogis.adapters.recipe_workflow import workflow_to_recipe
        from autogis.core.common.workflow_recipe import save_recipe
        try:
            recipe = workflow_to_recipe(
                Workflow(self._workflow_name, tuple(self._steps)))
            save_recipe(recipe, Path(path))
        except Exception as exc:  # noqa: BLE001 - surface any save error in-UI
            self._status.setText(f"Save failed: {exc}")
            return
        self._status.setText(f"Saved recipe: {path}")

    def _step_summary(self, form_label: str, values: dict, pause: bool) -> str:
        """One-line row label: command + first non-empty text arg + pause tag."""
        hint = next((str(v) for v in values.values()
                     if isinstance(v, str) and v.strip()), "")
        hint = f" ({hint})" if hint else ""
        return f"{form_label}{hint}{'  [pause-on-warn]' if pause else ''}"

    def _step_row_text(self, step: Step) -> str:
        """Render command and review-checkpoint recipe steps in the list."""
        if step.command is None:
            return (
                f"Review checkpoint ({step.message})"
                if step.message else "Review checkpoint"
            )
        return self._step_summary(
            " ".join(step.command), step.values, step.pause_on_warning)

    def _on_add_step(self) -> None:
        if self._runner is not None:
            return
        form = self._current_form()
        if form is None:
            return
        values = self._raw_values()
        try:
            step = build_step(
                form, values,
                pause_on_warning=self._pause_on_warning.isChecked())
        except FormValidationError as exc:
            self._status.setText(f"Fix before adding: {exc}")
            return
        if not self._steps:
            self._workflow_name = "gui-workflow"
        self._steps.append(step)
        self._step_list.addItem(self._step_row_text(step))
        self._refresh_step_controls()

    def _on_remove_step(self) -> None:
        i = self._step_list.currentRow()
        if self._runner is not None or i < 0:
            return
        del self._steps[i]
        self._step_list.takeItem(i)
        if not self._steps:
            self._workflow_name = "gui-workflow"
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
        self._workflow_name = "gui-workflow"
        self._step_list.clear()
        self._refresh_step_controls()

    def _on_run_workflow(self) -> None:
        if self._runner is not None or not self._steps:
            return
        reason = self._workflow_blocked_reason()
        if reason:
            self._status.setText(reason)
            return
        self._run_is_workflow = True
        for i in range(self._step_list.count()):   # clear any prior-run glyphs
            item = self._step_list.item(i)
            item.setText(item.text().lstrip("✓⏸✗ "))
        self._start_run(
            tuple(self._steps), self._workflow_name)  # sets Cancel/Resume

    def _on_cancel(self) -> None:
        if self._runner is None:
            return
        self._runner.cancel()
        self._cancel_button.setEnabled(False)
        self._resume_button.setEnabled(False)
        if self._worker is None:
            # No worker in flight (idle/paused) -> no _on_result/_on_failure is
            # coming to finish the run, so finish it here. Deciding from
            # self._worker (a UI-thread-owned field), NOT runner.status: the
            # worker thread mutates the runner state, so a step that just
            # emitted its result is already non-RUNNING while its _on_result is
            # still queued -- reading status here would finish the run and null
            # self._runner out from under that pending _on_result.
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
        # _set_authoring_enabled re-enables Run unconditionally; re-gate it for
        # the current command (a LOCAL tool with no local_python, or an
        # unreachable one, must stay blocked). show_reason=False so it doesn't
        # clobber the terminal status just set by the caller.
        self._sync_run_availability(show_reason=False)
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
        if result.report_out:      # #205: the qa.csv was copied to the user's path
            text.append(f"Report saved to: {result.report_out}")
        if result.report_error:    # copy-out failed; decision unaffected, just shown
            text.append(f"Report NOT saved: {result.report_error}")
        if result.stdout:
            text += ["", "-- stdout --", result.stdout]
        if result.stderr:
            text += ["", "-- stderr --", result.stderr]
        self._output.setHtml(_colorize_output("\n".join(text)))
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
        if self._runner is None:
            return  # a cancel/close finished the run while this delivery queued
        index = len(self._runner.results) - 1  # the step that just ran
        self._render_result(result, index)     # sets status to the decision label
        self._repaint_run_widgets()
        state = self._runner.status
        if state is RunState.PENDING:
            self._advance()                     # loop to the next step
        elif state is RunState.PAUSED:
            # A single Run pauses too now (#205): _start_run reset Resume, so
            # both paths get the same Resume/Cancel affordance here.
            self._status.setText(
                f"PAUSED after step {index + 1} -- Resume or Cancel")
            self._resume_button.setEnabled(True)
        else:                                   # DONE / HALTED / CANCELLED
            if self._run_is_workflow:
                self._status.setText(
                    self._terminal_message(state, index, result))
            elif state is RunState.CANCELLED:
                # A cancelled single Run must read "Cancelled", not the decision
                # label of the step that completed under a deferred cancel
                # (#205 C made mid-flight cancel reachable for single Run).
                self._status.setText("Cancelled")
            # Otherwise a single Run keeps the decision label _render_result set
            # (today's UX: "CONTINUE"/"HALT").
            self._finish_run()

    def _on_failure(self, message: str) -> None:
        self._join_worker()
        if self._runner is None:
            return  # a cancel/close finished the run while this delivery queued
        if self._runner.status is RunState.CANCELLED:
            # advance() raised only because a cancel landed in the worker's
            # startup gap -- report the cancel it was, not a failure.
            self._status.setText("Cancelled")
        else:
            self._output.setHtml(_colorize_output(message))
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
