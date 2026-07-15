# Session hand-off — 2026-07-15: geostatistical Phase-5 gate OPENED

**For a fresh session tasked with the geostatistical conditional tools.**
Written by the ADR-0084 session; the user explicitly reopened this tool group
in that session on 2026-07-15.

## The gate decision (authoritative record)

- **The Phase-5 geostatistical group is REOPENED** — user decision, 2026-07-15
  ("We'll open the geostatistical tools"). CLAUDE.md's deferred-groups section
  is updated in the same commit as this hand-off.
- **The AI-assisted group (§11) remains deferred.** Nothing here touches it.
- Reopened ≠ implement-first. Both governing docs say the same thing: the
  group is **blocked on an architecture review**, and per the design stub's
  exit criteria, *"Resolution belongs in an ADR … Do not implement against
  this stub."* Your first deliverable is the architecture review outcome as a
  **Proposed ADR** (next free number; 0084 was the last used), signed off by
  the user in plain text **before** any per-tool spec or code.

## Scope: exactly 3 tools

| Tool | Priority | Primary blocker (per review doc) |
|---|---|---|
| `RunFieldToGroundwaterModelPipeline` | HIGH | Model QA schema |
| `BuildGroundwaterSurfaceModel` | HIGH | Uncertainty output format |
| `BuildAnalyticalConcentrationSurface` | MED-HIGH | Nondetect rules + plume boundary |

