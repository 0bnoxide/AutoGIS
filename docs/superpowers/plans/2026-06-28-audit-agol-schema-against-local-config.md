# AuditAGOLSchemaAgainstLocalConfig (Tool 6.6) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `autogis agol audit-schema` CLI command that compares a hosted AGOL feature layer's schema (fields, types, domains) against a local layer spec YAML, and reports structured drift — missing fields, extra fields, type mismatches, and domain drift.

**Architecture:** New headless module `autogis/core/agol/audit_schema.py` contains:
(a) `diff_schema(fetched_schema: dict, local_spec: dict) -> SchemaDriftReport` — pure diff, zero arcgis dependency, fully unit-testable with fixture dicts;
(b) `format_drift_report(report)` — text formatter;
(c) `fetch_layer_schema(gis, ...)` — lazy-imports arcgis, marked `# pragma: no cover`, the single seam between the headless core and the live API.
The CLI command in `autogis/adapters/cli.py` calls `agol_from_profile()` (from `autogis/runtime/sessions.py`), then `fetch_layer_schema()`, then `diff_schema()` — exactly the same seam pattern as `publish.py` / `publish-layer`.

**Tech Stack:** Python 3.x, stdlib `dataclasses` / `csv` / `json`, `click`, `PyYAML` (already a cli.py dep), `pytest` + `monkeypatch`. No new dependencies.

## Global Constraints

- `autogis/core/agol/audit_schema.py` must import without `arcgis` or `arcpy` present. `fetch_layer_schema()` lazy-imports `arcgis.features.FeatureLayer` inside the function body and is `# pragma: no cover`.
- Command name exactly `audit-schema` under the existing `agol` group in `cli.py`.
- `diff_schema()` and `format_drift_report()` are the only public surface of the headless core — all tests use these two functions with fixture dicts; no mock of arcgis needed.
- Local spec files use `coded_values` (snake_case list); AGOL REST JSON uses `codedValues` (camelCase). `diff_schema()` handles both; this asymmetry is intentional and must be preserved.
- `SiteConfig` is canonical in `autogis/core/common/config.py`. Local spec files are standalone YAML/JSON loaded via `load_config()` (already in common/config.py). They are NOT embedded in `SiteConfig`.
- Run tests with `python -m pytest -q`. All new tests must pass headlessly.
- Branch: main (or `feat/audit-agol-schema` if isolating the work).

---

### Task 1: Core module `audit_schema.py` + unit tests

**Files:**
- Create: `autogis/core/agol/audit_schema.py`
- Create: `tests/test_audit_schema.py`

**Interfaces:**
- Produces (for Task 2):
  - `diff_schema(fetched_schema: dict, local_spec: dict) -> SchemaDriftReport`
  - `format_drift_report(report: SchemaDriftReport) -> str`
  - `fetch_layer_schema(gis, *, layer_url=None, item_id=None, layer_index=0) -> dict`
  - `DriftItem` dataclass — fields: `field_name: str`, `drift_type: str`, `local_value: Optional[str]`, `agol_value: Optional[str]`, `message: str`
  - `SchemaDriftReport` dataclass — fields: `layer_name: str`, `total_agol_fields: int`, `total_spec_fields: int`, `drift_items: List[DriftItem]`, `.has_drift: bool`, `.drift_by_type: Dict[str, List[DriftItem]]`
  - Drift-type string constants: `DRIFT_MISSING_FIELD`, `DRIFT_EXTRA_FIELD`, `DRIFT_TYPE_MISMATCH`, `DRIFT_DOMAIN_DRIFT`, `DRIFT_NULLABLE_MISMATCH`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_audit_schema.py`:

```python
"""Unit tests for diff_schema / format_drift_report (headless, no arcgis)."""
import pytest

from autogis.core.agol.audit_schema import (
    diff_schema,
    format_drift_report,
    SchemaDriftReport,
    DriftItem,
    DRIFT_MISSING_FIELD,
    DRIFT_EXTRA_FIELD,
    DRIFT_TYPE_MISMATCH,
    DRIFT_DOMAIN_DRIFT,
    DRIFT_NULLABLE_MISMATCH,
)


# ── shared fixtures ───────────────────────────────────────────────────────────

_BASE_SPEC = {
    "layer_name": "MonitoringWells",
    "fields": [
        {"name": "OBJECTID",   "type": "esriFieldTypeOID"},
        {"name": "LocationID", "type": "esriFieldTypeString", "nullable": True},
        {"name": "WellType",   "type": "esriFieldTypeString", "nullable": True,
         "domain": {
             "name": "WellTypeDomain",
             "coded_values": [
                 {"code": "MW", "name": "Monitoring Well"},
                 {"code": "SW", "name": "Surface Water"},
             ],
         }},
    ],
}

_BASE_AGOL = {
    "name": "MonitoringWells",
    "fields": [
        {"name": "OBJECTID",   "type": "esriFieldTypeOID",   "nullable": False, "domain": None},
        {"name": "LocationID", "type": "esriFieldTypeString", "nullable": True,  "domain": None},
        {"name": "WellType",   "type": "esriFieldTypeString", "nullable": True,
         "domain": {
             "type": "codedValue",
             "name": "WellTypeDomain",
             "codedValues": [
                 {"code": "MW", "name": "Monitoring Well"},
                 {"code": "SW", "name": "Surface Water"},
             ],
         }},
    ],
}


def _spec(**override) -> dict:
    return {**_BASE_SPEC, **override}


def _agol(**override) -> dict:
    return {**_BASE_AGOL, **override}


# ── clean / no drift ─────────────────────────────────────────────────────────

def test_perfect_match_no_drift():
    report = diff_schema(_BASE_AGOL, _BASE_SPEC)
    assert not report.has_drift
    assert report.drift_items == []
    assert report.layer_name == "MonitoringWells"
    assert report.total_spec_fields == 3
    assert report.total_agol_fields == 3


# ── MISSING_FIELD ─────────────────────────────────────────────────────────────

