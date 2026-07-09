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

from ._sublayers import resolve_sublayer

# -- drift type constants ------------------------------------------------------
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


# -- data model ----------------------------------------------------------------

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


# -- headless diff ---------------------------------------------------------------

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

    # MISSING_FIELD -- in local spec, not in AGOL
    for name, sf in spec_fields.items():
        if name not in agol_fields:
            items.append(DriftItem(
                field_name=name,
                drift_type=DRIFT_MISSING_FIELD,
                local_value=sf.get("type"),
                agol_value=None,
                message=f"'{name}' defined in local spec but absent from AGOL layer",
            ))

    # EXTRA_FIELD -- in AGOL, not in local spec
    for name, af in agol_fields.items():
        if name not in spec_fields:
            items.append(DriftItem(
                field_name=name,
                drift_type=DRIFT_EXTRA_FIELD,
                local_value=None,
                agol_value=af.get("type"),
                message=f"'{name}' present in AGOL layer but not declared in local spec",
            ))

    # Shared fields -- check type, nullable, domain
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

        # NULLABLE_MISMATCH -- only checked when spec explicitly declares nullable
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

    # Both have domains -- compare domain names
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


# -- report formatter -----------------------------------------------------------

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


# -- AGOL fetch seam -------------------------------------------------------------

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

    ``layer_index`` is AGOL's REST sublayer id, matched across the item's
    layers AND tables via ``resolve_sublayer`` (see ``_sublayers.py``) -- not
    a positional index into ``item.layers``.

    Lazy: ``arcgis.features`` is imported only here -- this module stays
    importable without the arcgis package installed.  Called by the CLI
    command; the live arcgis fetch is never exercised in headless tests
    (sublayer resolution itself is covered via fakes in ``_sublayers``).
    """
    from arcgis.features import FeatureLayer  # type: ignore[import]

    if item_id and not layer_url:
        item = gis.content.get(item_id)
        if item is None:
            raise ValueError(f"AGOL item {item_id!r} not found in this GIS")
        layer_url = resolve_sublayer(item, layer_index, item_id).url
    if not layer_url:
        raise ValueError("Provide layer_url or item_id")
    return dict(FeatureLayer(layer_url, gis).properties)