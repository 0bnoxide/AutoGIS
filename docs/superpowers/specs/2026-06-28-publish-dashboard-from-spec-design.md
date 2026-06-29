# PublishDashboardFromSpec Design

**Date:** 2026-06-28
**Status:** Approved
**Tool:** PublishDashboardFromSpec (Tool 6.8)
**Priority:** MEDIUM — makes dashboards reproducible and version-controlled
**Runtime:** CLI ✓ / AGOL ✓✓ — `arcgis` (cloud extra), never arcpy

---

## Problem

Dashboards are built by clicking in the AGOL Dashboards UI: indicator cards, serial
charts, selectors, lists, filters, theme. None of it is version-controlled, and rebuilding
a dashboard for a new site is manual re-clicking. There is no way to define a dashboard in
YAML and publish/update it.

---

## Approach

**Chosen:** A spec→dashboard publisher on the injected-`gis` / lazy-`arcgis` contract. A
YAML spec declares the dashboard (title, web-map item, indicator cards, serial charts,
category/date selectors, lists, embedded report links, filters, theme, refresh interval).
The tool compiles the spec into the AGOL Dashboard item JSON and creates-or-updates the
item idempotently (by item id or title), matching `publish.py`'s create-or-overwrite
discipline. Charts/cards reference the `Dash_*` data-mart layers (6.4/6.7). A `--dry-run`
emits the compiled JSON without publishing.

The **spec→JSON compilation** is pure and lives in an arcgis-free helper that the tests
exercise fully; only the create/update call touches `arcgis`.

**Rejected: a thick UI-config DSL.** The spec covers the documented element set; anything
exotic is authored once in AGOL and exported, not modeled here.

**Rejected: building the data mart here.** Dashboards point only at `Dash_*` layers built
by 6.7 and refreshed by 6.4 — schema isolation is the whole point.

**Rejected: `GIS()` in core.** Injected; tests use a fake gis.

---

## Architecture

```
autogis/
  core/agol/
    dashboard_spec.py         ← NEW: compile_dashboard_json(spec) -> dict (arcgis-free)
    dashboard_publish.py      ← NEW: publish_dashboard(gis, ...) (injected, lazy arcgis)
  adapters/
    cli.py                    ← add `agol publish-dashboard` command
tests/
  test_agol_dashboard_spec.py     ← NEW (pure compile)
  test_agol_dashboard_publish.py  ← NEW (fake gis)
```

---

## Public API

```python
# dashboard_spec.py — pure
def compile_dashboard_json(spec: dict) -> dict:
    """Compile a dashboard YAML spec into AGOL Dashboard item JSON."""

# dashboard_publish.py
@dataclass
class PublishDashboardResult:
    item_id: str
    created: bool                # True if new, False if updated
    qa: QACollector

def publish_dashboard(
    gis,                         # injected GIS
    spec: dict,
    *,
    dry_run: bool = False,
) -> PublishDashboardResult:
    """Create or update a dashboard item from its compiled spec JSON."""
```

---

## CLI Command

```
autogis agol publish-dashboard \
  --profile <agol_profile.yaml> \
  --spec <dashboard_spec.yaml> \
  [--dry-run] \
  [--report <publish_qa.md>]
```

---

## Test Strategy

`tests/test_agol_dashboard_spec.py` (pure) + `test_agol_dashboard_publish.py` (fake gis):

1. `compile_dashboard_json` emits a header with the spec title + web-map item.
2. Each indicator card in the spec appears in the compiled JSON.
3. Serial chart references its `Dash_*` data-mart layer.
4. Category/date selectors compile to the right element types.
5. `dashboard_publish.py` imports without `arcgis` installed.
6. New item → `created=True`; existing item id → `created=False` (update path).
7. `dry_run=True` returns compiled JSON, fake gis records no publish call.
