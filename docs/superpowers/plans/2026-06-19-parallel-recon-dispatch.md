# Pre-Merge Parallel Recon Dispatch — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run one parallel wave of 6 read-only recon agents that verify MERGE_PLAN's ground-truth claims, consolidate their findings into a deltas doc, and hand verified ground truth to the build plan.

**Architecture:** Orchestrator (main session) dispatches R1–R6 as read-only `Explore`/`general-purpose` subagents in a single message (true parallel). No git worktrees — agents write nothing. Each returns a fixed-format report; orchestrator consolidates, adjudicates contradictions, surfaces a needs-human queue, then commits a deltas doc.

**Tech Stack:** Claude Code subagents (Explore / general-purpose), git, markdown. Target codebase under audit: `staging/envmon-incoming/` + `autogis/`.

**Source spec:** `docs/superpowers/specs/2026-06-19-parallel-recon-dispatch-design.md`

## Global Constraints

- Recon agents are **READ-ONLY**. Any write/edit attempt is a brief violation → discard that agent's output and re-run.
- All 6 agents dispatched in **one message** (parallel). No worktrees.
- Every agent returns the fixed report format: `CLAIM / VERDICT (confirmed|corrected|needs-human) / EVIDENCE (file:line) / DELTA / RISK`.
- The wave runs **once, before MERGE_PLAN step 1**, and blocks the builder.
- No agents run alongside the build spine (avoids shared-state race on the live branch).
- Deltas doc path: `docs/superpowers/specs/2026-06-19-mergeplan-deltas.md`.

---

## File Structure

- `docs/superpowers/specs/2026-06-19-mergeplan-deltas.md` — **Create.** The consolidated verification artifact. Sole writable output of this plan.
- `staging/envmon-incoming/src/*.py` (23 modules) — read-only audit targets (R1, R2, R4, R5, R6).
- `staging/envmon-incoming/toolbox/EnvironmentalMonitoringTools.pyt` — read-only audit target (R2).
- `staging/envmon-incoming/tests/` — read-only audit target (R3).
- `autogis/core/models.py`, `autogis/core/manifest.py` — read-only audit targets (R4 `HarvestConfig`/`RunSummary`, R5 `Manifest`).

---

### Task 1: Dispatch the recon wave (R1–R6, parallel)

**Files:**
- Create: none (read-only agents)
- Audit targets: as listed in File Structure

**Interfaces:**
- Consumes: the MERGE_PLAN claims listed per-stream below.
- Produces: 6 agent reports in the fixed `CLAIM/VERDICT/EVIDENCE/DELTA/RISK` format, held in the orchestrator's context for Task 2.

- [ ] **Step 1: Dispatch all 6 agents in a single message**

Use the Agent tool 6 times in ONE message. Subagent type `Explore` for R1/R2/R3/R6 (search-heavy), `general-purpose` for R4/R5 (cross-file API reconciliation). Each prompt ends with the report-format instruction below.

**Shared suffix appended to every agent prompt:**
```
You are READ-ONLY. Do not edit, write, or create any file. Return findings ONLY in this exact format, one block per claim:

CLAIM:    <the MERGE_PLAN assertion checked>
VERDICT:  confirmed | corrected | needs-human
EVIDENCE: <file:line references>
DELTA:    <what MERGE_PLAN gets wrong, if anything; "none" if confirmed>
RISK:     <what breaks in the merge build if left unaddressed; "none" if confirmed>
```

**R1 — arcpy-boundary audit (Explore):**
```
Audit staging/envmon-incoming/src/ (23 .py modules). For EACH module, grep for "arcpy" and classify it as: (a) arcpy-free (no reference), (b) arcpy at module top-level import, or (c) arcpy lazily imported inside a function/method. Verify MERGE_PLAN's claim that exactly 14 of 23 are arcpy-free and names them: result_parser, table_normalizer, the 5 normalize_* modules, callout_geometry, callout_collision, callout_templates, excel_workbook_inspector, excel_profile_reader, envmon_config, qa_checks. Also confirm the arcpy-edge set: import_to_gdb, build_figure_dataset, groundwater_contours, layout_manager, export_figures, gdb_schema, validate_database, build_current_event. For each arcpy-edge module, state whether arcpy is top-level (would break import without arcpy) or lazy-inside-function. Final claim to settle: "importing any core module succeeds with neither arcgis nor arcpy installed."
```

