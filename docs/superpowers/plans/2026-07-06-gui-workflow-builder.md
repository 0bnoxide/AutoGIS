# GUI Workflow Builder (v1) Implementation Plan

> **For agentic workers:** Calibrated for **inline self-execution** by an agent
> with full repo context, followed by the chapter's standing Fable pre-merge
> gate — not a zero-context subagent hand-off. Steps use checkbox (`- [ ]`)
> tracking. Crux logic (the drive-loop dispatcher) and all tests are given as
> real code; unambiguous widget boilerplate is specified precisely in prose.

**Goal:** Let the single-tool GUI window assemble several headless commands
into an ordered workflow and run them end to end over the existing
`WorkflowRunner`, with per-step results, pause-on-warning, HALT, and Cancel.

**Architecture:** All in `autogis/adapters/gui/app.py` (`MainWindow`). Reuses
`Workflow`/`WorkflowRunner`/`Step`/`build_step`/`_show_qa`. One refactor:
generalize the single-shot drive into an "advance until terminal/paused" loop
shared by both single **Run** (a 1-step workflow) and **Run workflow**.

**Tech Stack:** Python 3.14, PySide6 (`gui` optional extra), pytest with Qt's
`offscreen` platform plugin.

## Global Constraints

- `core/` and `adapters/` import with neither `arcpy` nor `arcgis` present.
  (`app.py` imports only PySide6 + sibling gui modules — unchanged.)
- Ponytail: laziest correct solution; reuse before writing; shortest diff
  after understanding. Mark deliberate ceilings with a `ponytail:` comment.
- Headless commands only (`_headless_forms()` filter unchanged). LOCAL support
  is the next slice.
- Tests: offscreen Qt, real widgets, `run_step` monkeypatched to return
  per-call results (the suite's convention; `test_gui_executor.py` owns real
  subprocess correctness). Never mock Qt itself.
- Every existing `tests/test_gui_app.py` test must stay green unchanged (the
  refactor is behavior-preserving for single Run).

---

### Task 1: Refactor the drive into an advance-until-terminal loop

Behavior-preserving foundation. No new user-visible behavior; single Run keeps
working exactly as today, now via the generalized loop.

**Files:**
- Modify: `autogis/adapters/gui/app.py` (`_on_run`, `_join_worker`, `_on_result`,
  `_on_failure`, `closeEvent`; add `RunState` import, `_start_run`, `_advance`,
  `_finish_run`, `_render_result`, `self._runner` state)
- Test: `tests/test_gui_app.py`

**Interfaces:**
- Consumes: `WorkflowRunner(workflow, job_root)`, `.advance()`, `.status`,
  `.results`, `RunState`, `Decision`, `StepResult`, `Workflow`, `Step`,
  `build_step`, `_show_qa`.
- Produces (later tasks rely on these exact names):
  - `self._runner: WorkflowRunner | None` — active run, `None` when idle.
  - `_start_run(steps: tuple[Step, ...], name: str, from_list: bool) -> None`
  - `_advance() -> None` — spawn a `_StepWorker` for the next step.
  - `_finish_run() -> None` — rmtree job dir, clear `_runner`, re-enable
    authoring, disable Cancel/Resume.
  - `_render_result(result: StepResult, index: int) -> None` — status +
    output + QA table + (if `self._run_is_workflow`) mark list row `index`.

- [ ] **Step 1: Add `RunState` to the runner import**

```python
from .runner import RunState, Workflow, WorkflowRunner
```

- [ ] **Step 2: Add run state to `__init__`** (near `self._worker`):

```python
self._runner: WorkflowRunner | None = None
self._run_is_workflow = False   # set by _on_run_workflow (Task 3); marks list rows
```

- [ ] **Step 3: Replace the single-shot body of `_on_run` to route through the loop**

```python
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
```

- [ ] **Step 4: Add `_start_run` / `_advance`**

```python
def _start_run(self, steps: "tuple[Step, ...]", name: str) -> None:
    self._status.setText("Running...")
    self._output.clear()
    self._qa_table.setVisible(False)
    self._set_authoring_enabled(False)   # defined in Task 2; add a stub now
    self._job_root = Path(tempfile.mkdtemp(prefix="autogis-gui-"))
    self._runner = WorkflowRunner(Workflow(name, steps), self._job_root)
    self._advance()

def _advance(self) -> None:
    self._worker = _StepWorker(self._runner)
    self._worker.finished_result.connect(self._on_result)
    self._worker.failed.connect(self._on_failure)
    self._worker.start()
```

