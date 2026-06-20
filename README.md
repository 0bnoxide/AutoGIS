# AutoGIS

Automation tools for ArcGIS Pro and ArcGIS Online / Survey123, delivered as a
single suite: the Attachment Harvester plus the Environmental Monitoring tools,
folded into **one `autogis` package** — one shared core with three adapters
(a `click` CLI, an ArcGIS Pro `.pyt` GUI, and the importable core itself).

- **One core, three adapters.** `autogis.core.common` is the shared substrate
  (config, QA, reporting, logging); `autogis.core.harvest` and
  `autogis.core.envmon` sit on top of it. Adapters are dumb marshallers:
  `autogis.adapters.cli` (CLI) and `autogis.adapters.toolbox.pyt` (Pro GUI)
  both construct and validate the *same* config dataclasses and call the *same*
  core functions, so the two interfaces can never drift.
- **Import with neither `arcgis` nor `arcpy`.** Both are lazy. Importing any
  `core` module succeeds with neither installed. `arcgis` is the `cloud` extra;
  `arcpy` is detected at runtime (it ships with ArcGIS Pro and is never a pip
  dependency).

## Runtime matrix

Every tool declares a runtime class, and the suite enforces it. The CLI
registers all 11 tools, but only the **headless-supported** ones are first-class
on the command line; the rest are registered but runtime-guarded — they error
clearly when `arcpy` is absent, and the `.pyt` GUI inside Pro is their primary
interface.

| Tool | Module / source | Runtime | Headless (CLI) | Notes |
|---|---|---|---|---|
| Attachment Harvester | `core.harvest` | **HYBRID** | yes (`autogis harvest`) | `arcgis` API; runs cloud or local |
| 1. Inspect Workbook | `excel_workbook_inspector` | **CLOUD** | yes (`autogis envmon inspect`) | openpyxl only, no arcpy |
| 2. Import to GDB | `import_to_gdb` | **LOCAL** | guarded | file-GDB cursors (arcpy); `.pyt`-primary |
| 3. Build Current Event | `build_current_event` | **LOCAL** | guarded | rule logic pure, GDB I/O is arcpy; `.pyt`-primary |
| 4. Build Callouts | `build_figure_dataset` | **LOCAL** | guarded | geometry inserts (arcpy); `.pyt`-primary |
| 5. GW Contours | `groundwater_contours` | **LOCAL** | guarded | 3D / Spatial Analyst; `.pyt`-primary |
| 6. Export Figures | `export_figures`, `layout_manager` | **LOCAL** | guarded | `arcpy.mp` layouts / PDF; `.pyt`-primary |
| 7. Full Pipeline | orchestrator | **LOCAL** | guarded | chains local stages; `.pyt`-primary |
| 8. Validate Database | `validate_database` | **LOCAL** | guarded | GDB cursors (arcpy); `.pyt`-primary |
| 9. Parser Profile Draft | `excel_workbook_inspector` | **CLOUD** | yes (`autogis envmon parser-profile`) | openpyxl only |
| 10. Figure Spec Template | inline | **CLOUD** | yes (`autogis envmon figure-spec`) | pure-python file write |

Headless-supported (run on the CLI without ArcGIS Pro): the **Harvester** plus
tools **1, 9, 10**. Tools **2–8** are `arcpy`-guarded and are `.pyt`-primary —
the runtime guard refuses them on the CLI when `arcpy` is absent, with a clear
message pointing at the Pro toolbox.

## Install

**Cloud / headless (Harvester + tools 1/9/10):**

```bash
pip install autogis[cloud]      # installs the arcgis Python API
```

**ArcGIS Pro (the LOCAL tools 2–8, plus the .pyt GUI):**

`arcpy` ships with Pro and is not pip-installable. Install `autogis` editable
into a *cloned* `arcgispro-py3` conda environment so the toolbox imports the
package like any library:

```bash
pip install -e .                # inside a cloned arcgispro-py3 env
```

See [`docs/pro-install.md`](docs/pro-install.md) for the full Pro setup (cloning
the env, adding the `.pyt`, and the toolbox cache/reload gotcha).

**Development:**

```bash
pip install -e ".[dev]"
pytest -v
```

## CLI surface

The `autogis` group exposes the harvester directly and the envmon tools under an
`envmon` sub-group:

```bash
autogis harvest --config my-job.yaml          # the Attachment Harvester
autogis envmon inspect <workbook.xlsx>         # tool 1  (headless)
autogis envmon parser-profile <workbook.xlsx>  # tool 9  (headless)
autogis envmon figure-spec <out.yaml>          # tool 10 (headless)
autogis envmon import-gdb …                     # tools 2–8: registered but
                                                #   arcpy-guarded (run in Pro)
```

(`autogis-harvest` is preserved as a legacy alias for `autogis`.)

### Attachment Harvester

Bulk-download photos/attachments from a feature layer for field-inspection
workflows. Copy `autogis/config/inspection-job.example.yaml` and edit it. Key
fields:

- `connection.profile` — stored ArcGIS profile name (or leave null to use env
  vars `AGOL_USER` / `AGOL_PASS`)
- `layer.item_id` or `layer.url` — the feature layer to harvest (one or the
  other, validated on the config dataclass)
- `layer.where` — optional attribute filter (default `1=1`)
- `output.directory` — where files land
- `output.group_template` — subfolder per attribute, e.g. `{Status}`
- `output.filename_template` — must include a feature id, e.g.
  `{InspectionID}_{OBJECTID}_{name}`
- `options.incremental` — only fetch features edited since the last run

```bash
autogis harvest --config my-job.yaml
# overrides:
autogis harvest --config my-job.yaml --where "Status = 'Complete'" --out ./batch --incremental
```

Each run writes the photos plus `manifest.csv` and `manifest.json` into the
output directory, and prints `Downloaded: X  Skipped: Y  Failed: Z`. Re-running
skips files already on disk, so failed downloads are retried cleanly.

Never put passwords in the config file or on the command line — use a stored
ArcGIS profile or the `AGOL_USER` / `AGOL_PASS` environment variables.

### Environmental Monitoring tools

Convert irregular environmental-monitoring Excel workbooks into a normalized
file geodatabase, QA reports, analytical callout feature classes, groundwater
labels, DRAFT potentiometric contours, and exported PDF/PNG figures — with full
source-cell traceability and idempotent imports. Tools 1/9/10 run headless; the
rest run inside ArcGIS Pro via the `.pyt` toolbox.

## Carried caveats (read before relying on this)

These predate the merge and are **not regressed** by it — they remain true:

- **The H281 parser profile is an unverified DRAFT.**
  `autogis/config/parser_profiles/H281_Glasgow_DataTables.yaml` was built from
  the written spec only; the real workbook was not available. It ships with a
  DRAFT banner and `_TODO`s. **Tool 1 + human review is mandatory before the
  first import** — compare every row/column anchor against the Tool 1 report,
  fix the `_TODO`s, and clear the DRAFT banner before importing real data.
- **Screening levels ship all-null.** Files under
  `autogis/config/screening_levels/` ship with null values and `_TODO` source
  citations. **Populate them before production** — no regulatory number is
  invented in code; screening comparison stays tri-state (NULL = not evaluable)
  until the levels are filled in.
- `average_parent_and_duplicate` is statistically dubious with nondetects and
  exists only because the spec demands it; it flags every averaged value with a
  QA WARNING. Keep the flag.
- arcpy code paths (tools 2–8) are **un-CI-able** — they are not exercised
  outside Pro. Run them on a copy of real data inside Pro before trusting
  outputs.
