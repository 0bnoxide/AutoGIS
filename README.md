# AutoGIS

Automation tools for ArcGIS Pro and ArcGIS Online / Survey123, delivered as a single suite: the **Attachment Harvester** plus the **Environmental Monitoring tools**, folded into **one `autogis` package** — one shared core with three adapters (a `click` CLI, an ArcGIS Pro `.pyt` GUI, and the importable core itself).

## 📊 Feature Implementation Tracker

Current status across the 79-tool environmental monitoring roadmap:

| Status | Count | % | Examples |
|--------|-------|---|----------|
| ✅ **Fully Implemented** | 17 | 22% | Lab EDD Importer, Reconcile Locations, Validate Database, Optimize Callouts, Build Callouts, GW Contours, Export Summary Tables, Publish to AGOL, Build Survey Form, Validate Config, Upgrade Schema |
| 🔨 **Foundation Laid** | 8 | 10% | GW Elevation Event, Analytical Exceedance Event, Parser Profile Drafting, Boring Log Database, RTK Survey, Level Loop Processing |
| ⏳ **Not Started** | ~54 | 68% | Batch Import, Migration, Survey123 Reconciliation, Flow Direction, Plume Boundary, Trend Charts, Cartography suite, Dashboard datamart, Field survey tools, Drone integration, AI-assisted tools |

**Roadmap phases:** Phase 1 (foundation) partially complete · Phase 2 (data intake) in progress · Phase 3 (maps/figures) planned · Phase 4 (field survey/AGOL) pending · Phase 5 (advanced analytics) deferred

See [`docs/ROADMAP_STATUS_2026-06-27.md`](docs/ROADMAP_STATUS_2026-06-27.md) and [`docs/IMPLEMENTATION_ROADMAP_PRIORITIZED.md`](docs/IMPLEMENTATION_ROADMAP_PRIORITIZED.md) for full details.

---

## 🏗️ Architecture

### One Core, Three Adapters

- **Shared substrate:** `autogis.core.common` provides config validation, QA reporting, logging, and run history tracking
- **Two domain modules:** `autogis.core.harvest` (Attachment Harvester) and `autogis.core.envmon` (Environmental Monitoring tools) sit on top
- **Three adapters:** `autogis.adapters.cli` (Click CLI), `autogis.adapters.toolbox.pyt` (ArcGIS Pro GUI), and direct imports all construct and validate the *same* config dataclasses and call the *same* core functions — interfaces never drift

### Design Invariants

- **Import with neither `arcgis` nor `arcpy`.** Both are lazy imports. Importing any `core` module succeeds with neither installed. `arcgis` is the optional `cloud` extra; `arcpy` is detected at runtime (ships with ArcGIS Pro, never a pip dependency)
- **Arcpy-free core** (ADR-0002): All core business logic runs without ArcGIS dependencies. LOCAL tools (2–8) guard at the adapter layer
- **Config as code:** All configuration via dataclasses (ADR-0009); no magic strings or config drift between interfaces

## 🔄 Runtime Matrix & Tool Catalog

Every tool declares a runtime class (`HYBRID`, `CLOUD`, or `LOCAL`), and the suite enforces it. The CLI registers all tools, but only **headless-supported** ones are first-class CLI commands; the rest error clearly when `arcpy` is absent and are `.pyt`-primary.

### Headless-Supported Tools (CLI-first)

| Tool | Module | Runtime | CLI Command | Requires |
|---|---|---|---|---|
| **Attachment Harvester** | `core.harvest` | HYBRID | `autogis harvest` | `arcgis` API; runs cloud or local |
| **1. Inspect Workbook** | `excel_workbook_inspector` | CLOUD | `autogis envmon inspect <.xlsx>` | openpyxl only |
| **9. Parser Profile Draft** | `excel_profile_reader` | CLOUD | `autogis envmon parser-profile <.xlsx>` | openpyxl only |
| **10. Figure Spec Template** | `build_figure_spec` | CLOUD | `autogis envmon figure-spec <out.yaml>` | pure Python |

### ArcGIS Pro-Primary Tools (arcpy-guarded on CLI)

| Tool | Module | Runtime | CLI Status | Primary Interface |
|---|---|---|---|---|
| **2. Import Lab EDD** | `import_edd` | LOCAL | ⛔ guarded | `.pyt` GUI |
| **3. Import to GDB** | `import_to_gdb` | LOCAL | ⛔ guarded | `.pyt` GUI |
| **4. Build Current Event** | `build_current_event` | LOCAL | ⛔ guarded | `.pyt` GUI |
| **5. Build Callouts** | `build_figure_dataset` | LOCAL | ⛔ guarded | `.pyt` GUI |
| **6. GW Contours** | `groundwater_contours` | LOCAL | ⛔ guarded | `.pyt` GUI |
| **7. Export Figures** | `export_figures`, `layout_manager` | LOCAL | ⛔ guarded | `.pyt` GUI |
| **8. Full Pipeline** | orchestrator | LOCAL | ⛔ guarded | `.pyt` GUI |
| **11. Validate Database** | `validate_database` | LOCAL | ⛔ guarded | `.pyt` GUI |
| **Upgrade Schema** | `schema_upgrader` | LOCAL | ⛔ guarded | `.pyt` GUI |