Add a temporary `_set_authoring_enabled` stub (Task 2 fills it):
```python
def _set_authoring_enabled(self, enabled: bool) -> None:
    self._run_button.setEnabled(enabled)
```

- [ ] **Step 5: Split `_join_worker` (thread-join only) and add `_finish_run`**

```python
def _join_worker(self) -> None:
    # thread-join ONLY -- see ADR-0057 for why .wait() is mandatory here.
    # Job-dir cleanup moved to _finish_run: the dir is shared across a
    # multi-step workflow's steps, so it must survive until the run ends.
    if self._worker is not None:
        self._worker.wait()
        self._worker = None

def _finish_run(self) -> None:
    self._runner = None
    self._set_authoring_enabled(True)
    if self._job_root is not None:
        shutil.rmtree(self._job_root, ignore_errors=True)
        self._job_root = None
```
(Keep the full `.wait()` explanatory comment from the current `_join_worker`.)

- [ ] **Step 6: Turn `_on_result` into the dispatcher; add `_render_result`; update `_on_failure`**

```python
def _render_result(self, result: StepResult, index: int) -> None:
    self._status.setText(_DECISION_LABEL[result.decision])
    text = [f"Decision: {_DECISION_LABEL[result.decision]}",
           f"Reason: {result.reason}"]
    if result.stdout:
        text += ["", "-- stdout --", result.stdout]
    if result.stderr:
        text += ["", "-- stderr --", result.stderr]
    self._output.setPlainText("\n".join(text))
    self._show_qa(result.qa_rows)

def _on_result(self, result: StepResult) -> None:
    self._join_worker()
    index = len(self._runner.results) - 1   # the step that just ran
    self._render_result(result, index)      # sets status to the decision label
    state = self._runner.status
    if state is RunState.PENDING:
        self._advance()                     # loop to the next step
    elif state is RunState.PAUSED:
        if self._run_is_workflow:
            self._status.setText(
                f"PAUSED after step {index + 1} -- Resume or Cancel")
            # Task 3 enables the Resume button here
    else:                                    # DONE / HALTED / CANCELLED
        if self._run_is_workflow:
            self._status.setText(self._terminal_message(state, index, result))
        # A single Run keeps the decision label _render_result set (today's
        # UX: "CONTINUE"/"HALT"); only a workflow shows a run-level message.
        self._finish_run()

def _on_failure(self, message: str) -> None:
    self._join_worker()
    self._output.setPlainText(message)
    self._show_qa(())
    self._status.setText("Failed to run")
    self._finish_run()

def _terminal_message(self, state: RunState, index: int,
                      result: StepResult) -> str:
    if state is RunState.HALTED:
        return f"HALTED at step {index + 1}: {result.reason}"
    if state is RunState.CANCELLED:
        return "Cancelled"
    return "Workflow complete"   # DONE
```

- [ ] **Step 7: Update `closeEvent`** — after the unchanged "refuse while a
  step is in flight" branch, call `_join_worker()` then `_finish_run()`
  **unconditionally** (both are no-ops when there is nothing to do). Do NOT
  gate on `self._worker is not None`: a PAUSED run has `_worker is None` but a
  live `self._runner`/`self._job_root`, and its job dir must still be cleaned
  up on close.

```python
def closeEvent(self, event) -> None:
    if self._worker is not None and self._worker.isRunning():
        self._status.setText(
            "A step is still running -- please wait for it to finish "
            "before closing.")
        event.ignore()
        return
    self._join_worker()   # no-op when _worker is None
    self._finish_run()    # cleans the job dir / clears runner; guards on None
    event.accept()
```

- [ ] **Step 8: Run the existing suite — must be green unchanged**

Run: `python -m pytest tests/test_gui_app.py -q`
Expected: all existing tests PASS (the walking-skeleton + QA + Browse tests).

- [ ] **Step 9: Add a regression test that a 1-step run cleans up**

```python
def test_single_run_finishes_and_clears_runner(qapp, monkeypatch):
    monkeypatch.setattr(runner_mod, "run_step",
        lambda step, job_dir, **kw: StepResult(Decision.CONTINUE, "ok", exit_code=0))
    win = MainWindow()
    form = next(iter(win._forms.values()))
    _fill_required_fields(win, form)
    win._on_run()
    _pump_until(lambda: win._run_button.isEnabled())
    assert "CONTINUE" in win._status.text()
    assert win._runner is None          # run finished, state cleared
    assert win._job_root is None        # job dir cleaned up
```

