# Live-Pro QA — Batch A: geostat EBK/GA acceptance run

The one remaining leg of the Phase-5 geostat gate (ADR-0085/0086): run the
shipped geostat LOCAL tools once in real ArcGIS Pro against synthetic data
with **known ground truth**, and check the output against the math.

Budget: **~45–60 min in one Pro session.** Everything is pre-staged; each step
is copy-paste. Synthetic data lives on the Desktop (never in the repo):
`C:\Users\ichbi\Desktop\AutoGIS-QA\geostat\` — regenerate identically any time
with step 1.

## QA batch map (which session covers what)

| Batch | Session type | Covers | Issues |
|---|---|---|---|
| **A (this doc)** | Pro conda console + Pro UI | geostat pipeline TIN/IDW/**EBK**, concentration surface, approval verb | geostat QA issue |
| B | ArcGIS Pro UI | `.pyt` run-history recording; CAD export functional QA | #231, #238 |
| C | Desktop GUI | GUI workflow builder drive-through | #195 |
| D | AGOL (owner infra) | Phase 9 sandbox hosted service | #307 |

## Prerequisites

- ArcGIS Pro 3.6.1 with **Spatial Analyst** (IDW), **3D Analyst** (TIN), and
  **Geostatistical Analyst** (EBK) licenses available.
- The cloned Pro env `arcgispro-py3-autogis` (see `docs/arcpy-environment.md`).
  All console commands below run in that env's `python`.

## Steps

### 1. Generate + load the synthetic site (~5 min)

```bat
:: any Python — writes CSVs + site_config.yaml + expected_truth.md to Desktop
python docs\qa\make_geostat_qa_data.py

:: Pro env — builds Desktop\AutoGIS-QA\geostat\QASITE.gdb with the real schema
python docs\qa\load_geostat_qa_gdb.py
```

PASS: loader prints `READY: ...QASITE.gdb`. Open `expected_truth.md` — it
states every expected number used below.

### 2. Headless sanity (no arcpy — proves the data, ~2 min)

```bat
python -m autogis envmon build-conc-surface --dry-run ^
  --results %USERPROFILE%\Desktop\AutoGIS-QA\geostat\results.csv ^
  --coords  %USERPROFILE%\Desktop\AutoGIS-QA\geostat\coords.csv ^
  --analyte Benzene --site QASITE --event-date 2026-07-01
```

PASS: 9 points (inner 3×3 detected ring), max ≈ 5000 at MW-06 — **not**
999999 (QC row excluded). Re-run with `--nondetect-rule use_rl`: 16 points
(nondetects join at RL=1.0). MW-02 present with a µg/L-scale value (mg/L row
unit-converted).

### 3. GW model pipeline with EBK — the core acceptance (~15 min)

In Pro, add `autogis/adapters/toolbox.pyt`, open **“5b. Run GW Model Pipeline
(DRAFT)”**:

- GDB: `Desktop\AutoGIS-QA\geostat\QASITE.gdb`
- Site config: `Desktop\AutoGIS-QA\geostat\site_config.yaml`
- Event date: `2026-07-01`
- Methods: **TIN, IDW, EBK** (EBK is the leg under test)
- Stats CSV: `Desktop\AutoGIS-QA\geostat\ranked_stats.csv`

PASS (per `expected_truth.md`):
- [ ] Tool completes; GeoStats license acquired for EBK (no QA ERROR skip).
- [ ] Draft contours: near-parallel SW–NE lines (flow toward SE, ~117°).
- [ ] MW-13's +25 ft outlier is absent (UseForContour=0 honored); MW-16 (dry)
      absent; 14 points used.
- [ ] All three methods ranked in `ranked_stats.csv`; every RMSE < 0.1 ft
      (truth is a plane — any competent interpolator nails it).
- [ ] EBK wrote a `Draft_` standard-error raster; `GW_ModelRun` +
      `GW_ModelCrossValidation` rows exist with ReviewStatus=DRAFT.

### 4. Approval verb (~2 min)

```bat
python -m autogis envmon approve-gw-model --gdb %USERPROFILE%\Desktop\AutoGIS-QA\geostat\QASITE.gdb ^
  --run-id <RunID from step 3> --model EBK --reviewer "<you>" ^
  --site QASITE --event 2026-07-01
```

PASS: `ApprovedModel=EBK, ReviewStatus=APPROVED` — hydro judgment recorded
regardless of rank.

### 5. Concentration surface, IDW then EBK (~15 min)

In Pro, open **“5c. Build Concentration Surface (DRAFT)”** (or the
`build-conc-surface` CLI with `--gdb`): results/coords CSVs from step 2,
analyte `Benzene`, site `QASITE`, event `2026-07-01`; run once with IDW,
once with **EBK**.

PASS:
- [ ] Raster peak within ~10% of 5000 µg/L at MW-06 (Gaussian truth); if the
      peak is ~1e6, canonical read failed — file a bug.
- [ ] EBK run adds a standard-error companion raster.
- [ ] Rasters carry the `Draft_` prefix; `Env_SurfaceRegistry` rows have
      ReviewStatus=DRAFT.
- [ ] `use_zero` vs `exclude` rule visibly changes the plume edge (nondetect
      ring pulled to 0 vs interpolated outward).

### 6. Record the outcome (~5 min)

- Note pass/fail per checkbox in the geostat QA issue; file a bug per failure.
- `.pyt` runs from step 3/5 double as #231 run-history datapoints — check
  `run_history` recorded them and note it on #231.

## After a PASS

Comment the checklist result on the geostat QA issue and close it — that
retires the last residual of the Phase-5 geostat gate (CLAUDE.md gate log
2026-07-24). The synthetic site stays reusable for regression QA of any
future geostat change.
