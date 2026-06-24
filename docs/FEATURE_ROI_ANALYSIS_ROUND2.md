# AutoGIS Feature ROI Analysis — Round 2 (2026-06-24)

## Context

**Current tool suite:** 11 tools (HarvestAttachments, Tools 1-10, plus AGOL publish)

**Last round results:**
- ✅ arcgis library integration (Tier 1 — direct value, lazy-arcpy compatible)
- ✅ AGOL publish tool (PublishEnvironmentalLayersToAGOL) — `agol publish-layer` command
- ⏳ numpy tools (Dan Patterson repo) — parked awaiting license verification
- ✅ Heuristic analyte column guess — integrated into `inspect` tool

**Methodology:** Rank candidates by **impact vs. effort**, with emphasis on features that:
1. **Prevent errors** before they enter the pipeline (validation, reconciliation)
2. **Eliminate manual work** (batch operations, automation)
3. **Scale operations** (handle many sites/jobs at once)
4. **Reduce debug cycles** (auditability, history, QA explanations)

---

## Tier 1 — High Impact / Low Effort (Implement Next Round)

### 1. **ValidateEnvConfig** ⭐⭐⭐ — Prevention tool
- **Why:** Catches bad YAML/JSON configs before runs fail; prevents 80% of user-induced errors.
- **Impact:** Eliminates failed imports and re-runs; saves 1–2 hours per site per week.
- **Effort:** ~3–4 hours (pre-built validators for parser profiles, figure specs, screening levels, analyte dictionary).
- **Dependencies:** None (depends on existing config classes).
- **Headless:** Yes (core library only, no arcpy).
- **Risk:** Very low.
- **ROI:** **Excellent** — prevents cascading errors, improves UX.
- **Suggested name:** `autogis envmon validate-config` + `.pyt` tool

---