def test_missing_field_detected():
    spec = _spec(fields=_BASE_SPEC["fields"] + [
        {"name": "SampleDepth_ft", "type": "esriFieldTypeDouble"}
    ])
    report = diff_schema(_BASE_AGOL, spec)
    missing = [d for d in report.drift_items if d.drift_type == DRIFT_MISSING_FIELD]
    assert len(missing) == 1
    assert missing[0].field_name == "SampleDepth_ft"
    assert missing[0].agol_value is None
    assert missing[0].local_value == "esriFieldTypeDouble"


def test_missing_field_message_describes_problem():
    spec = _spec(fields=_BASE_SPEC["fields"] + [
        {"name": "SampleDepth_ft", "type": "esriFieldTypeDouble"}
    ])
    report = diff_schema(_BASE_AGOL, spec)
    missing = [d for d in report.drift_items if d.drift_type == DRIFT_MISSING_FIELD]
    assert "SampleDepth_ft" in missing[0].message


# ── EXTRA_FIELD ───────────────────────────────────────────────────────────────

def test_extra_field_detected():
    agol = _agol(fields=_BASE_AGOL["fields"] + [
        {"name": "GlobalID", "type": "esriFieldTypeGlobalID",
         "nullable": False, "domain": None}
    ])
    report = diff_schema(agol, _BASE_SPEC)
    extra = [d for d in report.drift_items if d.drift_type == DRIFT_EXTRA_FIELD]
    assert len(extra) == 1
    assert extra[0].field_name == "GlobalID"
    assert extra[0].local_value is None
    assert extra[0].agol_value == "esriFieldTypeGlobalID"


# ── TYPE_MISMATCH ─────────────────────────────────────────────────────────────

def test_type_mismatch_detected():
    agol = _agol(fields=[
        {"name": "OBJECTID",   "type": "esriFieldTypeOID",     "nullable": False, "domain": None},
        {"name": "LocationID", "type": "esriFieldTypeInteger",  "nullable": True,  "domain": None},
        {"name": "WellType",   "type": "esriFieldTypeString",   "nullable": True,
         "domain": {"type": "codedValue", "name": "WellTypeDomain",
                    "codedValues": [{"code": "MW", "name": "Monitoring Well"},
                                    {"code": "SW", "name": "Surface Water"}]}},
    ])
    report = diff_schema(agol, _BASE_SPEC)
    mismatches = [d for d in report.drift_items if d.drift_type == DRIFT_TYPE_MISMATCH]
    assert len(mismatches) == 1
    assert mismatches[0].field_name == "LocationID"
    assert mismatches[0].local_value == "esriFieldTypeString"
    assert mismatches[0].agol_value  == "esriFieldTypeInteger"


# ── NULLABLE_MISMATCH ─────────────────────────────────────────────────────────

def test_nullable_mismatch_detected():
    agol = _agol(fields=[
        {"name": "OBJECTID",   "type": "esriFieldTypeOID",    "nullable": False, "domain": None},
        {"name": "LocationID", "type": "esriFieldTypeString",  "nullable": False, "domain": None},
        {"name": "WellType",   "type": "esriFieldTypeString",  "nullable": True,
         "domain": {"type": "codedValue", "name": "WellTypeDomain",
                    "codedValues": [{"code": "MW", "name": "Monitoring Well"},
                                    {"code": "SW", "name": "Surface Water"}]}},
    ])
    report = diff_schema(agol, _BASE_SPEC)
    nullables = [d for d in report.drift_items if d.drift_type == DRIFT_NULLABLE_MISMATCH]
    assert len(nullables) == 1
    assert nullables[0].field_name == "LocationID"


def test_nullable_not_checked_when_not_in_spec():
    """Fields without 'nullable' in spec should not produce NULLABLE_MISMATCH."""
    spec = _spec(fields=[
        {"name": "OBJECTID",   "type": "esriFieldTypeOID"},        # no nullable key
        {"name": "LocationID", "type": "esriFieldTypeString"},      # no nullable key
        {"name": "WellType",   "type": "esriFieldTypeString",
         "domain": {"name": "WellTypeDomain",
                    "coded_values": [{"code": "MW", "name": "Monitoring Well"},
                                     {"code": "SW", "name": "Surface Water"}]}},
    ])
    report = diff_schema(_BASE_AGOL, spec)
    nullables = [d for d in report.drift_items if d.drift_type == DRIFT_NULLABLE_MISMATCH]
    assert nullables == []


# ── DOMAIN_DRIFT: spec has domain, AGOL has none ─────────────────────────────

def test_domain_drift_spec_has_domain_agol_has_none():
    agol = _agol(fields=[
        {"name": "OBJECTID",   "type": "esriFieldTypeOID",   "nullable": False, "domain": None},
        {"name": "LocationID", "type": "esriFieldTypeString", "nullable": True,  "domain": None},
        {"name": "WellType",   "type": "esriFieldTypeString", "nullable": True,  "domain": None},
    ])
    report = diff_schema(agol, _BASE_SPEC)
    domain_items = [d for d in report.drift_items if d.drift_type == DRIFT_DOMAIN_DRIFT]
    assert len(domain_items) == 1
    assert domain_items[0].field_name == "WellType"
    assert domain_items[0].local_value == "WellTypeDomain"
    assert domain_items[0].agol_value is None


# ── DOMAIN_DRIFT: AGOL has domain, spec has none ─────────────────────────────

def test_domain_drift_agol_has_domain_spec_has_none():
    spec = _spec(fields=[
        {"name": "OBJECTID",   "type": "esriFieldTypeOID"},
        {"name": "LocationID", "type": "esriFieldTypeString", "nullable": True},
        {"name": "WellType",   "type": "esriFieldTypeString", "nullable": True},
    ])
    report = diff_schema(_BASE_AGOL, spec)
    domain_items = [d for d in report.drift_items if d.drift_type == DRIFT_DOMAIN_DRIFT]
    assert len(domain_items) == 1
    assert domain_items[0].field_name == "WellType"
    assert domain_items[0].agol_value == "WellTypeDomain"
    assert domain_items[0].local_value is None


# ── DOMAIN_DRIFT: domain name mismatch ───────────────────────────────────────

