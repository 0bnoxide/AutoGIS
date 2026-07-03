"""Field Maps monitoring project plan (Tool 7.1).

``plan_fieldmaps_project()`` is arcpy-free: it derives the six canonical
Field Maps layers and their editable field schema from a site config (plus
``analyte_groups`` merged in from an event config, if any).
``provision_fieldmaps_layers()`` is the thin arcpy shell that creates or
refreshes those layers in a file GDB; publishing the GDB to Field Maps is
the shipped ``agol publish-layer`` tool's job (6.1), not duplicated here.

Editable field names deliberately match what RouteSurvey123Submission
(7.1b, ``normalize_survey123.Survey123Field`` defaults) reads from
collection payloads — ``SamplingDate`` / ``SampledBy`` / ``DepthToWater_ft``
/ ``COCNumber`` / ``Matrix`` — NOT the 2026-06-28 spec's prose names
(``SampleDate`` / ``Sampler`` / ``DTW``). See ADR-0043.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from ..common.qa import QACollector, SEV_INFO, SEV_WARNING


@dataclass
class FieldDef:
    name: str
    field_type: str            # text | date | double | short
    domain: Optional[str] = None
    editable: bool = True      # crew-editable in the Field Maps form.
    # ``editable`` is plan metadata: a file GDB cannot enforce it; it is
    # applied when configuring the Field Maps form / hosted layer.


@dataclass
class LayerPlan:
    name: str                  # MonitoringWells, SampleStatus, ...
    geometry: str              # point | none (none = standalone table)
    fields: List[FieldDef]


# Coded-value domains referenced by FieldDef.domain; the provisioning
# shell creates any that are missing in the target GDB.
DOMAINS: Dict[str, Dict[str, str]] = {
    "YesNo": {"0": "No", "1": "Yes"},
    "WellCondition": {c: c for c in
                      ("Good", "Fair", "Damaged", "Inaccessible")},
}


def _status_field_name(group: str) -> str:
    return ("Status_" + re.sub(r"[^A-Za-z0-9]+", "_", group).strip("_"))[:64]


def _well_id(editable: bool = True) -> FieldDef:
    return FieldDef("WellID", "text", editable=editable)


def plan_fieldmaps_project(site_config: dict) -> List[LayerPlan]:
    """Derive the required Field Maps layers + editable field schema from
    site config. Arcpy-free.

    Keys used: ``monitoring_wells_fc`` (wells layer name, default
    MonitoringWells) and ``analyte_groups`` (one Status_<group> field per
    group on SampleStatus — merge the event config in to supply it).
    """
    visit_fields = [
        FieldDef("Sampled", "short", domain="YesNo"),
        FieldDef("SamplingDate", "date"),
        FieldDef("SampledBy", "text"),
        FieldDef("COCNumber", "text"),
        FieldDef("Matrix", "text"),
        FieldDef("DepthToWater_ft", "double"),
        FieldDef("PurgeVolume", "double"),
        FieldDef("AccessIssue", "text"),
        FieldDef("WellCondition", "text", domain="WellCondition"),
        FieldDef("PhotoRequired", "short", domain="YesNo"),
        FieldDef("Notes", "text"),
    ]
    status_fields = [FieldDef(_status_field_name(g), "text")
                     for g in site_config.get("analyte_groups", {})]

    return [
        LayerPlan(site_config.get("monitoring_wells_fc", "MonitoringWells"),
                  "point",
                  [_well_id(editable=False),
                   FieldDef("SiteID", "text", editable=False)] + visit_fields),
        LayerPlan("SampleStatus", "none",
                  [_well_id(), FieldDef("SampleID", "text"),
                   FieldDef("Sampled", "short", domain="YesNo"),
                   FieldDef("SamplingDate", "date")] + status_fields),
        LayerPlan("WaterLevels", "none",
                  [_well_id(), FieldDef("MeasurementDate", "date"),
                   FieldDef("DepthToWater_ft", "double"),
                   FieldDef("MeasuredBy", "text")]),
        LayerPlan("AccessNotes", "point",
                  [_well_id(), FieldDef("AccessIssue", "text"),
                   FieldDef("Notes", "text")]),
        LayerPlan("PhotoPoints", "point",
                  [_well_id(), FieldDef("PhotoDate", "date"),
                   FieldDef("Notes", "text")]),
        LayerPlan("IssueFlags", "point",
                  [_well_id(), FieldDef("IssueType", "text"),
                   FieldDef("Resolved", "short", domain="YesNo"),
                   FieldDef("Notes", "text")]),
    ]


_ARC_TYPE = {"text": "TEXT", "date": "DATE", "double": "DOUBLE",
             "short": "SHORT"}


def provision_fieldmaps_layers(
    gdb: Path,
    plans: List[LayerPlan],
    qa: QACollector,
    *,
    spatial_reference: Optional[str] = None,
) -> int:
    """Create/refresh the planned layers, fields and domains in *gdb*
    (ArcGIS Pro). Refresh is additive: existing layers keep their data and
    only missing fields are added. Returns the number of layers touched.
    """
    from ...runtime.sessions import arcpy_env as _arcpy
    arcpy = _arcpy()
    gdb_s = str(gdb)

    sr = arcpy.SpatialReference(spatial_reference) if spatial_reference else None
    if sr is None and any(p.geometry != "none" for p in plans):
        qa.add(SEV_WARNING, "unknown_crs",
               "No spatial reference supplied; point layers are created "
               "with an unknown CRS. Set coordinate_system in the site "
               "config before publishing.")

    # Domains: create any referenced domain missing from the GDB.
    domain_types: Dict[str, str] = {}
    for plan in plans:
        for fd in plan.fields:
            if fd.domain:
                domain_types.setdefault(fd.domain, _ARC_TYPE[fd.field_type])
    existing_domains = {d.name for d in arcpy.da.ListDomains(gdb_s)}
    for name in sorted(set(domain_types) - existing_domains):
        arcpy.management.CreateDomain(gdb_s, name, name,
                                      domain_types[name], "CODED")
        for code, label in DOMAINS.get(name, {}).items():
            arcpy.management.AddCodedValueToDomain(gdb_s, name, code, label)

    touched = 0
    for plan in plans:
        target = str(Path(gdb) / plan.name)
        if not arcpy.Exists(target):
            if plan.geometry == "none":
                arcpy.management.CreateTable(gdb_s, plan.name)
            else:
                arcpy.management.CreateFeatureclass(
                    gdb_s, plan.name, geometry_type=plan.geometry.upper(),
                    spatial_reference=sr)
            qa.add(SEV_INFO, "layer_created",
                   f"Created {plan.name} ({plan.geometry}).")
        existing_fields = {f.name.upper() for f in arcpy.ListFields(target)}
        for fd in plan.fields:
            if fd.name.upper() in existing_fields:
                continue
            arcpy.management.AddField(target, fd.name,
                                      _ARC_TYPE[fd.field_type],
                                      field_alias=fd.name,
                                      field_domain=fd.domain or "")
        touched += 1
    return touched