### Admin & Utility Tools (headless)

| Tool | Module | Runtime | CLI Command | Purpose |
|---|---|---|---|---|
| **Validate Config** | `config_validator` | CLOUD | `autogis envmon validate-config` | Config integrity checks |
| **Manage Analyte Dict** | `analyte_dictionary` | CLOUD | `autogis envmon manage-analyte-dict` | Canonical names + units |
| **Validate Units** | `unit_validator` | CLOUD | `autogis envmon validate-units` | Unit registry + conversion |
| **Reconcile Locations** | `location_reconciler` | CLOUD | `autogis envmon reconcile-locations` | Well/location QA |
| **Evaluate RPD QA** | `rpd_evaluator` | CLOUD | `autogis envmon evaluate-rpd-qa` | Duplicate analysis |

## 📦 Installation

### Headless / Cloud Setup
For the Attachment Harvester + headless envmon tools (1, 2, 9, 10):

```bash
pip install autogis[cloud]    # Includes arcgis Python API
autogis harvest --config my-job.yaml
autogis envmon import-edd lab-results.csv
```

### ArcGIS Pro Setup
For the full `.pyt` GUI + LOCAL tools (3–8, 11):

Since `arcpy` ships with Pro and is not pip-installable, install `autogis` editable into a cloned `arcgispro-py3` conda environment:

```bash
# Inside a cloned arcgispro-py3 environment
pip install -e .
```

Then point the ArcGIS Pro toolbox to the cloned environment. See [`docs/pro-install.md`](docs/pro-install.md) for the complete setup guide (cloning, toolbox registration, cache/reload details).

### Development Setup
For contributors:

```bash
pip install -e ".[dev]"     # Installs test dependencies
python -m pytest -q         # Run 362+ unit tests
```

Test baseline: **362 passing tests** covering arcpy-free core + CLI adapters.

## 🖥️ CLI Surface & Commands

The `autogis` CLI exposes the Harvester at the top level and envmon tools under an `envmon` sub-group:

### Harvester Commands

```bash
autogis harvest --config my-job.yaml                 # Download attachments from feature layer
autogis harvest --config my-job.yaml --incremental   # Incremental fetch (changed features only)
autogis harvest --config my-job.yaml --where "Status='Complete'"  # Filter by attribute
```

### Headless Envmon Tools

```bash
# Data validation & inspection
autogis envmon validate-config <env.yaml>            # Config integrity checks
autogis envmon validate-units <samples.csv>          # Unit conversion validation
autogis envmon reconcile-locations <workbook.xlsx>   # Well/location matching
autogis envmon manage-analyte-dict                   # Manage canonical analytes
autogis envmon evaluate-rpd-qa <duplicates.csv>      # Duplicate analysis

# Data import & preparation
autogis envmon inspect <workbook.xlsx>               # Workbook structure report (Tool 1)
autogis envmon parser-profile <workbook.xlsx>        # Parser profile drafter (Tool 9)
autogis envmon figure-spec <output.yaml>             # Figure spec template (Tool 10)

# Analysis & reporting
autogis envmon export-summary <event_db>             # Export summary tables
autogis envmon export-report-format-summary-tables <event_db>  # Formatted report export
autogis envmon evaluate-readiness <event_db>         # Event readiness check
autogis envmon compare-events <event_db>             # Compare monitoring events
autogis envmon process-level-loop <survey.csv>       # Process differential-level data
autogis envmon identify-data-gaps <event_db>         # Identify missing data
autogis envmon build-survey-form <config.yaml>       # Build Survey123 XLSForm

# Publishing
autogis agol publish-layer <config.yaml>             # Publish layers to AGOL
```

### Pro-Guarded Tools (arcpy-required)

These commands error clearly when `arcpy` is unavailable and point users to the `.pyt` GUI inside ArcGIS Pro:

```bash
autogis envmon import-gdb <config.yaml>              # Tool 3 — file-GDB import
autogis envmon build-current-event <config.yaml>     # Tool 4 — rule-based event building
autogis envmon validate-db <geodatabase>             # Tool 11 — database QA (Pro-primary)
autogis envmon import-edd <lab-results.csv>          # Tool 2 — Lab EDD import (Pro-primary)
autogis envmon upgrade-schema <geodatabase>          # Schema migration (Pro-primary)
# ... (additional tools 5–8 follow the same pattern)
```

