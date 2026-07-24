"""make_geostat_qa_data.py — synthetic dataset for the geostat live-Pro QA batch.

Generates a deterministic (seeded) synthetic site with KNOWN ground truth so
the human QA session can verify tool output against math, not vibes:

- 16 monitoring wells on a jittered 4x4 grid (UTM-like meters).
- Groundwater elevations on a known plane (gradient toward the SE) with tiny
  noise -> TIN/IDW/EBK draft contours + LOO ranking have a known right answer.
- A benzene plume as a Gaussian mound centered on MW-06 -> the concentration
  surface has a known peak, spread, and nondetect ring.
- Deliberate edge rows: one UseForContour=0 outlier, one dry well, one
  QCType row (must be dropped by canonical read), one mg/L row (must be
  unit-converted), nondetects with RLs (exercise all 4 nondetect rules).

Output goes to a staging folder OUTSIDE the repo (default:
``~/Desktop/AutoGIS-QA/geostat/``) — synthetic QA data is never committed.

Usage (any Python 3.9+, no deps):
    python docs/qa/make_geostat_qa_data.py            # write to Desktop
    python docs/qa/make_geostat_qa_data.py --out DIR  # write elsewhere
    python docs/qa/make_geostat_qa_data.py --check    # self-test, no files
"""
from __future__ import annotations

import argparse
import csv
import math
import random
from pathlib import Path

SITE_ID = "QASITE"
EVENT_DATE = "2026-07-01"
ANALYTE = "Benzene"

# Ground truth — cited in expected_truth.md and asserted by --check.
BASE_X, BASE_Y = 500_000.0, 4_650_000.0   # UTM-like origin, meters
SPACING = 60.0                            # grid spacing
GWE_BASE = 100.0                          # ft at the origin well
GWE_DX, GWE_DY = -0.004, -0.002           # ft/m -> flow toward SE (~117 deg)
GWE_NOISE_FT = 0.02
PLUME_SOURCE = "MW-06"                    # grid position (1,1)
PLUME_PEAK_UGL = 5000.0
PLUME_SIGMA_M = 25.0   # small vs the 60 m grid -> outer ring is nondetect
RL_UGL = 1.0                              # nondetect below this


def truth_gwe(x: float, y: float) -> float:
    return GWE_BASE + GWE_DX * (x - BASE_X) + GWE_DY * (y - BASE_Y)


def truth_conc(x: float, y: float, sx: float, sy: float) -> float:
    d2 = (x - sx) ** 2 + (y - sy) ** 2
    return PLUME_PEAK_UGL * math.exp(-d2 / (2 * PLUME_SIGMA_M ** 2))


def build_rows():
    rng = random.Random(42)
    wells, waterlevels, results, coords = [], [], [], []
    positions = {}
    for r in range(4):
        for c in range(4):
            n = r * 4 + c + 1
            loc = f"MW-{n:02d}"
            x = BASE_X + c * SPACING + rng.uniform(-8, 8)
            y = BASE_Y + r * SPACING + rng.uniform(-8, 8)
            positions[loc] = (x, y)
            gse = truth_gwe(x, y) + 8.0   # ground ~8 ft above water table
            wells.append({
                "SiteID": SITE_ID, "LocationID": loc, "WellID": loc,
                "WellType": "monitoring", "Status": "active",
                "X": round(x, 2), "Y": round(y, 2),
                "GroundElev_ft": round(gse, 2), "TOC_ft": round(gse + 2.5, 2),
            })

    sx, sy = positions[PLUME_SOURCE]
    for loc, (x, y) in positions.items():
        # --- water level row ---
        gwe = truth_gwe(x, y) + rng.gauss(0, GWE_NOISE_FT)
        row = {
            "SiteID": SITE_ID, "LocationID": loc, "EventDate": EVENT_DATE,
            "MonitoringPointElevation_ft": "", "DepthToWater_ft": "",
            "GroundwaterElevation_ft": round(gwe, 3),
            "IsDry": 0, "IsMeasured": 1, "MeasurementStatus": "OK",
            "UseForContour": 1, "ExclusionReason": "",
        }
        if loc == "MW-13":                # deliberate excluded outlier
            row["GroundwaterElevation_ft"] = round(gwe + 25.0, 3)
            row["UseForContour"] = 0
            row["ExclusionReason"] = "synthetic outlier - excluded"
        if loc == "MW-16":                # deliberate dry well
            row.update({"GroundwaterElevation_ft": "", "IsDry": 1,
                        "IsMeasured": 0, "MeasurementStatus": "DRY",
                        "UseForContour": 0,
                        "ExclusionReason": "dry - no measurement"})
        waterlevels.append(row)
        coords.append({"location_id": loc,
                       "x": round(x, 2), "y": round(y, 2)})

        # --- benzene result row ---
        c_ugl = truth_conc(x, y, sx, sy)
        detected = c_ugl >= RL_UGL
        res = {
            "SiteID": SITE_ID, "LocationID": loc,
            "SampleID": f"{loc}-{EVENT_DATE}",
            "SampleDate": EVENT_DATE, "Matrix": "WG",
            "AnalyteName": ANALYTE, "AnalyteCanonicalName": ANALYTE,
            "ResultRawText": (f"{c_ugl:.1f}" if detected else f"<{RL_UGL}"),
            "ResultNumeric": (round(c_ugl, 1) if detected else ""),
            "ReportingLimit": RL_UGL, "DetectionLimit": RL_UGL / 2,
            "Units": "ug/L", "Qualifier": ("" if detected else "U"),
            "IsNonDetect": (0 if detected else 1),
            "IsDetected": (1 if detected else 0),
            "QCType": "", "ResultFraction": "",
        }
        if loc == "MW-02" and detected:   # deliberate mg/L row (unit conv)
            res.update({"ResultNumeric": round(c_ugl / 1000.0, 6),
                        "Units": "mg/L",
                        "ResultRawText": f"{c_ugl / 1000.0:.6f}"})
        results.append(res)

    # Deliberate QC row: same well as the peak, absurd value; canonical read
    # MUST drop it (QCType set) or the surface peak will be visibly wrong.
    results.append(dict(results[0], LocationID=PLUME_SOURCE,
                        SampleID=f"{PLUME_SOURCE}-{EVENT_DATE}-FD",
                        QCType="FD", ResultNumeric=999999,
                        ResultRawText="999999", IsNonDetect=0, IsDetected=1,
                        Units="ug/L"))
    return wells, waterlevels, results, coords