**R2 — import-graph map (Explore):**
```
Map the import graph of staging/envmon-incoming/src/ (23 modules) plus staging/envmon-incoming/toolbox/EnvironmentalMonitoringTools.pyt. Extract every `from <module> import ...` and `import <module>` statement that references a SIBLING src module (the flat, non-namespaced imports — e.g. `from qa_checks import ...`). Output: (1) an adjacency list module -> [modules it imports], (2) a topological ordering safe for rewriting these to relative imports under autogis/core/envmon/, (3) the exact sys.path.insert hack line(s) in the .pyt that must be deleted, (4) any circular imports. This drives MERGE_PLAN step 4's relative-import rewrite.
```

**R3 — test inventory (Explore):**
```
Inventory staging/envmon-incoming/tests/. List every test module, the conftest.py, and any fixtures (esp. the synthetic workbook). For EACH test function, tag it arcpy-dependent (imports/exercises an arcpy path) or pure-python (CI-able without Pro). Produce a total count and verify MERGE_PLAN's "56 tests" figure. Output which tests can run in CI vs which must be exercised manually in ArcGIS Pro. This drives MERGE_PLAN step 4's test port + the CI gate.
```

**R4 — config reconcile (general-purpose):**
```
Compare two config systems. (A) Harness: autogis/core/models.py HarvestConfig (flat dataclass) + autogis/adapters/config_loader.py load_config(path, overrides) -> (HarvestConfig, profile), YAML-only. (B) Envmon: staging/envmon-incoming/src/envmon_config.py — typed dataclasses SiteConfig/ParserProfile/FigureSpec each with a .load(path) classmethod, ConfigError, load_config(path) -> dict, load_analyte_dictionary, load_screening_levels, YAML-or-JSON. Enumerate every field of each. Verify MERGE_PLAN §3.1's recommendation to adopt the envmon convention and re-express HarvestConfig in it. Output the proposed unified field set for core/common/config.py and any HarvestConfig field that has no clean home in the typed style.
```

**R5 — reporting reconcile (general-purpose):**
```
Compare two reporting systems. (A) Harness: autogis/core/models.py RunSummary (downloaded/skipped/failed counters) + autogis/core/manifest.py Manifest (CSV+JSON from AttachmentResult). (B) Envmon: staging/envmon-incoming/src/qa_checks.py QACollector/QARecord (severity, category, message, source-cell provenance, write_csv/write_json/write_markdown, as_gdb_row) + src/logging_utils.py _ArcpyHandler. Tasks: (1) map both API surfaces, (2) identify every RunSummary/Manifest method that is NOT thread-safe (called from worker threads in a future parallel-download feature), (3) list the provenance fields HARVESTER_ENHANCEMENTS says to RESERVE now: checksum (+algorithm), geometry (WKT/GeoJSON), source_table/relationship_id — confirm none exist yet on AttachmentResult/Manifest. Verify MERGE_PLAN §3.2 (standardize on QACollector + logging mirror, fold counters in as a summary view).
```

**R6 — caveat audit (Explore):**
```
Locate in the staging/envmon-incoming/ source the 4 carried-over caveats from MERGE_PLAN §1 and confirm each is still present and how it is guarded: (1) the H281 parser profile is a DRAFT never verified against the real workbook — find the profile under config/parser_profiles/ and any code/comment marking it draft; (2) arcpy code paths untested outside Pro; (3) average_parent_and_duplicate is statistically dubious with nondetects and must emit a QA WARNING — find the function and confirm the WARNING is emitted; (4) the screening-levels file ships all-null with _TODO citations — find it under config/screening_levels/ and confirm. For each, RISK = what regresses if the merge silently drops the guard.
```

- [ ] **Step 2: Verify all 6 returned in format**

