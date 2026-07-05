# ADR-0057: GUI walking skeleton — PySide6 as an optional extra, QThread bridge, headless-only first slice

**Status:** Accepted

**Date:** 2026-07-05

## Context

Four toolkit-free layers now exist (`introspect.py` ADR-0052, `executor.py`
ADR-0053, `runner.py` ADR-0055, `forms.py` ADR-0056) forming a complete
chain: Click command tree -> renderable form -> validated `Step` -> one
executed subprocess -> a multi-step workflow driven end to end. Per
CLAUDE.md's own rule ("if you can't test the UI, say so explicitly rather
than claiming success") and the standing project discipline around this GUI
chapter, the actual PySide6 widget layer was deliberately deferred until
this point — it cannot be adversarially verified the same way (real
subprocess/thread tests, Fable review) the prior four pieces were, so it
needed the user's explicit go-ahead before any widget code, not an
autonomous continuation.

Before writing any widget code, two environment facts were checked rather
than assumed:

1. **PySide6 was not installed anywhere in this project.** `pyproject.toml`
   had zero GUI dependencies (core deps: PyYAML, click, openpyxl, numpy;
   existing optional extras: `cloud` for arcgis, `report` for Pillow).
2. **Qt's `offscreen` platform plugin works in this environment**
   (`QT_QPA_PLATFORM=offscreen` lets a real `QApplication`/`QMainWindow`
   construct, show, and process events with no physical display) — meaning
   automated smoke tests against the *real* widget tree are possible, not
   just import checks.

## Decision

1. **PySide6 added as a new optional extra, `gui = ["PySide6"]`**, matching
   the existing `cloud`/`report` extras pattern — not a core dependency.
   Console script `autogis-gui = "autogis.adapters.gui.app:main"` added
   alongside the existing `autogis`/`autogis-harvest` entries.

2. **`autogis/adapters/gui/app.py` — one window, headless commands only.**
   Lists every `CommandForm` from `introspect_cli()` that is not
   `unreachable_reason`-flagged and not `needs_arcpy_env()` (a LOCAL/arcpy
   tool). Selecting a command renders its `FormField`s as plain widgets
   (`QLineEdit`/`QCheckBox`/`QComboBox`); Run calls `forms.build_step()`,
   shows a `FormValidationError` inline if raised, otherwise wraps the
   `Step` in a single-step `Workflow` and drives it through a real
   `WorkflowRunner`. **Deliberately excludes LOCAL tools**: those need a
   `local_python` (arcgispro-py3 clone) picker, a distinct settings problem
   left for a later slice, so this first window never has to solve it.

3. **The `QThread`-vs-`QRunnable`-vs-asyncio choice ADR-0055 explicitly
   punted is resolved here: a `QThread` subclass (`_StepWorker`).**
   `WorkflowRunner.advance()` is a single blocking call; `_StepWorker.run()`
   calls it and reports back via two Qt signals (`finished_result`,
   `failed`) — signals being the one thread-safe way to touch widgets from
   another thread in Qt, which is exactly why `runner.py` exposed a
   lock-guarded `advance()`/`.status` surface instead of inventing its own
   callback mechanism.

4. **Every `_StepWorker` is explicitly joined (`.wait()`) before its result
   is considered final**, inside both `_on_result` and `_on_failure` — not
   left to rely on Qt's own `finished` signal's queued-delivery timing (see
   Consequences: this was tried first and was not sufficient).