def test_domain_drift_name_mismatch():
    agol = _agol(fields=[
        {"name": "OBJECTID",   "type": "esriFieldTypeOID",   "nullable": False, "domain": None},
        {"name": "LocationID", "type": "esriFieldTypeString", "nullable": True,  "domain": None},
        {"name": "WellType",   "type": "esriFieldTypeString", "nullable": True,
         "domain": {"type": "codedValue", "name": "WellType_RENAMED",
                    "codedValues": [{"code": "MW", "name": "Monitoring Well"},
                                    {"code": "SW", "name": "Surface Water"}]}},
    ])
    report = diff_schema(agol, _BASE_SPEC)
    domain_items = [d for d in report.drift_items if d.drift_type == DRIFT_DOMAIN_DRIFT]
    name_mismatches = [d for d in domain_items
                       if d.local_value == "WellTypeDomain"
                       and d.agol_value == "WellType_RENAMED"]
    assert len(name_mismatches) == 1


# ── DOMAIN_DRIFT: coded value missing from AGOL ──────────────────────────────

def test_domain_drift_coded_value_missing_from_agol():
    agol = _agol(fields=[
        {"name": "OBJECTID",   "type": "esriFieldTypeOID",   "nullable": False, "domain": None},
        {"name": "LocationID", "type": "esriFieldTypeString", "nullable": True,  "domain": None},
        {"name": "WellType",   "type": "esriFieldTypeString", "nullable": True,
         "domain": {"type": "codedValue", "name": "WellTypeDomain",
                    "codedValues": [{"code": "MW", "name": "Monitoring Well"}]}},
    ])
    report = diff_schema(agol, _BASE_SPEC)
    domain_items = [d for d in report.drift_items if d.drift_type == DRIFT_DOMAIN_DRIFT]
    missing_code = [d for d in domain_items
                    if "SW" in (d.message or "") and d.agol_value is None]
    assert len(missing_code) == 1
    assert missing_code[0].local_value is not None


# ── DOMAIN_DRIFT: coded value extra in AGOL ──────────────────────────────────

def test_domain_drift_coded_value_extra_in_agol():
    agol = _agol(fields=[
        {"name": "OBJECTID",   "type": "esriFieldTypeOID",   "nullable": False, "domain": None},
        {"name": "LocationID", "type": "esriFieldTypeString", "nullable": True,  "domain": None},
        {"name": "WellType",   "type": "esriFieldTypeString", "nullable": True,
         "domain": {"type": "codedValue", "name": "WellTypeDomain",
                    "codedValues": [{"code": "MW", "name": "Monitoring Well"},
                                    {"code": "SW", "name": "Surface Water"},
                                    {"code": "EW", "name": "Extraction Well"}]}},
    ])
    report = diff_schema(agol, _BASE_SPEC)
    domain_items = [d for d in report.drift_items if d.drift_type == DRIFT_DOMAIN_DRIFT]
    extra_code = [d for d in domain_items
                  if "EW" in (d.message or "") and d.local_value is None]
    assert len(extra_code) == 1
    assert extra_code[0].agol_value is not None


# ── DOMAIN_DRIFT: coded value label mismatch ─────────────────────────────────

def test_domain_drift_coded_value_label_mismatch():
    agol = _agol(fields=[
        {"name": "OBJECTID",   "type": "esriFieldTypeOID",   "nullable": False, "domain": None},
        {"name": "LocationID", "type": "esriFieldTypeString", "nullable": True,  "domain": None},
        {"name": "WellType",   "type": "esriFieldTypeString", "nullable": True,
         "domain": {"type": "codedValue", "name": "WellTypeDomain",
                    "codedValues": [{"code": "MW", "name": "Monitor Well"},
                                    {"code": "SW", "name": "Surface Water"}]}},
    ])
    report = diff_schema(agol, _BASE_SPEC)
    domain_items = [d for d in report.drift_items if d.drift_type == DRIFT_DOMAIN_DRIFT]
    label_mismatches = [d for d in domain_items
                        if "MW" in (d.message or "") and "name" in (d.message or "")]
    assert len(label_mismatches) == 1


# ── mixed drift ───────────────────────────────────────────────────────────────

def test_mixed_drift_types():
    """MISSING_FIELD + EXTRA_FIELD + TYPE_MISMATCH all in one pass."""
    spec = _spec(fields=[
        {"name": "OBJECTID",    "type": "esriFieldTypeOID"},
        {"name": "SampleDepth", "type": "esriFieldTypeDouble"},   # absent from AGOL
        {"name": "WellType",    "type": "esriFieldTypeInteger",   # type mismatch
         "domain": {"name": "WellTypeDomain",
                    "coded_values": [{"code": "MW", "name": "Monitoring Well"},
                                     {"code": "SW", "name": "Surface Water"}]}},
    ])
    agol = _agol(fields=[
        {"name": "OBJECTID", "type": "esriFieldTypeOID",     "nullable": False, "domain": None},
        {"name": "WellType", "type": "esriFieldTypeString",   "nullable": True,   # type mismatch vs spec
         "domain": {"type": "codedValue", "name": "WellTypeDomain",
                    "codedValues": [{"code": "MW", "name": "Monitoring Well"},
                                    {"code": "SW", "name": "Surface Water"}]}},
        {"name": "GlobalID", "type": "esriFieldTypeGlobalID", "nullable": False, "domain": None},
    ])
    report = diff_schema(agol, spec)
    types_found = {d.drift_type for d in report.drift_items}
    assert DRIFT_MISSING_FIELD in types_found
    assert DRIFT_EXTRA_FIELD   in types_found
    assert DRIFT_TYPE_MISMATCH in types_found


# ── SchemaDriftReport helpers ─────────────────────────────────────────────────

def test_drift_by_type_grouping():
    spec = _spec(fields=[
        {"name": "OBJECTID", "type": "esriFieldTypeOID"},
        {"name": "FieldA",   "type": "esriFieldTypeString"},
        {"name": "FieldB",   "type": "esriFieldTypeDouble"},
    ])
    agol = _agol(fields=[
        {"name": "OBJECTID", "type": "esriFieldTypeOID",     "nullable": False, "domain": None},
        {"name": "FieldA",   "type": "esriFieldTypeInteger",  "nullable": True,  "domain": None},
        {"name": "GlobalID", "type": "esriFieldTypeGlobalID", "nullable": False, "domain": None},
    ])
    report = diff_schema(agol, spec)
    by_type = report.drift_by_type
    assert len(by_type[DRIFT_MISSING_FIELD]) == 1
    assert len(by_type[DRIFT_EXTRA_FIELD])   == 1
    assert len(by_type[DRIFT_TYPE_MISMATCH]) == 1