def write_all(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    wells, waterlevels, results, coords = build_rows()
    for name, rows in (("wells.csv", wells), ("waterlevels.csv", waterlevels),
                       ("results.csv", results), ("coords.csv", coords)):
        with (out / name).open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    (out / "expected_truth.md").write_text(EXPECTED_TRUTH, encoding="utf-8")
    gdb = (out / "QASITE.gdb").as_posix()
    (out / "site_config.yaml").write_text(SITE_CONFIG_TMPL.format(gdb=gdb),
                                          encoding="utf-8")
    print(f"Wrote {len(wells)} wells, {len(waterlevels)} water levels, "
          f"{len(results)} results + site_config.yaml -> {out}")


# All SITE_REQUIRED keys (presence-validated); values beyond gdb/site_id are
# synthetic placeholders the geostat tools never read.
SITE_CONFIG_TMPL = """\
site_id: {SITE_ID}
site_name: Synthetic Geostat QA Site
project_number: QA-0000
address: 1 Synthetic Way
city: Nowhere
state: NY
coordinate_system: EPSG:26918
default_gdb: {{gdb}}
default_aprx_template: UNUSED.aprx
monitoring_wells_fc: MonitoringWells
soil_borings_fc: SoilBorings
site_boundary_fc: SiteBoundary
""".format(SITE_ID=SITE_ID, gdb="{gdb}")


EXPECTED_TRUTH = f"""# Ground truth for the synthetic geostat QA site

Site {SITE_ID}, event {EVENT_DATE}, analyte {ANALYTE}. Regenerate any time:
`python docs/qa/make_geostat_qa_data.py` (seeded — output is identical).

## Groundwater surface (Env_WaterLevels)
- TRUE surface: plane, GWE = {GWE_BASE} + ({GWE_DX})(x-{BASE_X:.0f}) +
  ({GWE_DY})(y-{BASE_Y:.0f}) ft, noise sigma = {GWE_NOISE_FT} ft.
- Flow direction: toward the SE (azimuth ~117 deg from north).
- Contourable wells: 14 (MW-13 excluded UseForContour=0 outlier; MW-16 dry).
- PASS: draft contours are near-parallel lines trending SW-NE; LOO RMSE for
  every method well under 0.1 ft; MW-13's +25 ft spike absent from contours.

## Benzene plume (results.csv)
- TRUE surface: Gaussian, peak {PLUME_PEAK_UGL:.0f} ug/L at {PLUME_SOURCE},
  sigma {PLUME_SIGMA_M:.0f} m. Wells below {RL_UGL} ug/L are nondetects (U).
- MW-02 is reported in mg/L — the surface must unit-convert it, not drop it.
- One QCType=FD row (999999 ug/L at {PLUME_SOURCE}) MUST be excluded by
  canonical read: if the interpolated peak is ~1e6, canonical read failed.
- PASS: surface peak within ~10% of {PLUME_PEAK_UGL:.0f} ug/L at
  {PLUME_SOURCE}; nondetect ring behaves per rule (exclude/half_rl/use_rl/
  use_zero -> point counts differ exactly as the rule implies).
"""


def check() -> None:
    wells, waterlevels, results, coords = build_rows()
    assert len(wells) == 16 and len(coords) == 16
    contourable = [r for r in waterlevels if r["UseForContour"] == 1]
    assert len(contourable) == 14, len(contourable)
    dry = [r for r in waterlevels if r["IsDry"] == 1]
    assert len(dry) == 1 and dry[0]["GroundwaterElevation_ft"] == ""
    # plane recoverable: residual of contourable GWEs vs truth < 4*sigma
    for r in contourable:
        x, y = next((w["X"], w["Y"]) for w in wells
                    if w["LocationID"] == r["LocationID"])
        assert abs(r["GroundwaterElevation_ft"] - truth_gwe(x, y)) < 4 * GWE_NOISE_FT
    qc = [r for r in results if r["QCType"]]
    assert len(qc) == 1 and qc[0]["ResultNumeric"] == 999999
    nd = [r for r in results if r["IsNonDetect"] == 1]
    # outer ring (row 3 / col 3) must be nondetect, inner 3x3 detected
    assert 5 <= len(nd) <= 8, len(nd)
    assert all(r["ResultNumeric"] == "" for r in nd)
    mgl = [r for r in results if r["Units"] == "mg/L"]
    assert len(mgl) == 1 and mgl[0]["LocationID"] == "MW-02"
    # determinism
    assert build_rows()[1][0] == waterlevels[0]
    print("make_geostat_qa_data --check: OK")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path,
                    default=Path.home() / "Desktop" / "AutoGIS-QA" / "geostat")
    ap.add_argument("--check", action="store_true", help="self-test only")
    args = ap.parse_args()
    if args.check:
        check()
    else:
        write_all(args.out)


if __name__ == "__main__":
    main()
