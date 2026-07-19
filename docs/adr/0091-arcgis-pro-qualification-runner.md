# ADR-0091: ArcGIS Pro qualification runner (roadmap Phase 1)

**Status:** Proposed — owner merge of the ADR PR constitutes sign-off (roadmap
shared gate item 1)

**Date:** 2026-07-19

## Context

The production roadmap (ADR-0087, `docs/production-roadmap.md`) opens with
Phase 1: a repeatable local qualification command that instantiates every
`.pyt` tool, validates parameter construction, exercises representative arcpy
seams against a scratch geodatabase, and reports Pro version, extensions,
passes, failures, and skips in JSON plus a human-readable report.

The need is structural, not hypothetical: arcpy seams are `pragma: no cover`
(~35 call sites), so the headless suite cannot catch `.pyt`/arcpy defects —
that is how #174 (invalid enum keyword) and #214 (FilterObject crash at
dialog-open, fixed in a0dc8b9) shipped. Six of nine open issues are manual
Pro-QA rows; the runner exists to shrink that class (#231 outright; the
parameter/instantiation halves of #222/#238).

Environment: this machine has ArcGIS Pro 3.6.1 with the cloned
`arcgispro-py3-autogis` conda env (`docs/arcpy-environment.md`). No Pro 3.5
install exists or is planned.

## Decision

### Architecture

- **Core:** one new module `autogis/core/qualify.py` — check logic + report
  model (`Check`, `QualificationReport`, `collect_environment`,
  `check_toolbox`, `exercise_scratch_gdb`, `run_qualification`). arcpy-free at
  import (arcpy reached only inside functions), auto-enforced by
  `tests/test_boundary_imports.py`. No module-level `datetime`/`math`/`numpy`/
  `time` names (`__main__` stomping hazard, see `cli.py` RecordingCommand
  notes).
- **Adapter:** CLI leaf `envmon qualify` in `autogis/adapters/cli.py`:
  `_guard("qualify")` then call core. Inherits run-history recording for free
  (RecordingCommand, ADR-0076). Registry: `TOOLS["qualify"] = Runtime.LOCAL`
  plus one `_REGISTRY_SEED` entry (parity tests require both).
- **Invocation** (live QA): Pro conda python with `PYTHONPATH` per
  `docs/arcpy-environment.md`; `python -m autogis envmon qualify --out DIR`.

### Checks — slice 1

- **Environment/preflight:** `arcpy.GetInstallInfo()["Version"]`,
  `arcpy.ProductInfo()`, `arcpy.CheckExtension(code)` for exactly
  `("Spatial", "3D", "ImageAnalyst", "GeoStats")` — the four codes production
  tools depend on — plus `sys.executable` and `autogis.__file__` provenance.
  These arcpy calls are themselves ADR-0077 subjects: doc-verified against
  current Esri pages in the implementing session, cited in the PR.
- **Tier 1 (all 19 tools):** load `toolbox.pyt` via `importlib` SourceFileLoader,
  enumerate `Toolbox().tools` at runtime (never a hardcoded list — parity
  tests guarantee registration completeness), and per tool: instantiate, call
  `getParameterInfo()` (the #214 crash site), assert unique parameter names,
  call `updateParameters()` where present. One `arcpy.ImportToolbox()` pass so
  Pro's own loader validates the file. Per-tool exceptions → `fail` with
  traceback.
- **Tier 2 (scratch GDB, zero new arcpy surface):** in a temp dir, call the
  shipped seams `create_or_update_gdb_schema()` (creates the FileGDB plus full
  schema from nothing) then the core validate-database read-back. Windows
  FileGDB-lock cleanup is best-effort, never a check failure.

### Report

`qualification.json` (schema 1: `environment`, `checks[]` with
`id/outcome/seconds/detail`, `summary` pass/fail/skip counts) plus
`qualification.md`, written to `--out DIR`. Exit codes: 0 all-pass (skips
allowed), 1 any check failed, 2 precondition failure (e.g. uninitialized Pro
license → documented remediation text, never a check "fail"). The command sets
`AUTOGIS_RUN_HISTORY` into the out-dir first thing (prevents cwd-scatter when
slice 2 executes tools). The human report states the coverage boundary
explicitly: Tier 1 + slice-1 Tier 2 does not execute tool bodies, so
#174-class enum defects inside seams are out of scope until slice 2.

### Canaries (gate detection clauses)

`--self-test` runs only two canaries and exits 0 iff **both are detected as
failures**:

1. **Broken parameter definition:** an internal `_BrokenParamCanary` tool class
   whose `getParameterInfo` reproduces #214 (ValueList filter containing `""`),
   injected through the identical `check_toolbox` path via an `extra_tools`
   parameter. Implementation must live-verify the assignment raises in
   standalone Pro python; documented fallback is a directly-raising canary
   (weaker — records which variant shipped).
2. **Failing scratch-GDB operation:** `exercise_scratch_gdb(doomed=True)`
   targets a GDB path whose parent is a plain file, guaranteeing the shipped
   seam fails. Same production code path, no mocks.

No permanent expected-fail checks in normal runs; `toolbox.pyt` is never
mutated to test the tester.

### Production gate — amended (owner decision, 2026-07-19)

The Phase 1 gate's "completes on ArcGIS Pro 3.5 and the current preferred Pro
release" is **amended to "the currently installed Pro release"** (no 3.5
install exists). Recorded consequence: a green run on 3.6.1 proves nothing
about the Pro 3.5 compliance floor — 3.5-floor compliance remains an
authoring-time documentation-verification duty (ADR-0077) that the runner
complements and never discharges. The runner is version-agnostic (no
version-conditional code), so a 3.5 gate run can be added later without design
change. Gate evidence: one normal run with 0 fails plus one `--self-test` run
exiting 0 on the installed Pro, transcripts cited in the closing PR.

### Deferred (later slices — not licensed by this ADR)

- **Slice 2:** `execute()` of the synthetic-feasible keystone chain
  (`gen-synthetic-workbook` → ImportToGdb → BuildCurrentEvent/BuildCallouts/
  ValidateDatabase) with real `arcpy.Parameter` objects and a minimal messages
  fake; run-history/readiness assertions (mechanizes #231).
- **Slice 3+:** extension-gated tools (skip-with-reason via CheckExtension),
  CAD/Civil 3D rows (#238), opt-in network rows behind `OPENTOPOGRAPHY_API_KEY`
  (#222/#256), human-only checklist emission.
- **Permanently Tier-1 (classified, never executed, never stubbed):**
  HarvestAttachments (hardcoded portal `GIS("pro")`), ExportFigures (real
  template APRX), DownloadOpenTopoDEM (unconditional
  `ArcGISProject("CURRENT")`).

## Consequences

- Easier: repeatable evidence that every tool constructs; the #214 defect
  class is caught before a dialog ever opens; manual Pro-QA rows shrink
  (fully: #231 at slice 2; partially: #222/#238 now).
- Harder / duties created: every defect the runner catches live must get a
  code fix **plus a backported headless pin** (ast or fake-arcpy, like the
  LyrName and param-order pins in `tests/test_toolbox_cad.py`) — otherwise the
  runner becomes the only guard and it needs Pro to run. The runner never
  discharges ADR-0077 doc-verification. The suite boundary holds: the runner
  is never pytest-collected; pytest never runs from the Pro env.
- Known landmines deliberately left for slice 2 as findings, fixed in the
  toolbox not the runner: FullPipeline empty-multivalue crash, ExportFigures
  template fallback.

## Alternatives considered

- **Standalone script / `python -m autogis.core.qualify`:** zero registry
  footprint but re-implements or skips guard + run-history recording that the
  CLI leaf gets free. Rejected.
- **Full keystone-chain execution in slice 1:** closer to Pro reality but
  pulls fixture generation and execute()-driving forward; the gate's clauses
  are met without it and slice 2 is unchanged. Rejected for slice 1.
- **Permanent expected-fail canaries in every run:** continuous detector
  proof at the cost of an xfail vocabulary and noisier reports; speculative
  until a canary ever regresses. Rejected.
- **Procuring a Pro 3.5 environment for the gate:** rejected by owner
  2026-07-19; gate amended as above.

## Related decisions

- ADR-0087 — post-catalog production roadmap (Phase 1 ordering)
- ADR-0077 — arcpy documentation-verification policy (floor stays 3.5)
- ADR-0076 — run-history site identity (runner records itself via the CLI seam)
- ADR-0006 — .pyt toolbox as primary UI for LOCAL tools
- ADR-0085 — Phase-5 slice tools appearing in the Tier-1 inventory
