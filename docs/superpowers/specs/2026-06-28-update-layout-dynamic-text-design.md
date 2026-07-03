# UpdateLayoutDynamicText Design

> **SUPERSEDED (2026-07-02, ADR-0041).** Do NOT build the `layout_text.py`
> module this spec proposes — the core logic already shipped as
> `autogis/core/envmon/layout_manager.py::update_layout_text()` (named
> elements + `{{placeholder}}` resolution with QA warnings), and Tool 5.8 is
> now the `envmon update-layout-text` CLI command calling it directly
> (CLI-first per ADR-0039; this spec's guard-and-redirect Architecture
> section predates that ADR). Kept for historical record only.

**Date:** 2026-06-28
**Status:** Superseded — see ADR-0041
**Tool:** UpdateLayoutDynamicText (Tool 5.8)
**Priority:** MEDIUM — keeps figure title blocks consistent across a packet
**Runtime:** LOCAL (arcpy) — routes through the `.pyt` toolbox (ADR-0006)

---

## Problem

Every figure's title block carries the same metadata: site name, address, figure number,
event date, project number, prepared-by, reviewed-by, report date, regulatory basis. When
any of these changes, an analyst edits each layout by hand and they drift apart. There is
no batch updater that pushes one metadata record into every layout's dynamic-text
elements.

---

## Approach

**Chosen:** arcpy-bound batch text updater on the Tools 2–8 pattern. The arcpy part —
walking `arcpy.mp` layout elements and setting dynamic-text values — lives in the `.pyt`
toolbox. The **resolution logic** — taking a metadata record + a field-spec config and
producing the `{element_name: text}` map, including computed fields like figure number
sequencing and formatted dates — is pure and lives in an arcpy-free core helper, fully
tested without Pro.

ADR-0002 keeps core arcpy-free; ADR-0006 keeps the `.pyt` toolbox as the UI with the CLI
guarding-and-redirecting.

**Rejected: free-text find/replace in layouts.** Brittle. The tool maps *named* dynamic-text
elements to *named* metadata fields via config, so a missing element is a QA warning, not
a silent miss.

**Rejected: headless layout editing.** Layout element access needs `arcpy.mp`; only the
text resolution is extracted.

---

## Architecture

```
autogis/
  core/envmon/
    layout_text.py            ← NEW (arcpy-free: metadata -> element-text map)
  adapters/
    toolbox.pyt               ← add UpdateLayoutDynamicText tool class (arcpy apply)
    cli.py                    ← add update-layout-text command: _guard + redirect
  runtime/
    capabilities.py           ← register "update-layout-text" (requires arcpy)
tests/envmon/
  test_layout_text.py         ← NEW (arcpy-free)
  test_cli_guards.py          ← extend: update-layout-text guard fires headless
```

---

## Public API

Arcpy-free core (`layout_text.py`):

```python
@dataclass
class TextUpdate:
    element_name: str
    value: str
    source_field: str

def resolve_layout_text(
    metadata: dict,                  # site_name, address, project_number, ...
    field_spec: dict,                # element_name -> {field, format}
    *,
    figure_number_start: int | None = None,
) -> list[TextUpdate]:
    """Map metadata onto named layout elements; format dates/numbers; sequence figures."""
```

Arcpy toolbox tool: opens the APRX/layouts, applies each `TextUpdate` to the matching
dynamic-text element, warns on elements present in the spec but absent in the layout, and
on layout elements not covered by the spec.

CLI: `_guard("update-layout-text")` then a `ClickException` pointing at the
`UpdateLayoutDynamicText` tool in the `.pyt` toolbox.

---

## CLI Command

```
autogis envmon update-layout-text --metadata <meta.yaml> --field-spec <fields.yaml> --aprx <project.aprx>
# headless: clean guard error -> use the .pyt toolbox tool inside ArcGIS Pro
```

---

## Test Strategy

Arcpy-free:

1. `resolve_layout_text` maps each metadata field to its named element.
2. Date fields formatted per the field spec's format string.
3. `figure_number_start` sequences figure numbers across elements in order.
4. Metadata field missing for a spec'd element → that element omitted + a recorded warning.
5. Element name in spec maps to exactly one `TextUpdate`.
6. `update-layout-text` CLI raises a clean guard error when arcpy is absent.
