# Claude Code kickoff — AutoGIS suite merge

Paste the block below to Claude Code from the repo root. It assumes both trees
are already in the working copy: the harness at `autogis/` and the
Environmental Monitoring code staged at `staging/envmon-incoming/`.

---

```
Read docs/MERGE_PLAN.md in full before doing anything. It is the authoritative
plan for merging the staged Environmental Monitoring toolbox
(staging/envmon-incoming/) into this AutoGIS harness as a single CLI- and
GUI-driven suite. I built both projects separately; the plan reconciles them.

Constraints — do not violate:
- One core, three adapters (CLI click-group, Esri .pyt GUI, future cloud).
  Adapters only marshal inputs and render output; ALL logic lives in core.
- Importing any autogis.core module must succeed with NEITHER arcgis NOR arcpy
  installed. Keep both lazy. `cloud` is a pip extra (arcgis); arcpy is
  runtime-detected, never an extra.
- Standardize reporting on the env project's QACollector + logging mirror, not
  the harness RunSummary. Single config-validation source on the dataclass.
- Preserve the carried-over data-safety rules and caveats in MERGE_PLAN §1
  (unverified H281 profile, untested arcpy paths, the flagged averaging rule,
  null screening levels). Do not silently regress them.

Work on a branch `merge/envmon-suite`, keep `main` green, and follow the
staged commit order in MERGE_PLAN §5 — one reviewable commit per step. Run
pytest after each step; the arcpy-dependent paths are not CI-able, so leave
them behind a runtime guard and note them for manual testing in Pro.

The two architecture decisions in MERGE_PLAN §6 are FINAL — build to them, do
not re-open them: (1) monorepo, single `autogis` package, no second package;
(2) all tools registered in the CLI group, but only tools 1/9/10 are headless-
supported while 2–8 are registered-but-runtime-guarded with the .pyt as their
primary interface.

Start with step 1 (scaffold without behavior change) and show me the plan for
that commit before writing code.
```

---

## Why this split of labor

The implementation belongs in Claude Code because the git history, the original
build context, and (critically) a real ArcGIS Pro environment to exercise the
arcpy paths all live on your machine. This Cowork session's job was to bridge
context the two sessions don't otherwise share: an accurate side-by-side of both
trees and the specific reconciliations the merge forces. That bridge is
`docs/MERGE_PLAN.md`.

## Before you run it

- The env code is staged at `staging/envmon-incoming/` (74 files; a locked
  `.pytest_cache` came along — add it to `.gitignore`). Commit it to the branch
  first so there's a real diff to merge against, then let Claude Code
  reorganize and finally delete the staging dir at step 6.
- The two architecture decisions in MERGE_PLAN §6 are already settled
  (monorepo; CLI registers all tools, 1/9/10 headless, 2–8 guarded), so Claude
  Code can proceed without stopping to ask.
