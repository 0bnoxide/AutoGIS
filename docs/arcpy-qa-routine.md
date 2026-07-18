# ArcPy functional-QA routine

Use this routine for the open ArcGIS Pro gates in issues
[#178](https://github.com/0bnoxide/AutoGIS/issues/178),
[#222](https://github.com/0bnoxide/AutoGIS/issues/222),
[#231](https://github.com/0bnoxide/AutoGIS/issues/231), and
[#238](https://github.com/0bnoxide/AutoGIS/issues/238). It also covers the
live CAD/TIN smoke pass left by PR
[#251](https://github.com/0bnoxide/AutoGIS/pull/251).

This inventory is current as of 2026-07-17. Open issue #195 is a headless GUI
workflow check and #244 is arcpy-free QC key logic, so neither belongs in this
pass. See [the ArcPy environment guide](arcpy-environment.md) before first use.

Run the sections in order. One prepared Pro project supplies the inputs for
all four issues, and the successful `.pyt` import run doubles as the run-history
proof for #231. The normal pytest suite remains in the arcpy-free dev
environment; this is a separate functional pass.

## Inputs

Use disposable copies, never the only copy of project data.

- An `.aprx` with an active map, a projected map CRS, two selected feature
  layers, and a small TIN with a defined horizontal and vertical coordinate
  system.
- A disposable file GDB plus one known-good environmental workbook, matching
  site config, parser profile, analyte dictionary, and screening-level file.
- A CAD mapping file covering the two selected feature layers.
- An OpenTopography API key in `OPENTOPOGRAPHY_API_KEY`.
- A DWG/DXF viewer and Civil 3D (or another LandXML TIN consumer) for the two
  format checks that ArcPy alone cannot prove.

## 1. Pin the checkout and preflight the Pro license

From the checkout being qualified, run in PowerShell:

```powershell
$QaRepo = (Resolve-Path .).Path
$QaProPython = Join-Path $env:LOCALAPPDATA 'ESRI\conda\envs\arcgispro-py3-autogis\python.exe'
$QaEvidence = Join-Path $env:TEMP ("autogis-arcpy-qa-{0}" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $QaEvidence | Out-Null
$env:PYTHONPATH = $QaRepo
$env:AUTOGIS_RUN_HISTORY = Join-Path $QaEvidence 'run_history.csv'

git rev-parse HEAD | Tee-Object (Join-Path $QaEvidence 'commit.txt')
"Windows identity: $([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)" |
    Tee-Object (Join-Path $QaEvidence 'environment.txt')
& $QaProPython -c "import arcpy, autogis; print(arcpy.GetInstallInfo()['Version']); print(arcpy.ProductInfo()); print(autogis.__file__)" |
    Tee-Object -Append (Join-Path $QaEvidence 'environment.txt')
& $QaProPython -m autogis --help |
    Tee-Object (Join-Path $QaEvidence 'module-help.txt')
```

Pass only when:

- ArcPy reports ArcGIS Pro 3.5 or newer and an initialized product license.
- `autogis.__file__` is inside `$QaRepo`, proving `PYTHONPATH` selected this
  checkout rather than the editable install elsewhere.
- `python -m autogis --help` exits 0. This is the PR #252 prerequisite.

If ArcPy raises `RuntimeError: The Product License has not been initialized`,
open ArcGIS Pro, sign in/authorize the license, confirm Pro itself opens a
project, and repeat this section. Do not interpret that error as an AutoGIS
test failure.

Agent sandboxes may run under an isolated Windows identity such as
`CodexSandboxOffline`, which cannot read the interactive user's ArcGIS
credential vault or offline entitlement. If Pro works interactively but this
preflight fails under a different identity, rerun the read-only check through
an approved unsandboxed command or an interactive PowerShell session. Never
copy portal tokens or passwords into the sandbox.

## 2. GUI LOCAL execution (#178)

Launch the GUI from the qualified checkout:

```powershell
python -m autogis.adapters.gui.app
```

Perform this matrix and save one screenshot per row:

| Check | Expected result |
|---|---|
| Blank `local_python`; select `envmon validate-db` | Run disabled with the arcgispro-py3 hint |
| Set `local_python` to `$QaProPython` | Run enables for `validate-db` |
| Restart the GUI | The selected interpreter persists |
| Select `envmon import-gdb` | Run remains disabled with the `.pyt` reason |
| Select a headless tool such as `envmon list-tools` | Run remains enabled |
| Run `validate-db` against the disposable GDB | The command executes under real ArcPy; it does not print a `.pyt` redirect; status and QA rows populate |
| Clear `local_python` | LOCAL tools return to the gated state |

Pass #178 only if all seven rows pass. Record any command that redirects after
the local interpreter is set; that indicates a reachability classification
bug, not a license failure.

## 3. `.pyt` run history (#231)

Close all ArcGIS Pro processes first so the new process inherits
`AUTOGIS_RUN_HISTORY`. Switch Pro to `arcgispro-py3-autogis`, then launch the
test project from the same PowerShell session:

```powershell
$QaAprx = '<PATH_TO_DISPOSABLE_APRX>'
Start-Process 'C:\Program Files\ArcGIS\Pro\bin\ArcGISPro.exe' -ArgumentList $QaAprx
```

Add `autogis\adapters\toolbox.pyt` from `$QaRepo`, and run **2. Import
Environmental Workbook** in `validate_only` mode with the known-good workbook.
This exercises a redirect-only tool without altering the GDB.

Confirm `$env:AUTOGIS_RUN_HISTORY` contains one `import-gdb` record with the
expected site ID and `status=success`, then run:

```powershell
& $QaProPython -m autogis envmon evaluate-readiness `
    --site-id <SITE_ID> `
    --run-history $env:AUTOGIS_RUN_HISTORY `
    --required-tool import-gdb `
    --report (Join-Path $QaEvidence 'readiness.md')
```

Pass #231 only if the record lands at the explicit path and readiness does not
emit `required_tool_not_run`.

## 4. OpenTopography `.pyt` matrix (#222)

Run **Download OpenTopography DEM** in the same Pro project. Use a very small
AOI to avoid unnecessary API traffic.

| Case | Expected evidence |
|---|---|
| Active map extent | GeoTIFF and provenance JSON; request bbox matches the WGS84-projected view extent |
| Feature layer with a selection | Selected-feature extent is used |
| Same layer with selection cleared | Whole-layer extent is used |
| Manual `W S E N` bbox | Values pass through unchanged |
| Output path entered without a suffix | `.tif` is appended; the sidecar is `<name>.tif.json`; no Esri Grid naming error |
| Add to map on | Downloaded raster appears in the active map |
| Reproject on | `_epsg<code>.tif` is produced with BILINEAR resampling and that raster is added |
| Elevation conversion on | Final raster name records the selected direction (`_m_to_intft`, `_m_to_usft`, `_intft_to_m`, or `_usft_to_m`) and that raster is added |
| Map view active | View zooms to the added layer and the message says so |
| Layout view active | No false “zoomed” claim |
| Missing/invalid key, empty AOI, oversized bbox | Readable error; no `.part`, partial `.tif`, or orphaned projected raster |

Save the tool messages and output directory listing in `$QaEvidence`. Pass
#222 only when all rows pass; delete the downloaded test rasters afterward.
Elevation conversion uses the documented `Times` raster operation with exact
unit factors and requires an available Spatial Analyst, Image Analyst, or 3D
Analyst license only when its checkbox is enabled. It changes cell values, not
vertical coordinate system metadata; verify that metadata before downstream
elevation analysis.

## 5. CAD package and TIN LandXML (#238 / PR #251)

### CAD package

Run **8.9 Build CAD Export Package** with both selected feature layers.

1. Export once as `DWG_R2018` and once as `DXF_R2018` into a clean directory.
2. Confirm both files open and contain both input geometries.
3. Confirm actual CAD layer name, color, and linetype match the mapping file.
4. Confirm `projection_note.txt` and `mapping_report.csv` match the requested
   EPSG code and mappings.
5. Confirm the source feature classes gained no CAD fields and no staged
   datasets remain in `arcpy.env.scratchGDB`.
6. Set a deliberately conflicting Output Coordinate System environment and
   repeat. Coordinates and the projection note must still reflect the
   validated source EPSG because the tool pins that environment for export.
7. Put `<output-stem>.prj` in the output directory and repeat. The tool must
   block before export and leave no partial CAD file.
8. Repeat with one unmapped layer, a non-EPSG CRS, and a mismatched layer CRS.
   Each must block before `ExportCAD` and leave no partial output.

### TIN LandXML

Run **8.2 Export Civil 3D TIN LandXML** against the prepared TIN.

1. Confirm 3D Analyst is available and the tool writes a named LandXML 1.2
   surface with points and faces.
2. Import it into Civil 3D using full import. Confirm the surface name,
   horizontal/vertical units, coordinate location, and triangle count.
3. Confirm no temporary triangle feature class remains in the scratch GDB and
   the 3D Analyst extension is checked back in.
4. Repeat with a mismatched EPSG, mismatched unit, mismatched or positive-down
   defined VCS, and unavailable 3D Analyst. Each must fail cleanly with no
   output or leaked extension checkout. An undefined VCS is allowed; verify
   its z-values really use the selected LandXML unit before accepting it.

The headless CgPoints `export-civil3d --landxml` check in #238 does not require
ArcPy and is intentionally outside this routine.

## 6. Evidence and closure

Keep these together in `$QaEvidence`:

- commit and environment preflight;
- screenshots/tool messages for every matrix row;
- `run_history.csv` and `readiness.md`;
- output directory listings and mapping/projection sidecars;
- CAD viewer screenshots; and
- Civil 3D import summary/screenshots.

Post the relevant subset to each issue. Close an issue only when every row in
its section passes. If a row fails, include the exact input, Pro version,
message, and artifact path; do not close the issue on a partial pass.