def test_has_drift_false_when_clean():
    report = diff_schema(_BASE_AGOL, _BASE_SPEC)
    assert report.has_drift is False


def test_has_drift_true_when_dirty():
    spec = _spec(fields=_BASE_SPEC["fields"] + [
        {"name": "Missing", "type": "esriFieldTypeString"}
    ])
    assert diff_schema(_BASE_AGOL, spec).has_drift is True


# ── format_drift_report ───────────────────────────────────────────────────────

def test_format_report_clean():
    report = diff_schema(_BASE_AGOL, _BASE_SPEC)
    text = format_drift_report(report)
    assert "CLEAN" in text
    assert "No schema drift detected." in text
    assert "DRIFT DETECTED" not in text


def test_format_report_drift_detected():
    spec = _spec(fields=_BASE_SPEC["fields"] + [
        {"name": "SampleDepth_ft", "type": "esriFieldTypeDouble"}
    ])
    report = diff_schema(_BASE_AGOL, spec)
    text = format_drift_report(report)
    assert "DRIFT DETECTED" in text
    assert "MISSING_FIELD"   in text
    assert "SampleDepth_ft"  in text
    assert "CLEAN" not in text


def test_format_report_contains_layer_name():
    report = diff_schema(_BASE_AGOL, _BASE_SPEC)
    assert "MonitoringWells" in format_drift_report(report)


def test_format_report_shows_field_counts():
    report = diff_schema(_BASE_AGOL, _BASE_SPEC)
    text = format_drift_report(report)
    assert "3" in text   # 3 fields in both spec and AGOL
```

- [ ] **Step 2: Run tests to confirm they fail**

```
python -m pytest tests/test_audit_schema.py -v
```

Expected: `ImportError: cannot import name 'diff_schema' from 'autogis.core.agol.audit_schema'` (module does not exist yet).

- [ ] **Step 3: Create `autogis/core/agol/audit_schema.py`**

```python
"""AuditAGOLSchemaAgainstLocalConfig — headless diff core (Tool 6.6).

diff_schema() and format_drift_report() are arcpy-free and importable without
arcgis installed.  fetch_layer_schema() lazy-imports arcgis.features.FeatureLayer
and is marked ``# pragma: no cover`` — it is the seam between the headless diff
core and the live AGOL REST API.

Local spec format (YAML/JSON):
  layer_name: MonitoringWells
  fields:
    - name: LocationID
      type: esriFieldTypeString
      nullable: true
      domain:
        name: WellTypeDomain
        coded_values:          # snake_case key — AGOL REST uses "codedValues"
          - {code: "MW", name: "Monitoring Well"}
          - {code: "SW", name: "Surface Water"}

Fetched AGOL schema format (from FeatureLayer.properties):
  {"fields": [{"name": ..., "type": ..., "nullable": ...,
               "domain": {"name": ..., "codedValues": [...]}}]}
"""
from __future__ import annotations

import dataclasses
from typing import Dict, List, Optional

# ── drift type constants ──────────────────────────────────────────────────────
DRIFT_MISSING_FIELD     = "MISSING_FIELD"      # spec field absent from AGOL
DRIFT_EXTRA_FIELD       = "EXTRA_FIELD"        # AGOL field absent from spec
DRIFT_TYPE_MISMATCH     = "TYPE_MISMATCH"      # esriFieldType differs
DRIFT_DOMAIN_DRIFT      = "DOMAIN_DRIFT"       # domain name or coded values differ
DRIFT_NULLABLE_MISMATCH = "NULLABLE_MISMATCH"  # nullable flag differs

_ALL_DRIFT_TYPES = (
    DRIFT_MISSING_FIELD,
    DRIFT_EXTRA_FIELD,
    DRIFT_TYPE_MISMATCH,
    DRIFT_DOMAIN_DRIFT,
    DRIFT_NULLABLE_MISMATCH,
)


# ── data model ────────────────────────────────────────────────────────────────

@dataclasses.dataclass
class DriftItem:
    field_name:  str
    drift_type:  str            # one of the DRIFT_* constants above
    local_value: Optional[str]
    agol_value:  Optional[str]
    message:     str


@dataclasses.dataclass
class SchemaDriftReport:
    layer_name:        str
    total_agol_fields: int
    total_spec_fields: int
    drift_items:       List[DriftItem]

    @property
    def has_drift(self) -> bool:
        return bool(self.drift_items)

    @property
    def drift_by_type(self) -> Dict[str, List[DriftItem]]:
        result: Dict[str, List[DriftItem]] = {}
        for item in self.drift_items:
            result.setdefault(item.drift_type, []).append(item)
        return result


# ── headless diff ─────────────────────────────────────────────────────────────

