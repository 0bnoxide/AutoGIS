# CreateHostedViewsForStakeholders Design

**Date:** 2026-06-28
**Status:** Approved
**Tool:** CreateHostedViewsForStakeholders (Tool 6.11)
**Priority:** MEDIUM — audience-specific hosted views (internal/client/field/public/reg)
**Runtime:** CLI ✓ / AGOL ✓ — `arcgis` (cloud extra), never arcpy

---

## Problem

Different audiences need different slices of the same hosted feature layer: internal QA
sees everything, clients see approved fields only, field crews see active wells for the
current event, the public sees no sensitive analytical values, regulators see approved
exceedance data. Building these views by hand in AGOL is error-prone — a forgotten field
filter can leak sensitive data.

---

## Approach

**Chosen:** A view builder driven by a YAML view-spec, on the injected-`gis` /
lazy-`arcgis` contract. Each view entry declares its source layer, the **field allow-list**
(or deny-list), and a row **definition query**. The tool creates or updates each hosted
view idempotently and verifies after creation that the realized view exposes only the
allowed fields — a leak (a sensitive field still visible) is a blocking QA ERROR, not a
warning. The **field/row filtering resolution** (allow/deny → final field set, query
composition) is pure and fully tested without AGOL; only view create/update touches
`arcgis`.

**Rejected: deny-list only.** Allow-list is the safe default for client/public/regulatory
views (new sensitive fields are excluded unless explicitly allowed); deny-list is offered
for the internal view.

**Rejected: trusting the create call.** The post-create field verification is the safety
property — sensitive-field leakage is checked, not assumed.

**Rejected: `GIS()` in core.** Injected; tests use a fake gis.

---

## Architecture

```
autogis/
  core/agol/
    hosted_views.py           ← NEW (injected gis, lazy arcgis)
  adapters/
    cli.py                    ← add `agol create-views` command
tests/
  test_agol_hosted_views.py   ← NEW (fake gis)
```

---

## Public API (`hosted_views.py`)

```python
@dataclass
class ViewSpec:
    name: str                 # Internal_QA_View, Client_View, Field_Crew_View, ...
    source_layer: str
    allow_fields: list[str] | None
    deny_fields: list[str] | None
    definition_query: str | None
    sensitive_fields: list[str]    # must NOT appear in the realized view

@dataclass
class ViewResult:
    name: str
    created: bool
    exposed_fields: list[str]
    leaked_fields: list[str]       # sensitive fields still visible -> blocking
    qa: QACollector

def resolve_fields(source_fields: list[str], spec: ViewSpec) -> list[str]:
    """Apply allow/deny to produce the final exposed field set (pure)."""

def create_stakeholder_view(
    gis,                       # injected GIS
    spec: ViewSpec,
) -> ViewResult:
    """Create/update the hosted view, then verify no sensitive field leaked."""
```

---

## CLI Command

```
autogis agol create-views \
  --profile <agol_profile.yaml> \
  --view-spec <views.yaml> \
  [--report <views_qa.md>]
```

A leaked sensitive field sets a non-zero exit (blocking QA).

---

## Test Strategy

`tests/test_agol_hosted_views.py` — fake injected `gis`:

1. `resolve_fields` with an allow-list returns only allowed fields.
2. `resolve_fields` with a deny-list drops denied fields, keeps the rest.
3. Sensitive field present in the realized view → `leaked_fields` non-empty, blocking ERROR.
4. Definition query passed through to the created view.
5. `hosted_views.py` imports without `arcgis` installed.
6. Existing view name → `created=False` (update path).
7. Allow-list excludes a newly-added source field by default (no leak on schema growth).