- [ ] **Step 10: Commit**

```bash
git add autogis/adapters/gui/app.py tests/test_gui_app.py
git commit -m "refactor(gui): generalize single-shot run into advance-until-terminal loop"
```

---

### Task 2: Authoring UI — Add to workflow, Steps list, Remove/↑/↓, Clear

**Files:**
- Modify: `autogis/adapters/gui/app.py` (`__init__` widgets; new
  `_step_summary`, `_on_add_step`, `_on_remove_step`, `_move_step`,
  `_on_clear_steps`; flesh out `_set_authoring_enabled`; `self._steps`)
- Test: `tests/test_gui_app.py`

**Interfaces:**
- Consumes: `build_step`, `FormValidationError`, `self._current_form`,
  `self._raw_values`.
- Produces:
  - `self._steps: list[Step]` — source of truth; `QListWidget` rows mirror it.
  - `self._pause_on_warning: QCheckBox`
  - `_on_add_step()`, `_on_remove_step()`, `_move_step(delta: int)`,
    `_on_clear_steps()`, `_step_summary(form_label, values, pause) -> str`.

- [ ] **Step 1: `__init__` — add `self._steps: list[Step] = []` and widgets**
  below the existing Run row, in order: a horizontal row with `+ Add to
  workflow` (`self._add_button` → `_on_add_step`) and `self._pause_on_warning`
  = `QCheckBox("pause on warning")`; a `QLabel("Steps:")`; `self._step_list`
  = `QListWidget()`; a row with `Remove`/`↑`/`↓`
  (`self._remove_button`/`_up_button`/`_down_button`) and `Run workflow`
  (`self._run_wf_button` → `_on_run_workflow`, Task 3) + `Clear`
  (`self._clear_button` → `_on_clear_steps`). Import `QListWidget` from
  `PySide6.QtWidgets`. Place these BEFORE the shared status/QA/output widgets
  so results stay at the bottom.

- [ ] **Step 2: `_step_summary`**

```python
def _step_summary(self, form_label: str, values: dict,
                  pause: bool) -> str:
    hint = next((str(v) for v in values.values()
                 if isinstance(v, str) and v.strip()), "")
    hint = f" ({hint})" if hint else ""
    tag = "  [pause-on-warn]" if pause else ""
    return f"{form_label}{hint}{tag}"
```

- [ ] **Step 3: `_on_add_step`** — build_step (inline error on
  `FormValidationError`, add nothing), set `step.pause_on_warning` from the
  checkbox, append to `self._steps`, append `_step_summary(...)` to
  `self._step_list`, call `_refresh_step_controls()`.

```python
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
    from dataclasses import replace
    step = replace(step, pause_on_warning=self._pause_on_warning.isChecked())
    self._steps.append(step)
    self._step_list.addItem(
        self._step_summary(form.label, values, step.pause_on_warning))
    self._refresh_step_controls()
```

- [ ] **Step 4: Remove / move / clear + `_refresh_step_controls`**

```python
def _selected_row(self) -> int:
    return self._step_list.currentRow()

def _on_remove_step(self) -> None:
    i = self._selected_row()
    if self._runner is not None or i < 0:
        return
    del self._steps[i]
    self._step_list.takeItem(i)
    self._refresh_step_controls()

def _move_step(self, delta: int) -> None:
    i = self._selected_row()
    j = i + delta
    if self._runner is not None or i < 0 or not (0 <= j < len(self._steps)):
        return
    self._steps[i], self._steps[j] = self._steps[j], self._steps[i]
    item = self._step_list.takeItem(i)
    self._step_list.insertItem(j, item)
    self._step_list.setCurrentRow(j)

def _on_clear_steps(self) -> None:
    if self._runner is not None:
        return
    self._steps.clear()
    self._step_list.clear()
    self._refresh_step_controls()

def _refresh_step_controls(self) -> None:
    has = bool(self._steps)
    self._run_wf_button.setEnabled(has and self._runner is None)
    self._clear_button.setEnabled(has and self._runner is None)
    for b in (self._remove_button, self._up_button, self._down_button):
        b.setEnabled(has and self._runner is None)
```

- [ ] **Step 5: Flesh out `_set_authoring_enabled`** (replace the Task-1 stub):

