# ADR-0068: Record run history for `.pyt` toolbox executions via a toolbox_core helper

**Status:** Proposed (draft — do not implement without review)

**Date:** 2026-07-06

> **Placeholder number.** Parallel ADR streams collide on real numbers
> (ADR-0034 collision, PR #127; 0061/0062→0063 double collision). Assign the
> next free number at merge time, checking every open PR's files, not just
> `ls docs/adr/`.

## Context

ADR-0017 defines the run-history contract ("Every AutoGIS tool execution
needs an auditable record") and ADR-0054's `RecordingCommand`/
`RecordingGroup` finally wired its write side at the CLI adapter seam,
covering ~105 leaf commands across every CLI-mediated caller: console
script, CliRunner tests, and GUI subprocess launches
(`gui/executor.py` deliberately defers to the CLI seam).

One execution path still writes no record: **`.pyt` toolbox tools run
inside ArcGIS Pro**. ADR-0050 item 6's caller enumeration ("GUI-launched,
scripted, or a human at a terminal") never mentions the `.pyt` caller, and
the 2026-07-01 architecture review's H1 recommendation explicitly included
"the same call in the `.pyt` `execute()` bodies" — that half was never
implemented, and no ADR rejected it either.

Why it matters: nine CLI commands are redirect-only by design (ADR-0006 /
ADR-0039) — `import-gdb`, `build-event`, `build-callouts`, `gw-contours`,
`export-figures`, `full-pipeline`, `condition-dem`,
`compare-drone-surfaces`, `reconcile-locations --gdb` — so the `.pyt` is
those tools' *only* execution path. `evaluate_readiness`
(`core/envmon/evaluate_readiness.py`) flags `required_tool_not_run` for any
required tool without a `"success"` record. A readiness check naming any of
the report-pipeline tools is therefore **structurally unsatisfiable**: their
runs happen only where nothing records. Worse, the QA record's
`recommended_action` says to run `autogis envmon <tool>` — which for these
tools refuses by design. This is the surviving core of review finding H1;
everything else about H1 is fixed.

Two adjacent facts a reviewer needs:

- ADR-0017 claims "Path is configured in `SiteConfig` under
  `run_history_path`" — **that field was never implemented** (no hit in the
  codebase). ADR-0054 instead resolves the destination via the
  `AUTOGIS_RUN_HISTORY` env var, defaulting to `Path.cwd()/"run_history.csv"`.
- ADR-0051's sentinel byte-range lock already makes concurrent writers safe
  (Windows/msvcrt — and Pro is Windows-only), so a `.pyt` writer can run
  concurrently with CLI/GUI writers on a shared drive.

## Proposed decision

1. **Add an arcpy-free recording helper to `adapters/toolbox_core.py`** —
   the module that exists precisely so `.pyt` logic can be unit-tested
   headless. Suggested shape: a context manager

   ```python
   with recording_pyt_run("import-gdb", site_id=site.site_id,
                          dest_hint=gdb_path.parent):
       ...  # the existing execute() body
   ```

   It owns timing, status classification (clean exit → `success`;
   `KeyboardInterrupt` → `cancelled`; any exception → `error`, re-raised
   unchanged), input sanitization (`json.dumps(..., default=str)`, same as
   `RecordingCommand._record`), and the best-effort `RunHistory.write()`.
   Fully pytest-able with no arcpy present.

2. **Each `.pyt` `execute()` wraps its body in the context manager** — one
   line of untestable-in-CI code per tool, same footprint as the existing
   `require_runtime(...)` calls. Syntax errors are caught by the existing
   AST-parse test (`test_pyt_toolbox_parses`); behavior lives in the tested
   helper.

3. **Destination precedence** (the real design decision — pick one at
   review):

   - `AUTOGIS_RUN_HISTORY` env var, honoring the literal `off`
     (parity with ADR-0054), **then**
   - a per-tool `dest_hint` — recommended convention: the target GDB's
     parent directory, since every gen-1 tool takes a `gdb`/workspace
     parameter and that is where a project's readers will plausibly point
     `--run-history`, **then**
   - `Path.cwd()/"run_history.csv"` — last resort only; ArcGIS Pro's cwd is
     not the project directory, so records landing there are effectively
     lost to readers. (Alternative: finally implement
     `SiteConfig.run_history_path` per ADR-0017's original text — but only
     ~half the `.pyt` tools load a `SiteConfig`, so it cannot be the primary
     mechanism.)

4. **`site_id`/`event_id`**: from the tool's loaded `SiteConfig` /
   `event_date` parameter where available, `""`/`None` otherwise —
   ADR-0054's existing convention for site-less commands.

5. **No double-logging today**: no `.pyt` tool shells out to the CLI, so the
   CLI-seam recorder and this helper never both fire for one run. If that
   ever changes, mirror ADR-0054's `_SELF_LOGGING_COMMANDS` skip-list
   approach.

6. **Implementation gate**: per ADR-0039's discipline ("don't build
   untestable arcpy-only plumbing under an architecture-cleanup change"),
   the `.pyt`-side wiring ships only with a functional QA pass inside a real
   ArcGIS Pro session (same class as issues #173/#178), verifying a record
   actually lands where `evaluate-readiness --run-history` reads it.

## Consequences

### Positive

- `evaluate-readiness` and `portfolio-metrics` become satisfiable for the
  report-pipeline tools — the exact tools a readiness check names — closing
  the last H1 gap.
- Every execution path (CLI, GUI-via-CLI, `.pyt`-in-Pro) feeds one audit
  log; ADR-0017's "every tool execution" claim becomes true.
- Untestable surface stays one line per tool; all logic is headless-tested.

### Negative / accepted

- `execute()` bodies gain a line CI cannot exercise (mitigated per items 2
  and 6).
- `.pyt`-recorded `inputs` come from the tool's own marshalled parameter
  dict, thinner than the CLI's `ctx.params`. Accepted: audit trail, not
  replay (same trade as ADR-0054).
- A second write-side mechanism exists next to `RecordingCommand`. Accepted:
  the adapters genuinely differ (Click context vs. Esri parameter objects);
  the shared substrate (`RunRecord`, `RunHistory`, lock, best-effort
  semantics) is common.

## Alternatives considered

1. **Do nothing; document that run history covers only CLI-mediated runs.**
   Rejected: readiness's primary subjects are precisely the `.pyt`-only
   tools; the reader stays structurally broken for its main use case — H1's
   original substance.
2. **Inline `RunHistory.write()` calls in each `execute()`** (the review's
   literal wording). Rejected: ~10 copies of timing/classification logic in
   the one file pytest cannot import.
3. **`.pyt` `execute()` shells out to the CLI to inherit
   `RecordingCommand`.** Rejected: loses the live Pro session (open APRX,
   layouts) that tools like `ExportFigures` need in-process; contradicts
   ADR-0006's rationale for the `.pyt`.
4. **GDB `Env_RunHistory` table.** Already rejected by ADR-0017 alternative
   2 (readers must stay arcpy-free).

## Related decisions

- [ADR-0017](0017-run-history-csv-log.md) — the contract; its
  `SiteConfig.run_history_path` claim is corrected here.
- [ADR-0050](0050-unified-gui-adapter-direction.md) item 6 — CLI-seam
  recording; this ADR covers the caller its enumeration missed.
- [ADR-0051](0051-run-history-msvcrt-sentinel-lock.md) — makes the extra
  concurrent writer safe.
- [ADR-0054](0054-cli-seam-run-recording-recording-command.md) — the CLI
  seam mechanism this helper deliberately parallels.
- [ADR-0006](0006-pyt-toolbox-as-primary-ui.md) /
  [ADR-0039](0039-cli-first-generation-2-local-tools.md) — why the `.pyt`
  is the only execution path for gen-1 tools.
- `docs/reviews/fable-architecture-review.md` — finding H1, source of this
  proposal.
