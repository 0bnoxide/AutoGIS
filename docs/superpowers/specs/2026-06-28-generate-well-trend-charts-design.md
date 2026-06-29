# GenerateWellTrendCharts Design

**Date:** 2026-06-28
**Status:** Approved
**Tool:** GenerateWellTrendCharts (Tool 4.6)
**Priority:** MEDIUM — hydrographs and concentration trends are standard report exhibits

---

## Problem

Monitoring reports include hydrographs (water level vs. time) and concentration trend
plots (analyte vs. time) per well. Analysts build these by hand in Excel each event.
There is no tool that reads the normalized history and emits chart images + a trend
summary, and no objective trend classification (Mann-Kendall) — trends are eyeballed.

---

## Approach

**Chosen:** Headless chart generator over normalized long-format history. For each
(well, analyte|water-level) series, sort by date, render a PNG (matplotlib), and compute
a **Mann-Kendall** trend flag (increasing / decreasing / no-trend, with Sen's slope) —
deterministic, no SciPy required (the S-statistic + variance is short stdlib math).
Nondetects plotted at half the detection limit, flagged in the legend. Outputs PNGs, an
optional combined PDF packet, and a trend summary CSV (dashboard-ready).

**Rejected: SciPy/pandas dependency.** Mann-Kendall and Sen's slope are a few dozen
lines of stdlib `statistics`/`math`; the repo avoids heavy deps. matplotlib is the only
addition and is import-guarded so the core stays importable without it (charts skipped +
WARNING if matplotlib absent).

**Rejected: in-map ArcGIS charts.** These are report exhibits, not map layers — pure
headless image generation, runs in CI/cloud.

**Rejected: deciding regulatory trend significance.** The tool emits the Mann-Kendall
statistic and classification; professional interpretation stays with the hydrogeologist
(the same DRAFT-guardrail philosophy as the contour tools).

---

## Architecture

```
autogis/
  core/envmon/
    trend_charts.py          ← NEW (data prep + Mann-Kendall, arcpy-free)
  adapters/
    cli.py                   ← add gen-trend-charts command (headless)
tests/envmon/
  test_trend_charts.py       ← NEW
```

matplotlib import is wrapped: data-prep and Mann-Kendall are pure stdlib and fully
tested; only the PNG render call needs matplotlib.

---

## Public API (`trend_charts.py`)

```python
@dataclass
class TrendSeries:
    location_id: str
    analyte: str             # or "WaterLevel"
    dates: list[str]
    values: list[float]
    nondetect_flags: list[bool]

@dataclass
class TrendResult:
    location_id: str
    analyte: str
    mk_statistic: float
    sens_slope: float
    trend_class: str         # increasing | decreasing | no-trend | insufficient-data
    n: int

def build_series(rows: list[dict], *, value_field: str) -> list[TrendSeries]:
    """Group normalized rows into per-well, per-analyte time series."""

def mann_kendall(values: list[float]) -> tuple[float, str]:
    """Return (S-statistic, trend_class). Pure stdlib."""

def sens_slope(dates: list[float], values: list[float]) -> float:
    """Median pairwise slope. Pure stdlib."""

def summarize_trends(series: list[TrendSeries]) -> list[TrendResult]: ...

def render_charts(series, out_dir: Path, *, combined_pdf: bool = False) -> list[Path]:
    """Render PNGs (and optional PDF). No-op + WARNING if matplotlib missing."""
```

---

## CLI Command

```
autogis envmon gen-trend-charts \
  --history <history.csv> \
  --value-field result_value \
  --out-dir <charts/> \
  [--wells MW-1,MW-2] \
  [--analytes Benzene,MTBE] \
  [--combined-pdf] \
  [--summary <trend_summary.csv>]
```

Headless. PNG/PDF render requires matplotlib; trend summary does not.

---

## Test Strategy

`tests/envmon/test_trend_charts.py` — arcpy-free, no matplotlib needed:

1. `build_series` groups rows into correct (well, analyte) series.
2. `mann_kendall` on a strictly increasing series → positive S, `increasing`.
3. `mann_kendall` on flat data → `no-trend`.
4. `sens_slope` returns the median pairwise slope on a known set.
5. Fewer than 4 points → `insufficient-data`.
6. Nondetect values plotted at half-DL are flagged in `TrendSeries`.
7. `summarize_trends` emits one `TrendResult` per series.