def diff_schema(fetched_schema: dict, local_spec: dict) -> SchemaDriftReport:
    """Compare a fetched AGOL layer schema dict against a local spec dict.

    ``fetched_schema`` must contain a "fields" list in AGOL REST / arcgis SDK
    format (keys per field: name, type, nullable, domain).
    ``local_spec`` must contain "layer_name" and "fields" (see module docstring
    for the full spec format).  No arcgis or arcpy imports here.
    """
    layer_name = local_spec.get("layer_name", "")
    spec_fields: Dict[str, dict] = {
        f["name"]: f for f in local_spec.get("fields", [])
    }
    agol_fields: Dict[str, dict] = {
        f["name"]: f for f in fetched_schema.get("fields", [])
    }

    items: List[DriftItem] = []

    # MISSING_FIELD — in local spec, not in AGOL
    for name, sf in spec_fields.items():
        if name not in agol_fields:
            items.append(DriftItem(
                field_name=name,
                drift_type=DRIFT_MISSING_FIELD,
                local_value=sf.get("type"),
                agol_value=None,
                message=f"'{name}' defined in local spec but absent from AGOL layer",
            ))

    # EXTRA_FIELD — in AGOL, not in local spec
    for name, af in agol_fields.items():
        if name not in spec_fields:
            items.append(DriftItem(
                field_name=name,
                drift_type=DRIFT_EXTRA_FIELD,
                local_value=None,
                agol_value=af.get("type"),
                message=f"'{name}' present in AGOL layer but not declared in local spec",
            ))

    # Shared fields — check type, nullable, domain
    for name in spec_fields:
        if name not in agol_fields:
            continue   # already reported as MISSING_FIELD
        sf = spec_fields[name]
        af = agol_fields[name]

        # TYPE_MISMATCH
        st, at = sf.get("type"), af.get("type")
        if st and at and st != at:
            items.append(DriftItem(
                field_name=name,
                drift_type=DRIFT_TYPE_MISMATCH,
                local_value=st,
                agol_value=at,
                message=f"'{name}' type: local={st!r} agol={at!r}",
            ))

        # NULLABLE_MISMATCH — only checked when spec explicitly declares nullable
        if "nullable" in sf:
            an = af.get("nullable")
            if an is not None and sf["nullable"] != an:
                items.append(DriftItem(
                    field_name=name,
                    drift_type=DRIFT_NULLABLE_MISMATCH,
                    local_value=str(sf["nullable"]),
                    agol_value=str(an),
                    message=(f"'{name}' nullable: local={sf['nullable']} "
                             f"agol={an}"),
                ))

        # DOMAIN_DRIFT
        items.extend(_diff_domains(name, sf.get("domain"), af.get("domain")))

    return SchemaDriftReport(
        layer_name=layer_name,
        total_agol_fields=len(agol_fields),
        total_spec_fields=len(spec_fields),
        drift_items=items,
    )


def _diff_domains(
    field_name: str,
    spec_domain,
    agol_domain,
) -> List[DriftItem]:
    """Return DriftItems for domain-level differences between spec and AGOL."""
    items: List[DriftItem] = []
    if spec_domain is None and agol_domain is None:
        return items

    def _name(d) -> str:
        return d.get("name", "") if isinstance(d, dict) else str(d)

    if spec_domain is not None and agol_domain is None:
        items.append(DriftItem(
            field_name=field_name,
            drift_type=DRIFT_DOMAIN_DRIFT,
            local_value=_name(spec_domain),
            agol_value=None,
            message=(f"'{field_name}': local spec declares domain "
                     f"{_name(spec_domain)!r} but AGOL has none"),
        ))
        return items

    if spec_domain is None and agol_domain is not None:
        items.append(DriftItem(
            field_name=field_name,
            drift_type=DRIFT_DOMAIN_DRIFT,
            local_value=None,
            agol_value=_name(agol_domain),
            message=(f"'{field_name}': AGOL has domain "
                     f"{_name(agol_domain)!r} but local spec expects none"),
        ))
        return items

    # Both have domains — compare domain names
    sn = _name(spec_domain)
    an = _name(agol_domain)
    if sn and an and sn != an:
        items.append(DriftItem(
            field_name=field_name,
            drift_type=DRIFT_DOMAIN_DRIFT,
            local_value=sn,
            agol_value=an,
            message=f"'{field_name}' domain name: local={sn!r} agol={an!r}",
        ))

    # Compare coded values.
    # Local spec uses "coded_values" (snake_case); AGOL REST uses "codedValues".
    sd = spec_domain if isinstance(spec_domain, dict) else {}
    ad = agol_domain  if isinstance(agol_domain, dict) else {}
    spec_cvs: Dict[str, str] = {
        v["code"]: v["name"]
        for v in sd.get("coded_values", [])
        if isinstance(v, dict) and "code" in v
    }
    agol_cvs: Dict[str, str] = {
        v["code"]: v["name"]
        for v in ad.get("codedValues", [])
        if isinstance(v, dict) and "code" in v
    }

    for code, label in spec_cvs.items():
        if code not in agol_cvs:
            items.append(DriftItem(
                field_name=field_name,
                drift_type=DRIFT_DOMAIN_DRIFT,
                local_value=f"code={code!r} ({label!r})",
                agol_value=None,
                message=(f"'{field_name}' domain: coded value {code!r} "
                         f"in local spec but absent from AGOL"),
            ))
        elif spec_cvs[code] != agol_cvs[code]:
            items.append(DriftItem(
                field_name=field_name,
                drift_type=DRIFT_DOMAIN_DRIFT,
                local_value=f"code={code!r} name={label!r}",
                agol_value=f"code={code!r} name={agol_cvs[code]!r}",
                message=(f"'{field_name}' domain coded value {code!r} "
                         f"name mismatch: local={label!r} "
                         f"agol={agol_cvs[code]!r}"),
            ))

    for code, label in agol_cvs.items():
        if code not in spec_cvs:
            items.append(DriftItem(
                field_name=field_name,
                drift_type=DRIFT_DOMAIN_DRIFT,
                local_value=None,
                agol_value=f"code={code!r} ({label!r})",
                message=(f"'{field_name}' domain: coded value {code!r} "
                         f"in AGOL but absent from local spec"),
            ))

    return items


# ── report formatter ──────────────────────────────────────────────────────────

def format_drift_report(report: SchemaDriftReport) -> str:
    """Render a SchemaDriftReport as a human-readable text block."""
    status = "DRIFT DETECTED" if report.has_drift else "CLEAN"
    lines = [
        f"Schema Audit Report  [{status}]  Layer: {report.layer_name}",
        f"AGOL fields: {report.total_agol_fields}  "
        f"Spec fields: {report.total_spec_fields}  "
        f"Drift items: {len(report.drift_items)}",
        "",
    ]
    if not report.has_drift:
        lines.append("No schema drift detected.")
    else:
        by_type = report.drift_by_type
        for dtype in _ALL_DRIFT_TYPES:
            d_items = by_type.get(dtype, [])
            if d_items:
                lines.append(f"\n{dtype} ({len(d_items)})")
                lines.append("-" * 60)
                for di in d_items:
                    lines.append(f"  {di.field_name}: {di.message}")
    return "\n".join(lines)