```python
def _set_authoring_enabled(self, enabled: bool) -> None:
    self._run_button.setEnabled(enabled)
    self._add_button.setEnabled(enabled)
    self._command_box.setEnabled(enabled)
    if enabled:
        self._refresh_step_controls()   # re-enable only if steps exist
    else:
        for b in (self._run_wf_button, self._clear_button,
                  self._remove_button, self._up_button, self._down_button):
            b.setEnabled(False)
```
Call `self._refresh_step_controls()` once at the end of `__init__` to set the
initial disabled state.

- [ ] **Step 6: Tests**

```python
def test_add_step_appends_to_list(qapp):
    win = MainWindow()
    form = win._forms["envmon validate-rtk-survey"]
    win._command_box.setCurrentText(form.label)
    win._field_widgets["csv_path"].setText("rtk.csv")
    win._on_add_step()
    assert len(win._steps) == 1
    assert win._step_list.count() == 1
    assert "validate-rtk-survey" in win._step_list.item(0).text()

def test_add_step_invalid_form_shows_error_adds_nothing(qapp):
    win = MainWindow()
    form = next(f for f in win._forms.values()
               if any(fld.required for fld in f.fields))
    win._command_box.setCurrentText(form.label)   # required left blank
    win._on_add_step()
    assert "Fix before adding" in win._status.text()
    assert win._steps == []

def test_pause_on_warning_checkbox_sets_step_flag(qapp):
    win = MainWindow()
    form = win._forms["envmon validate-rtk-survey"]
    win._command_box.setCurrentText(form.label)
    win._field_widgets["csv_path"].setText("rtk.csv")
    win._pause_on_warning.setChecked(True)
    win._on_add_step()
    assert win._steps[0].pause_on_warning is True
    assert "[pause-on-warn]" in win._step_list.item(0).text()

def test_move_and_remove_reorder_steps_and_list_in_lockstep(qapp):
    win = MainWindow()
    for label, val in [("envmon validate-rtk-survey", "a.csv"),
                       ("envmon list-tools", "")]:
        win._command_box.setCurrentText(label)
        if "csv_path" in win._field_widgets:
            win._field_widgets["csv_path"].setText(val)
        win._on_add_step()
    assert len(win._steps) == 2
    win._step_list.setCurrentRow(0)
    win._move_step(1)                      # swap 0 and 1
    assert win._step_list.currentRow() == 1
    first_cmd = win._steps[0].command
    win._step_list.setCurrentRow(0)
    win._on_remove_step()
    assert len(win._steps) == 1
    assert win._steps[0].command != first_cmd
```
Run: `python -m pytest tests/test_gui_app.py -q` → all PASS.

- [ ] **Step 7: Commit**

```bash
git add autogis/adapters/gui/app.py tests/test_gui_app.py
git commit -m "feat(gui): workflow authoring UI -- add/remove/reorder steps"
```

---

### Task 3: Run workflow — multi-step drive, Cancel, Resume, row marking

**Files:**
- Modify: `autogis/adapters/gui/app.py` (`__init__` Cancel/Resume buttons;
  `_on_run_workflow`, `_on_cancel`, `_on_resume`; row marking in
  `_render_result`; enable Resume in `_on_result` PAUSED branch)
- Test: `tests/test_gui_app.py`

**Interfaces:**
- Consumes: everything from Tasks 1-2 + `WorkflowRunner.cancel()`/`resume()`.
- Produces: `self._cancel_button`, `self._resume_button`, `_on_run_workflow`,
  `_on_cancel`, `_on_resume`.

- [ ] **Step 1: `__init__`** — add `self._cancel_button` ("Cancel" →
  `_on_cancel`) and `self._resume_button` ("Resume" → `_on_resume`) to the
  Run-workflow button row; both start disabled.

- [ ] **Step 2: `_on_run_workflow`**

```python
def _on_run_workflow(self) -> None:
    if self._runner is not None or not self._steps:
        return
    self._run_is_workflow = True
    for i in range(self._step_list.count()):   # reset row prefixes
        self._step_list.item(i).setText(self._step_list.item(i).text().lstrip("✓⏸✗ "))
    self._cancel_button.setEnabled(True)
    self._start_run(tuple(self._steps), "gui-workflow")
```

- [ ] **Step 3: Row marking in `_render_result`** — after rendering, if
  `self._run_is_workflow` and `index < self._step_list.count()`, prefix the
  row with an outcome glyph:

```python
    if self._run_is_workflow and index < self._step_list.count():
        glyph = {Decision.CONTINUE: "✓", Decision.HALT: "✗",
                 Decision.PAUSE_FOR_REVIEW: "⏸"}[result.decision]
        item = self._step_list.item(index)
        item.setText(f"{glyph} {item.text().lstrip('✓⏸✗ ')}")
```

- [ ] **Step 4: Enable Resume in the PAUSED branch of `_on_result`** — add
  `self._resume_button.setEnabled(True)` in the `elif state is RunState.PAUSED`
  block written in Task 1.

- [ ] **Step 5: `_on_cancel` / `_on_resume`**

```python
def _on_cancel(self) -> None:
    if self._runner is None:
        return
    self._runner.cancel()
    self._cancel_button.setEnabled(False)
    self._resume_button.setEnabled(False)
    if self._runner.status is not RunState.RUNNING:
        # cancel took effect immediately (idle/paused, no in-flight step) ->
        # no _on_result will fire to finish the run, so do it here. When a
        # step IS in flight, status stays RUNNING and _on_result finishes it
        # once that step completes.
        self._status.setText("Cancelled")
        self._finish_run()

def _on_resume(self) -> None:
    if self._runner is None or self._runner.status is not RunState.PAUSED:
        return
    self._runner.resume()
    self._resume_button.setEnabled(False)
    if self._runner.status is RunState.DONE:
        # pause was on the LAST step -> resume() goes straight to DONE
        # (runner.resume docstring); nothing left to advance to.
        self._status.setText("Workflow complete")
        self._finish_run()
    else:
        self._advance()
```

Add a test for the pause-on-last-step resume path:
```python
def test_pause_on_last_step_resume_completes(qapp, monkeypatch):
    _script_run_step(monkeypatch, [
        StepResult(Decision.PAUSE_FOR_REVIEW, "warnings", exit_code=0)])
    win = MainWindow()
    _add(win, "envmon validate-rtk-survey", pause=True)   # single step, pauses
    win._on_run_workflow()
    _pump_until(lambda: win._resume_button.isEnabled())
    win._on_resume()
    _pump_until(lambda: win._runner is None)
    assert "complete" in win._status.text().lower()
```

- [ ] **Step 6: `_finish_run` disables Cancel/Resume** — add to `_finish_run`:
```python
    self._cancel_button.setEnabled(False)
    self._resume_button.setEnabled(False)
```

- [ ] **Step 7: Tests** — a helper builds a runner whose `run_step` returns a
  scripted list of results in order.

```python
def _script_run_step(monkeypatch, results):
    it = iter(results)
    calls = {"n": 0}
    def fake(step, job_dir, **kw):
        calls["n"] += 1
        return next(it)
    monkeypatch.setattr(runner_mod, "run_step", fake)
    return calls

def _add(win, label, val="x.csv", pause=False):
    win._command_box.setCurrentText(label)
    if "csv_path" in win._field_widgets:
        win._field_widgets["csv_path"].setText(val)
    win._pause_on_warning.setChecked(pause)
    win._on_add_step()

def test_two_step_workflow_runs_both_to_done(qapp, monkeypatch):
    calls = _script_run_step(monkeypatch, [
        StepResult(Decision.CONTINUE, "ok", exit_code=0),
        StepResult(Decision.CONTINUE, "ok", exit_code=0)])
    win = MainWindow()
    _add(win, "envmon validate-rtk-survey"); _add(win, "envmon validate-rtk-survey")
    win._on_run_workflow()
    _pump_until(lambda: win._runner is None)
    assert calls["n"] == 2
    assert "complete" in win._status.text().lower()
    assert win._step_list.item(0).text().startswith("✓")
    assert win._step_list.item(1).text().startswith("✓")

def test_halt_stops_before_later_steps(qapp, monkeypatch):
    calls = _script_run_step(monkeypatch, [
        StepResult(Decision.HALT, "QA FAIL", exit_code=1),
        StepResult(Decision.CONTINUE, "ok", exit_code=0)])  # must never run
    win = MainWindow()
    _add(win, "envmon validate-rtk-survey"); _add(win, "envmon validate-rtk-survey")
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
    _add(win, "envmon validate-rtk-survey", pause=True)
    _add(win, "envmon validate-rtk-survey")
    win._on_run_workflow()
    _pump_until(lambda: win._resume_button.isEnabled())
    assert "PAUSED" in win._status.text()
    assert calls["n"] == 1
    win._on_resume()
    _pump_until(lambda: win._runner is None)
    assert calls["n"] == 2
    assert "complete" in win._status.text().lower()

def test_cancel_when_paused_ends_run(qapp, monkeypatch):
    _script_run_step(monkeypatch, [
        StepResult(Decision.PAUSE_FOR_REVIEW, "warnings", exit_code=0),
        StepResult(Decision.CONTINUE, "ok", exit_code=0)])
    win = MainWindow()
    _add(win, "envmon validate-rtk-survey", pause=True)
    _add(win, "envmon validate-rtk-survey")
    win._on_run_workflow()
    _pump_until(lambda: win._resume_button.isEnabled())
    win._on_cancel()
    _pump_until(lambda: win._runner is None)
    assert "Cancelled" in win._status.text()
```
Run: `python -m pytest tests/test_gui_app.py -q` → all PASS.