Confirm 6 reports received, each using the `CLAIM/VERDICT/EVIDENCE/DELTA/RISK` blocks. For any agent that returned thin, empty, or off-format output, re-dispatch ONLY that one stream (not the whole wave). Do not proceed until all 6 are valid.

---

### Task 2: Consolidate into the deltas doc

**Files:**
- Create: `docs/superpowers/specs/2026-06-19-mergeplan-deltas.md`

**Interfaces:**
- Consumes: the 6 validated reports from Task 1.
- Produces: a committed deltas doc with a claim→verdict→delta table, a Corrections list, a needs-human queue, and the R2 import-graph/topo block.

- [ ] **Step 1: Write the deltas doc**

Create `docs/superpowers/specs/2026-06-19-mergeplan-deltas.md` with these sections:
- **Verdict table:** one row per claim — `stream | claim | verdict | delta`.
- **Corrections to MERGE_PLAN:** only the `corrected` verdicts whose DELTA changes a build instruction. Each with file:line evidence.
- **needs-human queue:** every `needs-human` verdict, phrased as a decision the user must make.
- **Import graph + topo order:** paste R2's adjacency list + topological ordering + the sys.path lines to delete, verbatim.
- **Reserved-schema note:** R5's confirmed list of provenance fields to reserve in core/common.

- [ ] **Step 2: Verify the doc has no empty sections**

Read the doc back. Confirm every section is populated (a section with no entries must say "none" explicitly, not be blank). Confirm every `corrected`/`needs-human` row carries file:line evidence.

---

### Task 3: Adjudicate contradictions and gate needs-human

**Files:**
- Modify: `docs/superpowers/specs/2026-06-19-mergeplan-deltas.md`

**Interfaces:**
- Consumes: the deltas doc from Task 2.
- Produces: an adjudicated deltas doc; a needs-human queue surfaced to the user and cleared or acknowledged.

- [ ] **Step 1: Resolve any contradictions**

If two streams disagree on an overlapping claim (e.g. R1 and R2 classify a module's arcpy dependency differently), the orchestrator reads the cited files directly, decides, and records the resolution inline in the deltas doc with the deciding evidence.

- [ ] **Step 2: Surface the needs-human queue to the user**

Present the needs-human queue (esp. the H281 draft-profile verification, item R6.1) to the user. The builder must NOT proceed past any unbacked R6 caveat-regression risk. Wait for the user to clear or explicitly acknowledge each item; record their decision in the doc.

---

### Task 4: Commit and hand off to the build plan

**Files:**
- Modify: `docs/superpowers/specs/2026-06-19-mergeplan-deltas.md` (final state)

**Interfaces:**
- Consumes: the adjudicated, user-acknowledged deltas doc.
- Produces: a committed deltas doc; a hand-off to the writing-plans skill for the MERGE_PLAN step-1→6 build plan.

- [ ] **Step 1: Commit the deltas doc**

```bash
git add docs/superpowers/specs/2026-06-19-mergeplan-deltas.md
git commit -m "docs: add verified MERGE_PLAN deltas from recon wave"
```
Expected: one file changed, commit created on `main`.

- [ ] **Step 2: Hand off**

Invoke the writing-plans skill to produce the MERGE_PLAN step-1→6 build plan, now grounded in the verified deltas doc rather than the unverified MERGE_PLAN summary. Feed the Corrections list and reserved-schema note into that plan's Global Constraints.

---

## Self-Review

**Spec coverage:** Every spec section maps to a task — §2 architecture + §3 streams → Task 1; §4 consolidation → Task 2; §6 failure handling → Task 1 Step 2 (thin result) + Task 3 (contradiction/needs-human); §5 sequencing + §7 done criteria → Task 4. Read-only rule → Global Constraints. Covered.

**Placeholder scan:** Agent briefs are written in full; no "TBD"/"similar to". Deltas-doc sections enumerated. No placeholders.

**Type consistency:** The report format `CLAIM/VERDICT/EVIDENCE/DELTA/RISK` is identical everywhere it appears. Stream IDs R1–R6 are consistent across plan, briefs, and deltas-doc sections. Deltas doc path identical in Global Constraints, Task 2, Task 3, Task 4.