5. **Two pre-existing bugs, invisible until this first real UI consumer,
   were fixed as part of this slice, at their root cause:**
   - `introspect.py`'s `_field()` copied `param.default` directly. Click
     >= 8.4 uses an internal `UNSET` sentinel (not `None`) to mean "no
     default declared," which leaked into `FormField.default` for any
     required field — invisible until `app.py` became the first code to
     *render* `.default` (pre-filling a text widget with `str(UNSET)`
     instead of leaving it blank, which then masked a missing-required-field
     validation error). Fixed by reading
     `param.to_info_dict()["default"]` instead — Click's own public,
     documented normalization of that same sentinel back to `None`
     (`to_info_dict` exists specifically "for documentation purposes" and
     already does this exact conversion).
   - A `QThread` lifecycle crash (`0xC0000005` access violation, ~40% of
     runs): destroying a `_StepWorker` (e.g. via Python GC dropping a
     `MainWindow`'s last reference once a test/caller moves on) while its
     underlying OS thread hadn't fully settled is undefined behavior in Qt.
     Fixed per decision 4.

6. **`os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")` at the top of
   the test file**, so the test suite never accidentally tries to spin up a
   real native window in CI/automation — verified this is necessary, not
   redundant: without it, `python -m pytest` on this project's Windows
   environment attempted real native platform initialization and (before
   decision 4's fix) manifested the QThread crash as an apparent hang.

## Consequences

### Positive

- The entire toolkit-free chain (introspect -> forms -> runner -> executor)
  is now exercised through a real Qt event loop and a real `QThread`, not
  just unit tests of each layer in isolation — and doing so immediately
  surfaced two real bugs neither layer's own test suite had a way to catch
  (a value nothing rendered, and a lifecycle interaction only a real
  `QThread` instance exposes).
- 7 new automated smoke tests run against the *real* widget tree via Qt's
  `offscreen` platform (construction, form rebuild on selection, inline
  validation-error path, the full run-a-step-on-a-worker-thread path twice
  over — success and failure — and an explicit disabled-while-in-flight
  check using a gated fake `run_step`) — genuine automated confidence, not
  a rubber stamp.
- LOCAL (arcpy) tools and the `local_python` settings problem are entirely
  out of this slice's scope, keeping it small enough to review and land in
  one PR.

### Negative / accepted trade-offs

- **This ADR cannot certify the window looks or feels right** — only that
  it constructs, wires signals correctly, and doesn't crash under Qt's
  offscreen plugin. A human must actually run `autogis-gui` (or
  `python -m autogis.adapters.gui.app`) and look at it. That verification
  is explicitly outstanding as of this ADR.
- No workflow builder (multi-step assembly), no LOCAL-tool support, no
  settings/persistence UI, no `unreachable` dict populated (still nobody
  computes ADR-0006/ADR-0039's reachability data — unaffected by this
  slice, tracked separately). All deliberately deferred to keep this the
  smallest slice that exercises the full chain end to end.

## Alternatives considered

1. **Connect `QThread.finished` to `self._worker.wait` instead of calling
   `wait()` explicitly inside the result/failure handlers.** Tried first;
   insufficient. `finished_result`/`failed` (custom signals, emitted from
   inside `run()`) and Qt's own `finished` (emitted by the `QThread`
   machinery immediately after `run()` returns) are delivered as separate
   queued events — nothing guarantees the `finished`-triggered `wait()`
   lands before a caller (a test function, a later `_on_run()` replacing
   `self._worker`) observes the button re-enabled and moves on, dropping
   the last reference. Reproduced empirically: this approach still crashed
   ~2/5 runs. Calling `.wait()` synchronously as the first line of the
   *same* handler the caller is waiting on (`_on_result`/`_on_failure`)
   closes that race because there is no second queued hop to lose.
2. **A worker-object + `moveToThread()` pattern instead of subclassing
   `QThread`.** Considered (it is Qt's more modern recommended pattern);
   rejected for this first slice as more moving parts than a single
   blocking `advance()` call needs — a `QThread` subclass with one `run()`
   body is the smaller diff and is fully sufficient here.
3. **Skip the `introspect.py` default-sentinel fix and just avoid rendering
   `FormField.default` for required fields in `app.py`.** Rejected: that
   would hide the bug at the one call site that happened to expose it
   instead of fixing the actual defect, and the sentinel leak would still
   be latent for any other future consumer of `FormField.default`.
4. **Include LOCAL (arcpy) tools in this first slice, with a `local_python`
   picker.** Rejected as scope creep for a walking skeleton — a settings
   UI for picking an arcgispro-py3 clone path is a distinct, separately
   reviewable piece of work.

## Related decisions

- [ADR-0050](0050-unified-gui-adapter-direction.md) — PySide6 as the chosen
  framework (decision 3); this ADR is its first actual code.
- [ADR-0055](0055-gui-workflow-runner-thread-boundary.md) — explicitly
  punted the `QThread`/`QRunnable`/asyncio choice to "the widget-layer
  task"; this ADR is that task, resolved as `QThread`.
- [ADR-0052](0052-gui-introspection-layer.md) — `FormField.default`'s
  source; the `UNSET`-sentinel fix lives in `introspect.py`, not here.
- [ADR-0056](0056-gui-form-step-adapter.md) — `build_step()`, called
  directly from the Run button handler with no adapter shim needed.

## Issues/PRs

- This decision + implementation: `autogis/adapters/gui/app.py`,
  `tests/test_gui_app.py`, `pyproject.toml` (`gui` extra,
  `autogis-gui` script), and the `introspect.py`/`param.default` fix.