The other 6 tools originally reviewed as conditional have **all shipped**
(ADR-0061 rescoped 3 of them out of this gate; see issue #167). Do not
re-review them.

## Repo state at hand-off

- `main` tip: `8e53611` (PR #236 merged). Full suite green in a `[dev]` env:
  2059 passed / 6 skipped. `xlrd` and `numpy` must be installed
  (`pip install -e '.[dev]'`) or collection fails.
- ADR-0084 (#230 key collisions): analytical half fixed; QC half deliberately
  reopened as a known limitation. Unrelated to geostat — context only.

## Read these first (in order)

1. `docs/CONDITIONAL_TOOLS_REVIEW.md` — per-tool blockers, staged integration
   paths (TIN → IDW → EBK/kriging), the numbered "Architecture Decisions
   Needed" lists, and H281/ZT42 test cases. Updated 2026-07-06.
2. `docs/superpowers/specs/2026-06-28-geostatistical-conditional-tools-design.md`
   — the 4 shared blockers (dependency/execution mode, nondetect rules, model
   registry + ranking, graphics/CAD format) and the ADR exit criteria.
3. `docs/adr/0061-drone-geotech-graphics-tool-batch.md` — the rescope
   precedent; shows how tools left this gate last time.
4. Issue #167 — gate history.

## Shipped infrastructure the review docs predate (CHECK BEFORE RE-DECIDING)

The review doc is dated 2026-06-25; substantial adjacent infrastructure has
shipped since. Run a reuse-inventory pass before drafting the ADR — several
"blockers" are now partially resolved:

- **`autogis/core/envmon/groundwater_contours.py`** — TIN / IDW /
  NaturalNeighbor **draft contours + draft flow arrow already exist**, with
  the DRAFT-status convention (`ReviewStatus='DRAFT'`, professional review
  required) and license degradation (3D Analyst for TIN, Spatial Analyst for
  IDW/NN → skip + QA ERROR, never crash). "Stage 1: TIN only" from the review
  doc's recommended path is substantially built.
- **`autogis/core/envmon/evaluate_gw_models.py`** (`evaluate-gw-models`) —
  headless cross-validation ranking (RMSE / signed bias / MAE /
  pct-within-tolerance, rank by RMSE) that consumes externally-computed
  predictions from CSV. The design stub's blocker 3 ("model output registry +
  ranking … not yet designed") is partially answered — what's missing is a
  persisted GDB registry, not the metrics.
- **`autogis/core/envmon/draft_plume_boundary.py`** (numpy hull) and
  **`estimate_gw_flow_direction.py`** — plume-boundary and flow-direction
  drafts exist.
- **GDB schemas already present** (`gdb_schema.py`): `Env_GWContourPoints`,
  `Env_GWContours_Draft`, `Env_GWFlowArrow_Draft`, `Env_PlumeBoundary_Draft`,
  `ElevationHistory`. No `GW_Model*` registry tables yet — that schema is
  genuinely undesigned.
- **`numpy>=1.24` is already a required dependency** (pyproject). The design
  stub's "heavy new deps" concern applies to scipy/scikit-learn (still NOT
  deps) and to arcpy Geostatistical Analyst, not to numpy.
- **`generate-reg-tables` shipped** with a nondetect-rule config — check its
  YAML/config shape for reuse before designing the shared nondetect policy
  (design-stub blocker 2 wants one config shared across tools).
- `survey-to-well-elevation`, `condition-dem`, `compare-drone-surfaces`,
  `generate-subsurface-profile` — shipped siblings; useful `.pyt`-seam and
  LOCAL-tool patterns.

## What the ADR must decide (deduped from both docs)

1. **Execution-mode split per stage** — which stages run headless
   (numpy/stdlib) vs LOCAL through the `.pyt` seam (arcpy Spatial/3D/
   Geostatistical Analyst). TIN/IDW draft contours are already LOCAL-degrading;
   EBK/kriging is the real decision (Geostatistical Analyst license, or defer).
2. **Model QA / registry schema** — `GW_ModelInputPoints`,
   `GW_ModelExcludedPoints`, `GW_ModelQA`, `GW_ModelCrossValidation` (or
   reuse/extend what `evaluate_gw_models` implies). Additive tables only;
   `SCHEMA_VERSION` bump.
3. **Ranking + approval workflow** — hydro judgment trumps metrics (review doc
   is explicit); how approval is recorded (status flag pattern exists:
   `ReviewStatus` DRAFT → approved).
4. **Nondetect policy config** — shared schema (exclude / half-RL / RL /
   zero / censored-placeholder), per analyte/matrix; reuse the
   `generate-reg-tables` precedent.
5. **Plume boundary rules** — threshold source (screening level vs site
   cleanup level), boundary clipping (site polygon / well buffer),
   multi-analyte handling.
6. **Uncertainty presentation** — EBK/kriging standard-error output format
   (only if kriging is in scope for slice 1 — the staged paths in both docs
   say defer it).

A defensible slice-1 shape (verify, don't assume): pipeline orchestration of
already-shipped pieces (contours → cross-validation → registry) + the
registry schema + nondetect config, with EBK/kriging as a later slice. That
mirrors the staged path both docs recommend and is the ponytail answer.

## Process requirements (non-negotiable, from CLAUDE.md + session lessons)

- **Invoke the `ponytail` skill (full) before writing code.**
- **`main` is READ-ONLY.** Feature branch + coordination claims first
  (`.claude/coordination/`; see CLAUDE.md). Your branch will be named by your
  session harness.
- **ADR-0077:** every arcpy call (kriging/EBK/GA especially) doc-verified
  against pro.arcgis.com in the writing session; cite pages in the PR.
  Compliance floor ArcGIS Pro 3.5. Geostatistical Analyst calls are exactly
  the ADR-0077 risk class — training-data recall is not evidence.
- **arcpy-free core invariant:** headless logic in `core/` importable with no
  arcpy/arcgis; arcpy work behind the `.pyt`/runtime seams
  (`pragma: no cover`).
- **ADR + agent-decision log** for the batch (two separate records; the log
  never substitutes for the ADR).
- **Cold review before merge** (`pr-reviewer` agent), and **NEVER merge
  without the user's explicit go** — a PR in this program was merged
  prematurely on 2026-07-15 (#235) and needed a corrective follow-up (#236).
  Reviews arrive as PR comments (Codex); poll/wait for them.
- **`AskUserQuestion` picker fails intermittently** (stream aborts, verified
  twice on 2026-07-15). Ask decisions in plain text.

## Suggested sequence

1. Read the four sources above; run the reuse inventory against the shipped
   modules listed here.
2. Draft the architecture-review ADR (Proposed): direction options +
   recommendation per the 6 decisions above, slice map, schema sketch.
3. Plain-text sign-off from the user on the direction.
4. Flip ADR to Accepted; write slice-1 spec; TDD headless parts; `.pyt` seam
   for LOCAL parts; cold review; user-approved merge.

## Unrelated open items (do NOT pick up; recorded so they aren't lost)

- #230 QC half: awaiting a real-file check for a per-analysis run-id column
  in the WMRD export (user's machine needed).
- Slice-2 EDD dialects (mining/epar4/NYSDEC): needs real sample files (user's
  machine).
- 3 stale remote branches (`claude/sleepy-wozniak-qo6o8t`/`-ts261r`/`-r6eu8m`)
  approved for deletion but blocked by the session permission classifier —
  user will handle.
- QA issues needing a real machine: #231, #222, #195, #178, #166.