# ── AGOL fetch seam ───────────────────────────────────────────────────────────

def fetch_layer_schema(  # pragma: no cover
    gis,
    *,
    layer_url: Optional[str] = None,
    item_id:   Optional[str] = None,
    layer_index: int = 0,
) -> dict:
    """Fetch the layer schema dict from AGOL via the arcgis SDK.

    Exactly one of ``layer_url`` or ``item_id`` must be provided.
    Returns the raw layer properties dict, which has a "fields" list.

    Lazy: ``arcgis.features`` is imported only here — this module stays
    importable without the arcgis package installed.  Called by the CLI
    command; never called in headless tests.
    """
    from arcgis.features import FeatureLayer  # type: ignore[import]

    if item_id and not layer_url:
        item = gis.content.get(item_id)
        if item is None:
            raise ValueError(f"AGOL item {item_id!r} not found in this GIS")
        layer_url = item.layers[layer_index].url
    if not layer_url:
        raise ValueError("Provide layer_url or item_id")
    return dict(FeatureLayer(layer_url, gis).properties)
```

- [ ] **Step 4: Run tests to confirm they pass**

```
python -m pytest tests/test_audit_schema.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Run full suite to confirm no regressions**

```
python -m pytest -q
```

Expected: existing count + new tests, all green.

- [ ] **Step 6: Commit**

```bash
git add autogis/core/agol/audit_schema.py tests/test_audit_schema.py
git commit -m "feat(agol): audit_schema — headless AGOL schema diff core (Tool 6.6)"
```

---

### Task 2: CLI command + example spec

**Files:**
- Modify: `autogis/adapters/cli.py` — add `audit-schema` command under `agol` group
- Create: `autogis/config/layer_schema_specs/example_monitoring_wells.yaml`
- Create: `tests/test_cli_audit_schema.py`

**Interfaces:**
- Consumes from Task 1: `diff_schema`, `format_drift_report`, `fetch_layer_schema`, `DriftItem`, `SchemaDriftReport`
- Consumes existing: `agol_from_profile` (already imported at top of `cli.py`), `load_config` (from `autogis.core.common.config`)

- [ ] **Step 1: Write failing CLI tests**

Create `tests/test_cli_audit_schema.py`:

```python
"""CLI tests for ``agol audit-schema`` (monkeypatched — no live AGOL)."""
import json

import pytest
from click.testing import CliRunner

from autogis.adapters.cli import autogis

# ── shared fixture data ───────────────────────────────────────────────────────

_SPEC_YAML = """\
layer_name: TestLayer
fields:
  - name: OBJECTID
    type: esriFieldTypeOID
  - name: LocationID
    type: esriFieldTypeString
    nullable: true
"""

_SCHEMA_CLEAN = {
    "name": "TestLayer",
    "fields": [
        {"name": "OBJECTID",   "type": "esriFieldTypeOID",    "nullable": False, "domain": None},
        {"name": "LocationID", "type": "esriFieldTypeString",  "nullable": True,  "domain": None},
    ],
}

_SCHEMA_DRIFT = {
    "name": "TestLayer",
    "fields": [
        {"name": "OBJECTID",   "type": "esriFieldTypeOID",     "nullable": False, "domain": None},
        {"name": "LocationID", "type": "esriFieldTypeInteger",  "nullable": True,  "domain": None},
    ],
}


# ── helpers ───────────────────────────────────────────────────────────────────

def _invoke(args, spec_content=_SPEC_YAML, monkeypatch=None,
            fetched=_SCHEMA_CLEAN, tmp_path=None):
    spec_file = tmp_path / "spec.yaml"
    spec_file.write_text(spec_content, encoding="utf-8")
    if monkeypatch is not None:
        monkeypatch.setattr(
            "autogis.core.agol.audit_schema.fetch_layer_schema",
            lambda gis, **kw: fetched,
        )
        monkeypatch.setattr(
            "autogis.adapters.cli.agol_from_profile",
            lambda profile: object(),
        )
    return CliRunner().invoke(
        autogis,
        ["agol", "audit-schema", "--spec", str(spec_file)] + args,
    )


# ── discoverability ───────────────────────────────────────────────────────────

def test_audit_schema_in_agol_help():
    result = CliRunner().invoke(autogis, ["agol", "--help"])
    assert "audit-schema" in result.output


# ── clean result ──────────────────────────────────────────────────────────────

def test_audit_schema_clean_output(tmp_path, monkeypatch):
    result = _invoke(
        ["--layer-url", "https://fake/FeatureServer/0"],
        fetched=_SCHEMA_CLEAN,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
    )
    assert result.exit_code == 0, result.output
    assert "CLEAN" in result.output


# ── drift detected ────────────────────────────────────────────────────────────

def test_audit_schema_drift_output(tmp_path, monkeypatch):
    result = _invoke(
        ["--layer-url", "https://fake/FeatureServer/0"],
        fetched=_SCHEMA_DRIFT,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
    )
    assert result.exit_code == 0, result.output
    assert "DRIFT DETECTED" in result.output
    assert "TYPE_MISMATCH"  in result.output


def test_audit_schema_fail_on_drift_exits_1(tmp_path, monkeypatch):
    result = _invoke(
        ["--layer-url", "https://fake/FeatureServer/0", "--fail-on-drift"],
        fetched=_SCHEMA_DRIFT,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
    )
    assert result.exit_code == 1


def test_audit_schema_clean_no_fail_on_drift_exits_0(tmp_path, monkeypatch):
    result = _invoke(
        ["--layer-url", "https://fake/FeatureServer/0", "--fail-on-drift"],
        fetched=_SCHEMA_CLEAN,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
    )
    assert result.exit_code == 0


# ── output formats ────────────────────────────────────────────────────────────

def test_audit_schema_json_format(tmp_path, monkeypatch):
    result = _invoke(
        ["--layer-url", "https://fake/FeatureServer/0",
         "--format", "json"],
        fetched=_SCHEMA_DRIFT,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["layer_name"]  == "TestLayer"
    assert data["has_drift"]   is True
    assert len(data["drift_items"]) >= 1
    # each item has the expected keys
    item = data["drift_items"][0]
    assert "field_name"  in item
    assert "drift_type"  in item
    assert "local_value" in item
    assert "agol_value"  in item
    assert "message"     in item


def test_audit_schema_csv_format(tmp_path, monkeypatch):
    result = _invoke(
        ["--layer-url", "https://fake/FeatureServer/0",
         "--format", "csv"],
        fetched=_SCHEMA_DRIFT,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
    )
    assert result.exit_code == 0, result.output
    assert "field_name" in result.output   # CSV header row
    assert "TYPE_MISMATCH" in result.output


def test_audit_schema_output_to_file(tmp_path, monkeypatch):
    out_file = tmp_path / "report.txt"
    result = _invoke(
        ["--layer-url", "https://fake/FeatureServer/0",
         "--output", str(out_file)],
        fetched=_SCHEMA_DRIFT,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
    )
    assert result.exit_code == 0, result.output
    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    assert "DRIFT DETECTED" in content


# ── error handling ────────────────────────────────────────────────────────────

def test_audit_schema_requires_layer_url_or_item_id(tmp_path, monkeypatch):
    """Both --layer-url and --item-id omitted must produce a UsageError."""
    monkeypatch.setattr(
        "autogis.adapters.cli.agol_from_profile",
        lambda profile: object(),
    )
    spec_file = tmp_path / "spec.yaml"
    spec_file.write_text(_SPEC_YAML, encoding="utf-8")
    result = CliRunner().invoke(
        autogis,
        ["agol", "audit-schema", "--spec", str(spec_file)],
    )
    assert result.exit_code != 0


def test_audit_schema_uses_item_id(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "autogis.core.agol.audit_schema.fetch_layer_schema",
        lambda gis, **kw: _SCHEMA_CLEAN,
    )
    monkeypatch.setattr(
        "autogis.adapters.cli.agol_from_profile",
        lambda profile: object(),
    )
    spec_file = tmp_path / "spec.yaml"
    spec_file.write_text(_SPEC_YAML, encoding="utf-8")
    result = CliRunner().invoke(
        autogis,
        ["agol", "audit-schema",
         "--spec", str(spec_file),
         "--item-id", "abc123def456",
         "--layer-index", "0"],
    )
    assert result.exit_code == 0, result.output
    assert "CLEAN" in result.output
```

