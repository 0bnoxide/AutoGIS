# GenerateSiteMapSeries Design

**Date:** 2026-06-28
**Status:** Approved
**Tool:** GenerateSiteMapSeries (Tool 5.6)
**Priority:** MEDIUM — produces figure packets across many sites/events in one pass
**Runtime:** LOCAL (arcpy) — routes through the `.pyt` toolbox (ADR-0006)

---

## Problem

A reporting cycle needs dozens of figures: one PDF per site, per map type, per event, or
a combined appendix. Today an analyst opens each layout in Pro and exports by hand. There
is no driver that iterates a site/event/figure-spec matrix and exports the packet, and no
manifest of what was produced.

---

## Approach

**Chosen:** An arcpy-bound packet exporter following the established Tools 2–8 pattern
(CLAUDE.md): the export itself (open APRX layout, set definition queries, export PDF/PNG)
is arcpy and lives in the `.pyt` toolbox; the **iteration plan** — expanding the
site × event × figure-spec matrix into an ordered job list and naming each output — is
pure logic and lives in an arcpy-free core helper that both the toolbox and the tests use.

Per ADR-0002 the core stays import-clean without arcpy; per ADR-0006 the `.pyt` toolbox
is the primary UI and the CLI command guards-and-redirects.

**Rejected: doing the export headless.** Layout export requires `arcpy.mp`; there is no
arcpy-free path to a Pro-rendered PDF. Only the planning is extracted to core.

**Rejected: a bespoke loop per packet type.** The four packet modes (per-site,
per-map-type, combined-appendix, historical-series) are selectors over the same matrix
expansion, not separate code paths.

---

## Architecture

```
autogis/
  core/envmon/
    map_series_plan.py        ← NEW (arcpy-free: matrix expansion + output naming)
  adapters/
    toolbox.pyt               ← add GenerateSiteMapSeries tool class (arcpy export)
    cli.py                    ← add gen-map-series command: _guard + redirect to .pyt
  runtime/
    capabilities.py           ← register "gen-map-series" (requires arcpy)
tests/envmon/
  test_map_series_plan.py     ← NEW (arcpy-free: the plan)
  test_cli_guards.py          ← extend: gen-map-series guard fires headless
```

---

## Public API

Arcpy-free core (`map_series_plan.py`):

```python
@dataclass
class MapJob:
    site_id: str
    event: str
    figure_spec: str
    out_name: str             # deterministic file name
    out_format: str           # pdf | png

def plan_map_series(
    sites: list[str],
    events: list[str],
    figure_specs: list[str],
    *,
    mode: str = "per_site",   # per_site | per_map_type | combined_appendix | historical
    out_format: str = "pdf",
) -> list[MapJob]:
    """Expand the site x event x figure-spec matrix into an ordered, named job list."""
```

Arcpy toolbox tool (`toolbox.pyt`): consumes the `MapJob` list, opens each layout, applies
the figure spec's definition queries, exports, and writes an export manifest CSV.

CLI (`cli.py`): `_guard("gen-map-series")` then a `ClickException` directing the user to the
`GenerateSiteMapSeries` tool in the `.pyt` toolbox — identical to `build-callouts`.

---

## CLI Command

```
autogis envmon gen-map-series --sites <sites.txt> --events 2026Q2 --specs <spec_dir/>
# headless: clean guard error -> use the .pyt toolbox tool inside ArcGIS Pro
```

---

## Test Strategy

Arcpy-free:

1. `plan_map_series(mode="per_site")` yields one job per (site, figure_spec) for the event.
2. `per_map_type` groups jobs by figure spec across sites.
3. `combined_appendix` produces a single ordered job list with appendix sequence.
4. Output names are deterministic and unique across the matrix.
5. `out_format` propagates to every `MapJob`.
6. `gen-map-series` CLI raises a clean guard error (not a traceback) when arcpy is absent.
