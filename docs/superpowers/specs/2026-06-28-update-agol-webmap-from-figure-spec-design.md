# UpdateAGOLWebMapFromFigureSpec Design

**Date:** 2026-06-28
**Status:** Approved
**Tool:** UpdateAGOLWebMapFromFigureSpec (Tool 6.3)
**Priority:** MEDIUM — keeps web maps in sync with the same figure specs that drive print
**Runtime:** CLI ✓ / AGOL ✓ — `arcgis` (cloud extra), never arcpy

---

## Problem

The same figure spec that configures a print layout (layer visibility, definition
queries, popups, labels, symbology) has a web-map equivalent in AGOL, maintained by hand
in the AGOL UI. The two drift. There is no tool that pushes a figure spec's display
config into a hosted web map's JSON.

---

## Approach

**Chosen:** Follow the shipped `core/agol/publish.py` contract (ADR + the publish-layer
plan): a `core/agol/webmap.py` module whose `gis` is **always injected**, with all
`arcgis` surface **lazy** inside function bodies so the module imports clean without the
cloud extra (ADR-0002 boundary extends to `arcgis`). The function reads the web map item
JSON, applies the figure spec (visibility, definition queries, popup/label config per
layer, symbology references), and writes it back. All outcomes flow through `QACollector`;
a `--dry-run` renders the JSON diff without writing.

**Rejected: editing symbology renderer JSON from scratch.** The tool maps figure-spec
fields onto existing operational-layer entries by layer name/id; a layer named in the spec
but absent in the web map is a QA WARNING, not a created layer.

**Rejected: instantiating `GIS()` inside core.** Credentials live only in the CLI seam
(`agol_from_profile`); core stays testable with a fake `gis`.

---

## Architecture

```
autogis/
  core/agol/
    publish.py                ← EXISTS (contract reference)
    webmap.py                 ← NEW (injected gis, lazy arcgis)
  adapters/
    cli.py                    ← add `agol update-webmap` command (builds + injects gis)
tests/
  test_agol_webmap.py         ← NEW (fake gis, no credentials)
```

---

## Public API (`webmap.py`)

```python
@dataclass
class WebMapUpdateResult:
    item_id: str
    layers_updated: int
    layers_missing: list[str]
    qa: QACollector

def update_webmap_from_spec(
    gis,                          # injected GIS
    *,
    webmap_item_id: str,
    figure_spec: dict,
    dry_run: bool = False,
) -> WebMapUpdateResult:
    """Apply a figure spec's display config to a hosted web map's operational layers."""
```

No `arcgis` import at module level; the item fetch/update calls are inside the function.

---

## CLI Command

```
autogis agol update-webmap \
  --profile <agol_profile.yaml> \
  --webmap-item <itemid> \
  --figure-spec <figure_spec.yaml> \
  [--dry-run] \
  [--report <webmap_qa.md>]
```

---

## Test Strategy

`tests/test_agol_webmap.py` — fake injected `gis`, no live AGOL:

1. `webmap.py` imports without `arcgis` installed (no module-level import).
2. Visibility from the spec applied to the matching operational layer.
3. Definition query from the spec written to the matching layer.
4. Layer named in spec but absent in web map → `layers_missing` + WARNING.
5. `dry_run=True` produces a diff and writes nothing (fake gis records no update call).
6. `layers_updated` counts only changed layers.