- [ ] **Step 2: Run CLI tests to confirm they fail**

```
python -m pytest tests/test_cli_audit_schema.py -v
```

Expected: most fail with `AssertionError: "audit-schema" not in output` because the command is not registered yet.

- [ ] **Step 3: Add `audit-schema` command to `cli.py`**

In `autogis/adapters/cli.py`, add the following block immediately after the existing `publish-layer` command definition (after line ~1265, before the `validate-rtk-survey` block):

```python
@agol.command("audit-schema")
@click.option("--spec", "spec_path", required=True, type=click.Path(exists=True),
              help="Path to local layer schema spec (YAML/JSON).")
@click.option("--layer-url", default=None,
              help="Full AGOL FeatureLayer REST URL.")
@click.option("--item-id", default=None,
              help="AGOL item ID (use with --layer-index when item has multiple layers).")
@click.option("--layer-index", type=int, default=0, show_default=True,
              help="Layer index within the item (0-based).")
@click.option("--profile", default=None,
              help="ArcGIS API for Python profile name.")
@click.option("--output", default=None, type=click.Path(),
              help="Write report to this file path (stdout if omitted).")
@click.option("--format", "fmt",
              type=click.Choice(["text", "csv", "json"]), default="text",
              show_default=True, help="Output format.")
@click.option("--fail-on-drift", is_flag=True, default=False,
              help="Exit with status 1 if any drift is detected.")
def audit_schema_cmd(spec_path, layer_url, item_id, layer_index, profile,
                     output, fmt, fail_on_drift):
    """Compare a hosted AGOL feature layer schema against a local spec (HYBRID)."""
    import csv as _csv
    import dataclasses
    import io
    import json as _json

    from autogis.core.agol.audit_schema import (
        DriftItem,
        diff_schema,
        fetch_layer_schema,
        format_drift_report,
    )
    from autogis.core.common.config import load_config

    if not layer_url and not item_id:
        raise click.UsageError("Provide --layer-url or --item-id.")

    local_spec = load_config(Path(spec_path))
    gis = agol_from_profile(profile)
    fetched_schema = fetch_layer_schema(
        gis,
        layer_url=layer_url,
        item_id=item_id,
        layer_index=layer_index,
    )
    report = diff_schema(fetched_schema, local_spec)

    if fmt == "text":
        content = format_drift_report(report)
    elif fmt == "json":
        content = _json.dumps(
            {
                "layer_name":        report.layer_name,
                "total_agol_fields": report.total_agol_fields,
                "total_spec_fields": report.total_spec_fields,
                "has_drift":         report.has_drift,
                "drift_items":       [dataclasses.asdict(d) for d in report.drift_items],
            },
            indent=2,
        )
    else:  # csv
        buf = io.StringIO()
        cols = [f.name for f in dataclasses.fields(DriftItem)]
        w = _csv.DictWriter(buf, fieldnames=cols)
        w.writeheader()
        for d in report.drift_items:
            w.writerow(dataclasses.asdict(d))
        content = buf.getvalue()

    if output:
        Path(output).write_text(content, encoding="utf-8")
        click.echo(
            f"Report written: {output}  "
            f"({'DRIFT' if report.has_drift else 'CLEAN'})"
        )
    else:
        click.echo(content)

    if fail_on_drift and report.has_drift:
        raise SystemExit(1)
```

- [ ] **Step 4: Create example layer schema spec**

Create `autogis/config/layer_schema_specs/example_monitoring_wells.yaml`:

```yaml
# Example layer schema spec for AuditAGOLSchemaAgainstLocalConfig (Tool 6.6).
# Usage:
#   autogis agol audit-schema \
#     --spec autogis/config/layer_schema_specs/example_monitoring_wells.yaml \
#     --item-id <your-agol-item-id> \
#     --profile <your-arcgis-profile>
#
# Field types must use AGOL/ArcGIS REST esriFieldType strings.
# Domains use "coded_values" (snake_case) — NOT the camelCase "codedValues"
# from the AGOL REST API; the tool normalises the difference automatically.

layer_name: MonitoringWells

fields:
  - name: OBJECTID
    type: esriFieldTypeOID

  - name: LocationID
    type: esriFieldTypeString
    nullable: false

  - name: WellName
    type: esriFieldTypeString
    nullable: true

  - name: WellType
    type: esriFieldTypeString
    nullable: true
    domain:
      name: WellTypeDomain
      coded_values:
        - {code: "MW",  name: "Monitoring Well"}
        - {code: "EW",  name: "Extraction Well"}
        - {code: "IW",  name: "Injection Well"}
        - {code: "SW",  name: "Surface Water"}
        - {code: "BLC", name: "Blank"}

  - name: TopOfCasing_ft
    type: esriFieldTypeDouble
    nullable: true

  - name: GroundSurface_ft
    type: esriFieldTypeDouble
    nullable: true

  - name: TotalDepth_ft
    type: esriFieldTypeDouble
    nullable: true

  - name: ScreenTop_ft
    type: esriFieldTypeDouble
    nullable: true

  - name: ScreenBottom_ft
    type: esriFieldTypeDouble
    nullable: true

  - name: Status
    type: esriFieldTypeString
    nullable: true
    domain:
      name: WellStatusDomain
      coded_values:
        - {code: "Active",       name: "Active"}
        - {code: "Abandoned",    name: "Abandoned"}
        - {code: "Destroyed",    name: "Destroyed"}
        - {code: "NotInstalled", name: "Not Installed"}

  - name: InstallDate
    type: esriFieldTypeDate
    nullable: true

  - name: Notes
    type: esriFieldTypeString
    nullable: true
```

- [ ] **Step 5: Run CLI tests to confirm they pass**

```
python -m pytest tests/test_cli_audit_schema.py -v
```

Expected: all tests PASS.

- [ ] **Step 6: Run full suite to confirm no regressions**

```
python -m pytest -q
```

Expected: all green, count rises by the new test count.

- [ ] **Step 7: Commit**

```bash
git add autogis/adapters/cli.py \
        tests/test_cli_audit_schema.py \
        autogis/config/layer_schema_specs/example_monitoring_wells.yaml
git commit -m "feat(agol): audit-schema CLI command — AGOL schema drift report (Tool 6.6)"
```

---

## Self-Review

### Spec coverage

| Requirement | Covered by |
|---|---|
| Headless diff core (no arcgis/arcpy at import) | `audit_schema.py` — zero top-level arcgis import |
| Takes already-fetched schema dict | `diff_schema(fetched_schema, local_spec)` — pure dict in |
| arcgis fetch behind the seam | `fetch_layer_schema()` — `# pragma: no cover`, lazy import |
| MISSING_FIELD drift | `test_missing_field_detected` + `test_mixed_drift_types` |
| EXTRA_FIELD drift | `test_extra_field_detected` + `test_mixed_drift_types` |
| TYPE_MISMATCH drift | `test_type_mismatch_detected` |
| DOMAIN_DRIFT | 5 domain tests covering all sub-cases |
| NULLABLE_MISMATCH | `test_nullable_mismatch_detected` |
| Output report format (text/csv/json) | `format_drift_report` + CLI `--format` option |
| CLI surface (`agol audit-schema`) | Task 2; tested in `test_cli_audit_schema.py` |
| `--fail-on-drift` exit code | `test_audit_schema_fail_on_drift_exits_1` |
| `--item-id` + `--layer-index` path | `test_audit_schema_uses_item_id` |
| `SiteConfig` canonical in `core/common/config.py` | Local spec loaded via `load_config()` — no SiteConfig changes |
| TDD order | All test files written in Step 1 before implementation in Step 3 |

### Placeholder scan

No "TBD", "TODO", "implement later", "add appropriate error handling", or similar phrases present. All test functions contain complete assertions. All implementation steps show complete code.

### Type consistency

- `DriftItem` defined once in Task 1 `audit_schema.py`; used by name in Task 2 CLI code (`from autogis.core.agol.audit_schema import DriftItem`) — exact match.
- `SchemaDriftReport` defined once; referenced as return type of `diff_schema()` everywhere.
- `fetch_layer_schema(gis, *, layer_url=None, item_id=None, layer_index=0)` — signature in `audit_schema.py` and the CLI call `fetch_layer_schema(gis, layer_url=layer_url, item_id=item_id, layer_index=layer_index)` — exact match.
- `format_drift_report(report: SchemaDriftReport) -> str` — imported and called with a `SchemaDriftReport` instance throughout.

---

## Assumptions and design notes

- **Local spec format** — a standalone YAML/JSON file (not embedded in `SiteConfig`). This keeps the spec versionable alongside GIS data without inflating the main site config. Pass it to the CLI via `--spec`.
- **`coded_values` vs `codedValues`** — The local spec uses snake_case (`coded_values`) matching Python conventions; AGOL REST JSON uses camelCase (`codedValues`). `_diff_domains()` handles both sides of this mapping. This is documented in the module docstring.
- **`OBJECTID` and system-managed fields** — The diff checks all fields including OBJECTID. If you want to skip system fields (OBJECTID, Shape, Shape_Length, Shape_Area, GlobalID, created_date, etc.), omit them from the local spec. EXTRA_FIELD drift items will still be reported for any AGOL system fields not declared in the spec.
- **No `capabilities.py` / Runtime guard** — The `agol` group has no LOCAL-only guard mechanism analogous to `_guard()` for arcpy tools. Like `publish-layer`, this command fails naturally with an `ImportError` if `arcgis` is absent when `agol_from_profile()` is called. This matches the project's existing HYBRID pattern.
- **Range domains** — The current implementation compares coded-value domains only. Range domains (esriRangeDomain) in AGOL will produce a DOMAIN_DRIFT item reporting "AGOL has domain X but local spec expects none" if the spec field has no `domain` key. To declare a range domain in the spec, add a `domain` key with no `coded_values` — the tool will only check the name, not the min/max. Full range-domain comparison is a future extension.