**Note:** All Pro-guarded tools require `arcpy` (ships with ArcGIS Pro only). When run outside Pro without `arcpy` installed, they provide a clear error message directing users to use the `.pyt` toolbox instead. Use the headless commands above for workflows that must run without Pro.

**Legacy alias:** `autogis-harvest` is preserved as a direct alias for `autogis`.

## 📸 Attachment Harvester

Bulk-download photos/attachments from a feature layer for field-inspection workflows. The Attachment Harvester is a **hybrid** tool — it runs with or without ArcGIS Pro (headless mode via the AGOL API).

### Quick Start

Copy `autogis/config/inspection-job.example.yaml` and edit:

```yaml
connection:
  profile: my-agol-profile    # or leave null for env vars AGOL_USER/AGOL_PASS
layer:
  item_id: "1a2b3c4d5e6f"     # feature layer AGOL ID
  # OR url: "https://services.arcgisonline.com/..."
  where: "1=1"                # optional attribute filter
output:
  directory: "./downloads"
  group_template: "{Status}"  # subfolder per attribute value
  filename_template: "{InspectionID}_{OBJECTID}_{name}"  # must include ID
options:
  incremental: true           # fetch only changed features
```

### Usage

```bash
# Basic harvest
autogis harvest --config my-job.yaml

# With command-line overrides
autogis harvest --config my-job.yaml --where "Status = 'Complete'" --out ./batch --incremental
```

### Output

Each run writes to the output directory:
- Photos/attachments organized by `group_template`
- `manifest.csv` — index of all files
- `manifest.json` — structured download log
- Console output: `Downloaded: X  Skipped: Y  Failed: Z`

Re-running skips files already on disk, so failed downloads retry cleanly.

### Security

Never include passwords in the config file or command line. Instead:
- Store an ArcGIS profile: `arcgis auth login --mode OAUTH2`
- Use environment variables: `AGOL_USER` and `AGOL_PASS`

## 🌍 Environmental Monitoring Tools

A full pipeline to standardize irregular Excel workbooks → normalized GDB → QA reports → cartographic figures → published web maps. All tools maintain **source-cell traceability** and **idempotent imports**.

### Data Flow Diagram

```
Excel/CSV Workbooks
    ↓ [Tools 1, 9]
    ├─ Workbook Inspection (openpyxl)
    ├─ Parser Profile Drafting (openpyxl)
    └─ Lab EDD Import (openpyxl)
    ↓
Config → Validation → Reconciliation
    ├─ Config validation (Tool 10.2)
    ├─ Location reconciliation (Tool 3.2)
    ├─ Unit conversion (Tool 3.5)
    ├─ Analyte dictionary (Tool 3.3)
    └─ RPD/QA evaluation (Tool 3.6)
    ↓
GDB Import [Pro/.pyt]
    ├─ Import tables (Tool 3)
    ├─ Build current event (Tool 4)
    └─ Validate database (Tool 3.1)
    ↓
Analysis & Cartography [Pro/.pyt]
    ├─ GW contours (Tool 4.2)
    ├─ Analytical callouts (Tool 5.1)
    ├─ Optimize placement (Tool 5.2)
    ├─ Export figures (Tool 6)
    └─ Publish to AGOL (Tool 6.1)
```

### Headless Data Prep Pipeline

For headless/cloud workflows, prepare data without Pro:

```bash
# Step 1: Inspect the workbook
autogis envmon inspect raw-monitoring.xlsx > inspection-report.txt

# Step 2: Draft a parser profile (if needed for new workbook format)
autogis envmon parser-profile raw-monitoring.xlsx > parser.yaml

# Step 3: Import lab results
autogis envmon import-edd lab-edd-results.csv --output results.csv

# Step 4: Validate config
autogis envmon validate-config site-config.yaml

# Step 5: Reconcile locations
autogis envmon reconcile-locations raw-monitoring.xlsx

# Step 6: Validate units
autogis envmon validate-units results.csv --profile site-config.yaml
```

### Pro-Based Analysis Pipeline

For mapping and advanced analysis, run inside ArcGIS Pro via the `.pyt` GUI:

- **Import to GDB** (Tool 3) — parse workbook, populate normalized tables
- **Build Current Event** (Tool 4) — apply rule logic (screening, exceedance detection)
- **Generate GW Contours** (Tool 4.2) — DRAFT potentiometric surface (Spatial Analyst)
- **Build Callouts** (Tool 5.1) — analytical features with source-cell links
- **Optimize Callout Placement** (Tool 5.2) — resolve box/leader overlaps (numpy geometry)
- **Export Figures** (Tool 6) — layout PDFs/PNGs with full traceability
- **Publish to AGOL** (Tool 6.1) — feature layers + web maps

### Key Capabilities