- [ ] **Step 8: Commit**

```bash
git add autogis/adapters/gui/app.py tests/test_gui_app.py
git commit -m "feat(gui): run multi-step workflows with pause/resume/cancel"
```

---

### Task 4: ADR-0062 + docs

**Files:**
- Create: `docs/adr/0062-gui-workflow-builder.md`
- Modify: `docs/adr/README.md` (index row); spec status line
- Modify: `app.py` module docstring (window is no longer only single-command)

- [ ] **Step 1: Verify 0062 is free** — `ls docs/adr/ | grep 006` and
  `gh pr list --state open` then check each open PR's files for a `docs/adr/`
  addition (the chapter's repeated-collision guard).

- [ ] **Step 2: Write ADR-0062** covering: the in-session/grow-window/gate-2/
  headless scope decisions and their rationale; the drive-loop unification
  (single Run = 1-step workflow through the shared loop) and the
  `_join_worker`/`_finish_run` split; why row-marking needs `_run_is_workflow`;
  accepted trade-offs (no persistence, no checkpoint steps, no auto ordering,
  offscreen tests can't certify appearance — human run outstanding); relate to
  ADR-0055/0057/0059/0060. Follow ADR-0059's structure.

- [ ] **Step 3: Add the README index row** (append after the 0060 row):
```
| [061](0062-gui-workflow-builder.md) | GUI workflow builder v1 -- assemble + run multi-step headless workflows over WorkflowRunner (in-session, gate-2 pause/halt/cancel) | Accepted | 2026-07-06 |
```

- [ ] **Step 4: Update the `app.py` module docstring** — the window now also
  assembles/runs multi-step workflows; keep it to a couple of lines.

- [ ] **Step 5: Update the spec status line** to `implemented` with the ADR/PR.

- [ ] **Step 6: Full suite + commit**
```bash
python -m pytest -q      # whole suite green
git add docs/adr/0062-gui-workflow-builder.md docs/adr/README.md \
        docs/superpowers/specs/2026-07-06-gui-workflow-builder-design.md \
        autogis/adapters/gui/app.py
git commit -m "docs(gui): ADR-0062 workflow builder + index"
```

---

## Post-implementation (outside the task list)

- Render an offscreen PNG of a built 2-step workflow (steps list + a completed
  run) and eyeball it.
- **Fable gate:** dispatch an independent `model: fable` bug-check +
  architectural review of the diff; fix real findings + a narrow re-check.
- Open the PR (base `main`); **do not self-merge** — report and ask.

## Self-Review

- **Spec coverage:** in-session (no persistence code) ✓; grow-window/Option A
  (Task 2 widgets under the form) ✓; single Run stays (Task 1 keeps `_on_run`)
  ✓; gate 2 — HALT (Task 1 terminal msg), Cancel (Task 3), pause-on-warning
  (Task 2 checkbox → Task 3 PAUSED/Resume) ✓; add/remove/reorder (Task 2) ✓;
  shared result panes (Task 1 `_render_result`) ✓; headless-only (unchanged
  filter) ✓; tests for every state (Task 3) ✓; ADR-0062 (Task 4) ✓.
- **Placeholder scan:** none — the Task-1 `_set_authoring_enabled` stub is
  explicitly replaced in Task 2 Step 5, not left dangling.
- **Type consistency:** `self._runner`, `_start_run(steps, name)`, `_advance`,
  `_finish_run`, `_render_result(result, index)`, `_run_is_workflow`,
  `self._steps`, `self._pause_on_warning`, `self._run_wf_button`,
  `self._cancel_button`, `self._resume_button` used identically across tasks.
