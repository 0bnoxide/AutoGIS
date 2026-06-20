# Handoff — envmon suite merge (2026-06-20)

Execution of `docs/superpowers/plans/2026-06-19-envmon-suite-merge.md` via
subagent-driven development (fresh subagent per task, reviewed between each).
Deltas spec (`docs/superpowers/specs/2026-06-19-mergeplan-deltas.md`) treated as
verified ground truth.

## Final state

- **Branch:** `merge/envmon-suite` (6 commits, one reviewable commit per task).
- **Merged:** PR [#1](https://github.com/0bnoxide/AutoGIS/pull/1) → `main`, merge commit `7ebbf2e`.
- **Tests:** `pytest -q` → **113 passed** (53 harness + 56 ported envmon + 4 new
  guard/CLI/capabilities), verified on the merged `main` state.
- **Arcpy-free invariant holds:** every `core`/`adapters`/`envmon` module imports
  with neither `arcpy` nor `arcgis` present.

### Commit map

| # | Commit | Task |
|---|--------|------|
| 1 | `7e94474` | Scaffold `core/common` + `runtime`, `core/harvest` package, CLI group, pyproject |
| 2 | `d0efcec` | Thread-safe QA/`Reporter` substrate, `disposition` + reserved provenance |
| 3 | `cc6ba1e` | Reference arcpy-free `.pyt` adapter + `toolbox_core` seam |
| 4 | `340facb` | Repackage 23 envmon modules → `autogis.core.envmon`, config reconciled, 56 tests ported |
| 5 | `1f600f8` | envmon CLI subcommands + 10 wired `.pyt` tools + runtime guard + session providers |
| 6 | `db9c75d` | Delete `staging/`, rewrite README + CHANGELOG |

## Decisions / deviations made during execution

- **Plan's "165 tests" target was wrong (double-count).** The baseline already
  collected the 56 envmon tests from `staging/` via a `sys.path` hack; relocating
  them keeps the real total at 113, not 165.
- **Task 5 `.pyt` correction.** The first pass stubbed the envmon Tool classes
  (imported core, called nothing). Caught in review; the real wiring was ported
  from the staging `.pyt` (`run_import(...)`, `build_current_event_wide(...)`,
  etc.) with `require_runtime(...)` guards added to the 7 LOCAL tools.
- **CLI tools 2–8** guard then raise a clear "use the Pro toolbox" `ClickException`
  rather than running headless. This follows the *winning* Global Constraints
  (".pyt is their primary UI; no rich CLI ergonomics for 2–8") over the plan's
  looser "then the core fn" wording.
- **`HarvestConfig` home:** canonical in `core/common/config.py` with a new
  `.load(path)` classmethod (nested-flatten + url-XOR-item_id validation on the
  dataclass); re-exported from `core/harvest/models.py` for back-compat. The
  legacy tuple-returning `adapters/config_loader.load_config` was left untouched
  (its CLI profile/override rewiring was deferred — see next actions).

## Next actions

### A. Functional gaps (address before relying on the suite)

1. **Surface harvester per-record results to the GUI.** `toolbox_core.run_harvest()`
   reads results off `RunSummary`, which carries only counts — so the `.pyt`
   `HarvestAttachments` tool reports 0 processed. Fix by having `harvest()` return
   (or attach) the `Manifest`/results list, then update `run_harvest` to use it.
   File: `autogis/core/harvest/harvester.py`, `autogis/adapters/toolbox_core.py`.
2. **Finish the H1 CLI rewiring (deferred from Task 4/5).** `adapters/config_loader.py`
   still returns the legacy `(HarvestConfig, profile)` tuple and applies the
   override whitelist. Per deltas H1, profile should be sourced from
   `runtime/sessions.agol_from_profile` and overrides applied in the CLI adapter
   around `HarvestConfig.load(path)`. Migrate `cli.py harvest` + `test_config_loader.py`
   to the single-object loader; retire the tuple shim.
3. **Reword / decide CLI 2–8 behavior.** Currently a `ClickException`. Confirm the
   "Pro-toolbox-only" stance is final, and make the message say so explicitly
   (it currently reads "not yet exposed headless," which implies unfinished work).

### B. Manual verification in ArcGIS Pro (un-CI-able — owner: you)

4. **Smoke-test all 11 `.pyt` tools in Pro.** Install per `docs/pro-install.md`
   (clone `arcgispro-py3`, `pip install -e .`, add `toolbox.pyt`), then run each
   tool against a real GDB. Watch the toolbox cache/reload gotcha (Refresh /
   restart Pro on import changes).
5. **Verify the LOCAL core call signatures end-to-end.** The `.pyt` execute bodies
   were ported faithfully but only AST-verified here; confirm each arcpy path
   (`import_to_gdb.run_import`, `groundwater_contours.build_groundwater_contours`,
   `export_figures.export_layouts`, `validate_database.validate_database`, the
   full pipeline) runs in Pro.

### C. Data / config caveats (preserved — must clear before production)

6. **H281 parser profile is an unverified DRAFT.** `autogis/config/parser_profiles/`
   keeps the DRAFT banner + `_TODO`s. Run Tool 1 + human review against a real
   H281 workbook, fix the `_TODO`s, clear the banner, before importing real data.
7. **Screening levels ship all-null.** `autogis/config/screening_levels/screening_levels.yaml`
   has ~37 `value: null` + `_TODO MDEQ RBSL`. Populate from the authoritative
   source; comparison stays tri-state (NULL = not evaluable) until then.

### D. Post-merge enhancements (reserved now, flesh out later)

8. **Fill the reserved provenance columns.** `AttachmentResult` reserves
   `checksum`/`algorithm`/`geometry`/`source_table`/`relationship_id` (empty).
   Wiring them avoids a second manifest-schema migration. Note: the harvester
   queries with `return_geometry=False` today — flip that for GeoJSON support.
9. **Flesh out `core/common/seen.py`.** Currently an interface stub for the single
   "seen-before" abstraction (harvester checksum-skip + envmon unique-key
   idempotency).

### E. Repo hygiene

10. **Add CI.** The arcpy-free suite (all 113 tests) is fully CI-able — add a
    GitHub Actions workflow (or the `session-start-hook`) running `pytest -q` so
    regressions are caught. Tools 2–8's pure logic is already covered.
11. **Delete the merged branch** `merge/envmon-suite` once you're satisfied.
12. **Minor:** `load_screening_levels`/`ConfigError` are imported in `toolbox.pyt`
    but currently unused — drop if you wire a linter.
