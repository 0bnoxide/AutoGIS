# ADR-0062: GUI LOCAL (arcpy) tool support — `local_python` picker, Run gating, class-1 reachability map

**Status:** Accepted

**Date:** 2026-07-06

## Context

[ADR-0057](0057-gui-walking-skeleton.md) shipped the GUI window scoped to
headless commands only; LOCAL (arcpy) tools were filtered out and a
`local_python` settings UI was explicitly deferred. The executor already
accepts a `local_python` (the `python.exe` of a cloned arcgispro-py3 env) and
the runner threads it through (ADR-0053/0055) — only the UI was missing.

Reading the CLI command bodies first surfaced the load-bearing fact: **a
LOCAL tool needing arcpy does NOT mean it runs via the CLI.** Two classes
exist:

- **class-2, executable:** the command guards for arcpy, then actually calls
  the core tool (`import-edd`, `validate-db`, `sync-to-gdb`,
  `survey-to-well-elevation`, …). These become runnable from the GUI once a
  `local_python` is set.
- **class-1, redirect-only:** the command guards, then *unconditionally*
  raises "use the .pyt toolbox" / "not implemented" (`import-gdb`,
  `build-event`, tools 2–7, the callout dead ends, `build-cad-package`).
  Running one via `local_python` only ever HALTs with that message.

Naively lifting the arcpy filter would therefore render always-broken buttons
for every class-1 tool. The user chose (over "show all, let them HALT" and
"hide class-1 entirely") to **grey class-1 out with the reason** — the best
UX, and the first real use of the `unreachable` map the introspector
(ADR-0052) has always accepted.

## Decision

1. **`gui/settings.py` (new): persist `local_python` via `QSettings`.** Qt's
   native per-user store (registry on Windows) — no new dependency, no
   hand-rolled config file. `get/set_local_python` take an optional injected
   store so tests use a temp ini and never touch the real registry.

2. **`gui/reachability.py` (new): the class-1 `UNREACHABLE` map** — space-joined
   command label → human reason (ADR-0006 Pro-only tools + ADR-0039 dead ends
   + `build-cad-package`'s unwired CAD leg). Curated, not derived (the
   redirect-vs-execute split is encoded nowhere programmatic); a drift-guard
   test asserts every label resolves to a real command. Kept out of
   `introspect.py` (whose docstring says policy lives elsewhere); reusable by
   a future workflow builder that must exclude never-runnable steps.

3. **`app.py`: show every command, gate Run.** Forms come from
   `introspect_cli(unreachable=UNREACHABLE)` — headless, class-2 LOCAL, and
   greyed class-1 all listed. A persisted `local_python` picker row (line edit
   + Browse) sits above the command box. `_run_blocked_reason` gates the Run
   button, precedence first-match:
   - class-1 (`unreachable_reason`) → disabled, reason shown (even *with* a
     `local_python` — unreachable wins);
   - class-2 (`needs_arcpy_env` and no `local_python`) → disabled, "set the
     arcgispro-py3 python.exe" hint;
   - otherwise runnable.
   Editing/browsing `local_python` re-gates live; `local_python` is threaded
   into `WorkflowRunner(local_python=…)` for the run.

## Consequences

### Positive

- ~17 class-2 LOCAL tools become runnable from the GUI once the user points
  `local_python` at their arcgispro-py3 clone; the setting survives launches.
- class-1 tools are visible-but-greyed with the reason, instead of absent
  (looks like an oversight) or a button that always HALTs.
- 15 new offscreen tests (settings round-trip/clear, reachability drift +
  class membership, class-1 disabled, class-1 stays blocked even with
  `local_python`, class-2 gated-then-runnable, headless free, live re-gate on
  edit, Browse persist, `local_python` reaches `run_step`).
- New logic lives in two small focused modules, keeping the `app.py` change
  (and its merge-conflict surface with a parallel workflow-builder effort on
  the same file) minimal.

### Negative / accepted trade-offs

- **Real arcpy execution of a class-2 tool is user-unverified.** There is no
  arcpy in this environment, so the offscreen tests prove the wiring, the
  gating, and the persistence — *not* that `validate-db` actually runs under a
  real arcgispro-py3. A human must confirm that (tracked as a visual/functional
  QA issue, same posture as ADR-0057/0060's look-and-feel caveat).
- **HYBRID over-restriction:** a few class-2 tools have a headless sub-path
  *and* a `--gdb` arcpy path (`sync-to-gdb`, `survey-to-well-elevation`, …).
  Because `needs_arcpy_env` keys on the LOCAL Runtime, the GUI gates the whole
  command on `local_python` — stricter than the CLI (their headless path is
  blocked without one) but safe (never runs arcpy without it) and strictly
  more than before (they were fully hidden). Not worth per-parameter
  conditional modeling for this slice.
- **No `local_python` validation:** the path is not checked for existence or
  arcpy-importability. A bad path fails cleanly at run time (subprocess
  `OSError`/guard error → HALT); a filesystem/arcpy probe would be complexity
  for little gain (`ponytail`).
- The `UNREACHABLE` map is hand-curated; a newly added class-1 tool must be
  added to it or it will render a runnable-but-HALT button. The drift guard
  only catches stale labels, not new omissions.

## Alternatives considered

1. **Show all LOCAL tools, let class-1 HALT at run time.** Rejected by the
   user: zero classification machinery, but the user only learns a tool is a
   dead end after clicking Run.
2. **Hide class-1 entirely (allowlist class-2).** Rejected: the user can't
   tell a missing tool from an oversight, and it needs the same curated list.
3. **Persist via a hand-rolled JSON config file / an env var.** Rejected:
   `QSettings` is already available (PySide6), native, and location-correct
   per platform; a file needs a format and a location decision, an env var
   gives no in-GUI setting.
4. **Validate `local_python` (probe `import arcpy`).** Rejected as YAGNI and
   slow (spawning the interpreter); the run surfaces a bad path cleanly.

## Related decisions

- [ADR-0057](0057-gui-walking-skeleton.md) — the headless-only window this
  extends; deferred exactly this `local_python` UI.
- [ADR-0053](0053-gui-executor-qa-signal.md) — the executor's `local_python`
  parameter this UI finally supplies.
- [ADR-0006](0006-pyt-toolbox-as-primary-ui.md) /
  [ADR-0039](0039-cli-first-generation-2-local-tools.md) — the policy behind
  the class-1 `UNREACHABLE` set.
- [ADR-0052](0052-gui-introspection-layer.md) — the `unreachable` map this is
  the first consumer of.

## Issues/PRs

- This decision + implementation: `autogis/adapters/gui/settings.py`,
  `autogis/adapters/gui/reachability.py`,
  `autogis/adapters/gui/app.py`, `tests/test_gui_app.py`,
  `tests/test_gui_settings.py`, `tests/test_gui_reachability.py`.