✅ **Idempotent imports** — re-run without duplicating data  
✅ **Full traceability** — every cell value links back to source (Excel row/col)  
✅ **QA automation** — RPD, unit mismatch, location reconciliation, screening comparison  
✅ **Arcpy-free core** — validation & import prep run anywhere  
✅ **Schema versioning** — migrate between GDB versions without data loss  
✅ **Headless reporting** — generate snapshots, summaries, and QA reports on CLI

## 📂 Project Structure

```
autogis/
├── core/
│   ├── common/          # Shared: config, QA, logging, run history, schema
│   ├── harvest/         # Attachment Harvester (arcpy-free)
│   └── envmon/          # Environmental monitoring (23 modules)
├── adapters/
│   ├── cli.py           # Click CLI surface
│   ├── toolbox.pyt      # ArcGIS Pro GUI
│   └── toolbox_core.py  # Seam between `.pyt` and core
├── config/
│   ├── inspection-job.example.yaml      # Harvester template
│   ├── parser_profiles/                 # Excel format definitions
│   ├── screening_levels/                # Regulatory thresholds (per state/program)
│   └── figure_specs/                    # Cartography templates
├── runtime/             # ArcGIS session providers + capability guards
└── tests/               # 329+ arcpy-free unit tests (pytest)
```

### Key Files & Modules

| Module | Purpose |
|--------|---------|
| `core/common/config.py` | Config dataclasses (HarvestConfig, EnvConfig) — canonical source |
| `core/common/schema/` | 5 modules (boring, dashboard, drone, envmon, survey) exporting ~29 dataclass types across all domains |
| `core/envmon/` | 36 modules: workbook inspector, EDD importer, validators, reconcilers, event builders, contour/callout generators, analysis tools |
| `adapters/cli.py` | Click CLI: registers all commands, validates config, dispatches to core |
| `runtime/` | arcpy/arcgis guards: `arcpy_available()`, `local_runtime_ok()`, `capability_required()` decorators |
| `tests/` | Unit tests for core modules (no arcpy/arcgis required); run with `pytest -q` |

---

## ⚠️ Known Caveats & Production Readiness

Read before relying on this suite in production:

### 1. **H281 Parser Profile is DRAFT** 🟡
`autogis/config/parser_profiles/H281_Glasgow_DataTables.yaml` was built from written spec only — the real workbook was unavailable. Ships with `DRAFT` banner and `_TODO` markers.

**Before first import:** Use Tool 1 (Inspect Workbook) + human review to validate every row/column anchor against the report. Fix the `_TODO`s, clear the DRAFT banner, then import.

### 2. **Screening Levels Ship Null** 🟡
Files under `autogis/config/screening_levels/` contain placeholder null values and `_TODO` source citations.

**Before production:** Populate with regulatory thresholds from your applicable standards (EPA, state, program). Screening comparison stays tri-state (NULL = not evaluable) until filled.

### 3. **Average Parent & Duplicate QA Warning** 🟡
`average_parent_and_duplicate` is statistically dubious with nondetects but is in the spec. Every averaged value flags a QA WARNING. **Keep the flag** — it signals when QC averaging is used.

### 4. **arcpy Code Paths Are Un-CI-able** 🟡
Tools 3–8 (Pro-based) are not exercised in CI (arcpy/Pro not available in headless tests). 

**Before production:** Run them on a copy of real monitoring data inside Pro. Verify imports, event logic, contours, and figures before trusting outputs.

### 5. **Incremental Harvest Depends on Feature Service Metadata**
The Attachment Harvester's `--incremental` flag relies on the feature service's `GlobalID` and `EditDate` fields. If missing, falls back to full re-download.

---

## 📚 Documentation

- **Installation:** [`docs/pro-install.md`](docs/pro-install.md) — Full Pro setup, environment cloning, toolbox registration
- **Roadmap:** [`docs/ROADMAP_STATUS_2026-06-27.md`](docs/ROADMAP_STATUS_2026-06-27.md) — Feature completion status (22% done, 10% foundation, 68% planned)
- **Prioritized Timeline:** [`docs/IMPLEMENTATION_ROADMAP_PRIORITIZED.md`](docs/IMPLEMENTATION_ROADMAP_PRIORITIZED.md) — Phase 1–4 sequencing (~70 weeks, 4 phases)
- **Architecture Decisions:** [`docs/adr/`](docs/adr/) — ADRs covering core invariants, schema design, config strategy
- **Codebase Memory:** See `.claude/settings.json` — MCP server integration for graph-based exploration

---

## 🤝 Contributing

Test coverage baseline: **329 passing tests**. All core logic is arcpy-free and CI-able.

```bash
# Run tests
python -m pytest -q

# Run with coverage
python -m pytest --cov=autogis --cov-report=term-missing

# Lint & type check
ruff check autogis/
mypy autogis/
```

See `docs/adr/README.md` for architectural guidelines before adding new tools.