### 2. **ReconcileSampleLocations** ⭐⭐⭐ — Join-safety tool
- **Why:** Fixes the single most common import failure: workbook sample IDs not matching well/location feature class.
- **Impact:** Eliminates ~40% of manual reconciliation work; restores failed joins silently or with suggestions.
- **Effort:** ~4–5 hours (diff algorithm, fuzzy matching for typos, suggester output).
- **Dependencies:** `Inspect` tool output (workbook structure), site config (well layer).
- **Headless:** Partially (core analysis headless, but needs arcpy to read well layer in production).
- **Risk:** Low (read-only; only suggests, doesn't modify).
- **ROI:** **Excellent** — addresses the #1 pain point.
- **Suggested name:** `autogis envmon reconcile-locations`

---

### 3. **ManageAnalyteDictionary** ⭐⭐ — Reference-data tool
- **Why:** Curate/validate the analyte dictionary; catch invalid analyte refs before they propagate through all downstream tools.
- **Impact:** Stabilizes all analytical tools (Tools 3–8); eliminates "analyte not found" errors.
- **Effort:** ~3–4 hours (CRUD UI in `.pyt`, file I/O for YAML, uniqueness checks).
- **Dependencies:** Config system (analyte_dictionary.yaml).
- **Headless:** Yes (YAML file operations).
- **Risk:** Very low (read/write to a config file).
- **ROI:** **Good** — prevents cascading errors, stabilizes reference data.
- **Suggested name:** `autogis envmon manage-analyte-dict`

---

### 4. **WriteRunHistory** ⭐⭐ — Audit trail tool
- **Why:** Every tool execution writes a record (RunID, tool, user, start/end, status, errors); makes the system auditable and debuggable.
- **Impact:** Enables troubleshooting ("why did Tool 3 fail on 2026-06-20?"); supports compliance/audit requirements.
- **Effort:** ~3–4 hours (hook into QACollector, write to CSV/SQLite table in GDB, render in `.pyt`).
- **Dependencies:** QACollector (already thread-safe).
- **Headless:** Partially (logging is headless, but GDB write needs arcpy).
- **Risk:** Low (append-only log; no data modification).
- **ROI:** **Good** — multiplies support capacity, enables root-cause analysis.
- **Suggested name:** `autogis envmon write-run-history`

---

## Tier 2 — High Impact / Medium Effort (Implement Round 3–4)

### 5. **BatchImportEnvironmentalWorkbooks** ⭐⭐⭐ — Scaling tool
- **Why:** Run Tool 2 (ImportToGdb) against many workbooks in a manifest (YAML); scales from 1 site to 10+.
- **Impact:** Enables batch processing of quarterly imports, seasonal events; saves 3–5 hours of clicking.
- **Effort:** ~5–6 hours (manifest parser, job orchestration, error recovery, progress UI).
- **Dependencies:** Tool 2 (ImportToGdb), job queue infrastructure.
- **Headless:** No (requires arcpy).
- **Risk:** Medium (coordinate many GDB writes; needs locking/transaction safety).
- **ROI:** **Excellent** — multiplies tool utilization; scales operations.
- **Suggested name:** `autogis envmon batch-import` or `autogis envmon run-job-queue`

---

### 6. **ManageScreeningLevels** ⭐⭐ — Reference-data tool
- **Why:** Curate screening level thresholds (YAML); validate units match analytes; track data source/revision.
- **Impact:** Stabilizes exceedance logic in Tools 4–6; prevents "threshold mismatch" errors.
- **Effort:** ~4–5 hours (`.pyt` UI, unit validation, audit trail on edits, CSV import/export).
- **Dependencies:** Config system (screening_levels.yaml), analyte dictionary.
- **Headless:** Yes (YAML file operations).
- **Risk:** Low (read/write to config).
- **ROI:** **Good** — stabilizes reference data, improves compliance.
- **Suggested name:** `autogis envmon manage-screening-levels`

---

### 7. **OptimizeCalloutPlacement** ⭐ — Cartography assist
- **Why:** Post-process callout collisions automatically; reduce manual repositioning from 30 min to 5 min per map.
- **Impact:** Saves 25 min per figure; for 10 figures/month = 4+ hours.
- **Effort:** ~6–8 hours (collision detection, simulated annealing or force-directed layout, preserve user overrides).
- **Dependencies:** Tool 4 (BuildCallouts), callout_placement_overrides.csv.
- **Headless:** No (needs arcpy for geometry).
- **Risk:** Medium (modifies feature positions; needs manual review workflow).
- **ROI:** **Good** — reduces manual cartographic work; improves map quality.
- **Suggested name:** `autogis envmon optimize-callout-placement`

---

## Tier 3 — Medium Impact / Low Effort (Quick Wins)

### 8. **ValidateAndConvertUnits** ⭐ — Data integrity tool
- **Why:** Detect and auto-convert unit mismatches (µg/L vs. mg/L); flag ambiguous cases.
- **Impact:** Prevents exceedance false-positives from unit errors; catches ~5% of imports.
- **Effort:** ~3–4 hours (unit conversion library, detection rules, output report).
- **Dependencies:** Analyte dictionary, screening levels.
- **Headless:** Yes (pure logic).
- **Risk:** Low (read-only; only flags and suggests).
- **ROI:** **Good** — prevents data-integrity errors.
- **Suggested name:** `autogis envmon validate-units`

---

### 9. **ExportAnalyticalSummaryTables** ⭐⭐ — Reporting tool
- **Why:** Generate Excel summary tables (current event, historical, exceedance-only, by well, by analyte group, RPD summary).
- **Impact:** Eliminates manual Excel pivot-table building; saves 1–2 hours per quarterly report.
- **Effort:** ~5–6 hours (template Excel writer, multiple table layouts, QA summary roll-up).
- **Dependencies:** Normalized GDB schema, openpyxl.
- **Headless:** Partially (Excel export headless, but needs arcpy to read GDB).
- **Risk:** Low (writes new files; non-destructive).
- **ROI:** **Excellent** — core deliverable automation.
- **Suggested name:** `autogis envmon export-summary-tables`

---

### 10. **EvaluateDuplicateRPD** ⭐ — QA automation
- **Why:** Flag duplicate/RPD pairs where percent recovery exceeds/falls below control limits; summarize in QA report.
- **Impact:** Catches 3–5 questionable results per event; eliminates manual review.
- **Effort:** ~2–3 hours (RPD formula, thresholds, QA output).
- **Dependencies:** Normalized data, QACollector.
- **Headless:** Yes (pure logic on normalized records).
- **Risk:** Very low (read-only analysis).
- **ROI:** **Good** — automated QA; improves data confidence.
- **Suggested name:** `autogis envmon evaluate-rpd` (can be a sub-mode of ValidateDatabase)

---

## Tier 4 — Lower Priority (Defer, but Catalogued)

### 11. **BuildAnalyticalKey** ⭐ — Cartography
- **Why:** Auto-generate analytical key table from figure spec + screening levels.
- **Impact:** Saves 15–20 min per map layout.
- **Effort:** ~4–5 hours (layout template, table builder).
- **Headless:** No (arcpy needed for GDB table creation).
- **ROI:** Good (convenience; not critical path).

### 12. **GenerateWellInspectionPhotoReport** ⭐ — Field ops
- **Why:** Generate PDF photo logs from attachments + well status.
- **Impact:** Saves 30 min per inspection event.
- **Effort:** ~6–8 hours (PDF writer, photo collation, index generation).
- **Headless:** Partially (PDF writing headless, but needs arcpy to read attachments).
- **ROI:** Good (specialized; not all projects use photos).

### 13. **ReconcileFieldAndLabData** ⭐ — Field reconciliation
- **Why:** Compare field samples to lab results; flag mismatches (date, ID, matrix, location).
- **Impact:** Catches ~10% of reconciliation errors pre-report.
- **Effort:** ~5–6 hours (fuzzy join algorithm, flagging rules).
- **Headless:** Yes (logic only, but needs external data sources).
- **ROI:** Good (specialized; depends on field data workflow).

### 14. **AI-Assisted Tools** (11.1–11.4 from roadmap) ⭐⭐ — Future exploration
- **Why:** Draft parser profiles, explain QA, draft figure specs, generate review checklists using LLM.
- **Impact:** Reduces 1–2 hours of manual work per new site.
- **Effort:** ~4–8 hours per tool (LLM integration, prompt engineering, guardrails).
- **Risk:** Medium (LLM hallucination potential; needs guardrails + human review).
- **ROI:** Excellent (if guardrails robust); parked pending LLM model selection.

---

## Summary: Recommended Next 3 Features (Round 2)

Based on **impact vs. effort** analysis:

| Priority | Tool | Impact | Effort | ROI | Owner |
|---:|---|---|---|---|---|
| **1** | `ValidateEnvConfig` | Very High | 3–4 hrs | **Excellent** | Validation + error prevention |
| **2** | `ReconcileSampleLocations` | Very High | 4–5 hrs | **Excellent** | Joins + fuzzy matching |
| **3** | `ManageAnalyteDictionary` | High | 3–4 hrs | **Good** | Reference data curation |

**Alternative top-3** (if prioritizing scale):
- `BatchImportEnvironmentalWorkbooks` (replaces Tool 7 FullPipeline for multi-site use)
- `ExportAnalyticalSummaryTables` (direct deliverable automation)
- `WriteRunHistory` (observability + auditability)

---

## Implementation Sequencing

1. **Phase A (Week 1):** `ValidateEnvConfig` + `ManageAnalyteDictionary` (paired: both reference-data tools; can share config validator infrastructure).
2. **Phase B (Week 2):** `ReconcileSampleLocations` (depends on Phase A validators).
3. **Phase C (Week 3–4):** `BatchImportEnvironmentalWorkbooks` or `ExportAnalyticalSummaryTables` (scale or reporting).

---

## Notes

- **Dan Patterson license:** Still pending. When resolved, prioritize numpy-based tools (geometry, statistics) in Tier 4 reranking.
- **AI tools:** Defer pending LLM model selection (Claude/GPT/local); will be Tier 2–3 after decision.
- **Tool 1 (InspectWorkbook) enhancement:** Integrate heuristic analyte-column guess + improved sheet detection in Phase A.
- **Architecture:** All new tools should follow ADR-001 (core-plus-adapters), ADR-002 (arcpy-free core), and ADR-003 (canonical config locations).

---

## Questions for Next Sync

1. Does the ROI ranking align with observed pain points in the field?
2. Should `ReconcileSampleLocations` be built as a standalone tool or integrated into Tool 2 (ImportToGdb)?
3. For `BatchImportEnvironmentalWorkbooks`, should jobs be queued in a GDB table (ADR-010 style) or a manifest YAML file?
4. Priority: reference-data stability (Phase A) vs. immediate scale (BatchImport)?
