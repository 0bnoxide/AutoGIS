"""FieldMapsSyncPreflight — read-only sync preflight core (Tool 7.5, Phase 9).

All ``check_*`` functions plus ``build_preflight_report()`` /
``format_preflight_report()`` are pure — arcpy-free AND arcgis-free.  The
``fetch_*`` seams lazy-import arcgis and are ``# pragma: no cover``, matching
the ``audit_schema`` / ``sync_layer`` seam pattern.

READ-ONLY guarantee (the Phase 9 gate's "without changing either side"):
every seam call is a properties read, query, or replica/attachment listing —
nothing in this module writes to the hosted service or to any local data.

Slice 1 (ADR-0111) is headless: the local side of the duplicate/conflict
checks comes from a CSV snapshot (e.g. ``agol sync-to-gdb --out-csv``), not
live FGDB reads.  The arcpy FGDB leg ("pending local edits" read directly
from a Field Maps offline GDB) is deferred to a later slice.

Verified API surfaces (cited in ADR-0111): service-level ``syncEnabled`` /
``syncCapabilities`` / ``editorTrackingInfo`` / ``capabilities``; layer-level
``globalIdField`` / ``hasAttachments`` / ``editFieldsInfo``; replica info
``creationDate`` / ``lastSyncDate`` (epoch ms); SDK ``flc.replicas.get_list()``
/ ``.get(id)`` and ``AttachmentManager.search()``.
"""
from __future__ import annotations

import dataclasses
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from ..common.qa import SEV_INFO, SEV_WARNING
from ._sublayers import resolve_sublayer
from .audit_schema import SchemaDriftReport
from .sync_layer import _is_system_field

_MS_PER_DAY = 86_400_000
_MAX_LISTED = 20  # per-check cap on itemized findings; the rest aggregate

# Fixed section order for the report formatter.
CHECKS = (
    ("sync_config",  "Sync configuration"),
    ("hosted_edits", "Pending hosted edits"),
    ("replica_age",  "Replica / offline-area age"),
    ("schema_drift", "Schema drift"),
    ("duplicates",   "Duplicate identities"),
    ("conflicts",    "Conflict candidates"),
    ("attachments",  "Attachments"),
)


# -- data model ----------------------------------------------------------------

@dataclasses.dataclass
class PreflightFinding:
    check:    str   # one of the CHECKS keys
    severity: str   # SEV_INFO | SEV_WARNING
    subject:  str   # key / field / replica the finding is about ("" = aggregate)
    message:  str


@dataclasses.dataclass
class PreflightReport:
    item_id:    str
    layer_name: str
    checks_run: List[str]
    findings:   List[PreflightFinding]

    @property
    def warnings(self) -> List[PreflightFinding]:
        return [f for f in self.findings if f.severity == SEV_WARNING]

    @property
    def has_warnings(self) -> bool:
        return bool(self.warnings)


# -- pure checks ---------------------------------------------------------------

def edit_date_field(layer_props: dict) -> str:
    """The layer's editor-tracking edit-date field name.

    Read from ``editFieldsInfo.editDateField``; falls back to ``EditDate``
    (the AGOL hosted-layer default that Tool 6.2 already assumes).
    """
    return (layer_props.get("editFieldsInfo") or {}).get("editDateField") \
        or "EditDate"


def check_sync_config(service_props: dict, layer_props: dict,
                      ) -> List[PreflightFinding]:
    """Service/layer settings a Field Maps sync workflow depends on."""
    out: List[PreflightFinding] = []

    def add(sev, subject, msg):
        out.append(PreflightFinding("sync_config", sev, subject, msg))

    if not service_props.get("syncEnabled"):
        add(SEV_WARNING, "syncEnabled",
            "sync is not enabled on this service - offline areas and "
            "Field Maps sync will fail")
    caps = [c.strip() for c in
            str(service_props.get("capabilities", "")).split(",")]
    if service_props.get("syncEnabled") and "Sync" not in caps:
        add(SEV_WARNING, "capabilities",
            "syncEnabled is true but 'Sync' is missing from the "
            "capabilities string - inconsistent service state")
    tracking = service_props.get("editorTrackingInfo") or {}
    if not tracking.get("enableEditorTracking"):
        add(SEV_WARNING, "editorTrackingInfo",
            "editor tracking is disabled - pending-edit detection "
            "(EditDate cutoffs) cannot work")
    if not layer_props.get("globalIdField"):
        add(SEV_WARNING, "globalIdField",
            "layer has no globalIdField - identity matching between "
            "hosted and local records is impossible")
    if not layer_props.get("hasAttachments"):
        add(SEV_INFO, "hasAttachments",
            "layer has attachments disabled - attachment checks not "
            "applicable")
    if not out:
        add(SEV_INFO, "", "sync configuration OK")
    return out


def check_pending_hosted_edits(records: Sequence[dict],
                               *, since: Optional[str] = None,
                               ) -> List[PreflightFinding]:
    """Summarize the hosted records fetched under the edit-date cutoff."""
    if since:
        msg = (f"{len(records)} hosted record(s) edited since {since}"
               if records else f"no hosted edits since {since}")
    else:
        msg = (f"{len(records)} hosted record(s) fetched (no --since "
               f"watermark - counts cover the whole layer, not pending "
               f"edits)")
    return [PreflightFinding("hosted_edits", SEV_INFO, "", msg)]


def check_replica_age(replicas: Sequence[dict], *, now_ms: int,
                      max_age_days: float) -> List[PreflightFinding]:
    """Age each replica/offline area from lastSyncDate (or creationDate).

    Replica info dates are unix epoch milliseconds per the REST replica-info
    resource.  A replica with neither date is itself a warning.
    """
    if not replicas:
        return [PreflightFinding("replica_age", SEV_INFO, "",
                                 "no replicas / offline areas registered")]
    out: List[PreflightFinding] = []
    for rep in replicas:
        name = str(rep.get("replicaName") or rep.get("replicaID")
                   or rep.get("replicaId") or "<unnamed>")
        last = rep.get("lastSyncDate") or rep.get("creationDate")
        if not last:
            out.append(PreflightFinding(
                "replica_age", SEV_WARNING, name,
                f"replica '{name}' has no lastSyncDate/creationDate - "
                f"age unknown"))
            continue
        age_days = (now_ms - int(last)) / _MS_PER_DAY
        basis = "last sync" if rep.get("lastSyncDate") else "creation"
        if age_days > max_age_days:
            out.append(PreflightFinding(
                "replica_age", SEV_WARNING, name,
                f"replica '{name}' is {age_days:.1f} day(s) old "
                f"({basis}) - exceeds --max-replica-age-days "
                f"{max_age_days:g}"))
        else:
            out.append(PreflightFinding(
                "replica_age", SEV_INFO, name,
                f"replica '{name}' age {age_days:.1f} day(s) ({basis})"))
    return out


def drift_findings(report: SchemaDriftReport) -> List[PreflightFinding]:
    """Adapt an audit_schema SchemaDriftReport into preflight findings."""
    if not report.has_drift:
        return [PreflightFinding("schema_drift", SEV_INFO, "",
                                 "no schema drift against the local spec")]
    return [PreflightFinding("schema_drift", SEV_WARNING,
                             d.field_name, f"{d.drift_type}: {d.message}")
            for d in report.drift_items]


def check_duplicate_identities(records: Sequence[dict],
                               *, key_field: str = "GlobalID",
                               ) -> List[PreflightFinding]:
    """Duplicate or missing identity keys in the hosted record set."""
    counts: Dict[str, int] = {}
    blanks = 0
    for rec in records:
        key = rec.get(key_field)
        if key in (None, ""):
            blanks += 1
        else:
            counts[str(key)] = counts.get(str(key), 0) + 1
    out: List[PreflightFinding] = []
    if blanks:
        out.append(PreflightFinding(
            "duplicates", SEV_WARNING, "",
            f"{blanks} hosted record(s) have no {key_field} value"))
    dups = sorted(k for k, n in counts.items() if n > 1)
    for key in dups[:_MAX_LISTED]:
        out.append(PreflightFinding(
            "duplicates", SEV_WARNING, key,
            f"{key_field} '{key}' appears {counts[key]} times on the "
            f"hosted layer"))
    if len(dups) > _MAX_LISTED:
        out.append(PreflightFinding(
            "duplicates", SEV_WARNING, "",
            f"...and {len(dups) - _MAX_LISTED} more duplicate "
            f"{key_field} value(s)"))
    if not out:
        out.append(PreflightFinding(
            "duplicates", SEV_INFO, "",
            f"no duplicate or missing {key_field} values"))
    return out


def _norm(value) -> str:
    return "" if value is None else str(value)


def check_conflict_candidates(hosted_records: Sequence[dict],
                              local_rows: Sequence[dict],
                              *, key_field: str = "GlobalID",
                              exclude_fields: Iterable[str] = (),
                              ) -> List[PreflightFinding]:
    """Hosted records whose local counterpart differs — conflict candidates.

    ``local_rows`` is a headless CSV snapshot (slice 1); a matched key whose
    shared non-system fields differ is a *candidate* — resolution stays under
    human control (Phase 9 scope).
    """
    # ponytail: naive string-compare of values (CSV loses types, so "1.0" vs
    # "1" false-positives are possible); tighten per-type at the live gate if
    # they show up.
    excluded = {key_field, *exclude_fields}
    local_by_key = {}
    for row in local_rows:
        key = row.get(key_field)
        if key not in (None, ""):
            local_by_key.setdefault(str(key), row)

    out: List[PreflightFinding] = []
    matched = hosted_only = 0
    conflicts: List[Tuple[str, List[str]]] = []
    for rec in hosted_records:
        key = rec.get(key_field)
        if key in (None, ""):
            continue  # counted by check_duplicate_identities
        local = local_by_key.get(str(key))
        if local is None:
            hosted_only += 1
            continue
        matched += 1
        diff = sorted(
            f for f in rec
            if f in local and f not in excluded and not _is_system_field(f)
            and _norm(rec[f]) != _norm(local[f]))
        if diff:
            conflicts.append((str(key), diff))

    for key, fields in conflicts[:_MAX_LISTED]:
        out.append(PreflightFinding(
            "conflicts", SEV_WARNING, key,
            f"potential conflict on {key_field} '{key}' - differing "
            f"field(s): {', '.join(fields)}"))
    if len(conflicts) > _MAX_LISTED:
        out.append(PreflightFinding(
            "conflicts", SEV_WARNING, "",
            f"...and {len(conflicts) - _MAX_LISTED} more conflict "
            f"candidate(s)"))
    out.append(PreflightFinding(
        "conflicts", SEV_INFO, "",
        f"{matched} matched key(s), {len(conflicts)} conflict "
        f"candidate(s), {hosted_only} hosted-only record(s) with no "
        f"local row"))
    return out


def check_attachments(hosted_attachments: Sequence[dict],
                      manifest_rows: Sequence[dict],
                      ) -> List[PreflightFinding]:
    """Hosted attachment inventory vs the local harvester manifest.

    ``hosted_attachments`` are normalized dicts (see ``fetch_attachments``):
    objectid / attachment_id / name / size.  ``manifest_rows`` are harvester
    ``manifest.csv`` rows (AttachmentResult columns).  Missing locally =
    hosted attachment with no manifest row; stale = sizes differ.
    """
    local: Dict[Tuple[str, str], dict] = {
        (_norm(r.get("objectid")), _norm(r.get("attachment_id"))): r
        for r in manifest_rows}
    out: List[PreflightFinding] = []
    missing = stale = 0
    for att in hosted_attachments:
        ident = (_norm(att.get("objectid")), _norm(att.get("attachment_id")))
        row = local.get(ident)
        label = f"oid {ident[0]} att {ident[1]} ({att.get('name', '')})"
        if row is None:
            missing += 1
            if missing <= _MAX_LISTED:
                out.append(PreflightFinding(
                    "attachments", SEV_WARNING, label,
                    f"hosted attachment {label} is not in the local "
                    f"manifest - not yet harvested"))
            continue
        hosted_size = _norm(att.get("size"))
        local_size = _norm(row.get("size"))
        if hosted_size and local_size and hosted_size != local_size:
            stale += 1
            if stale <= _MAX_LISTED:
                out.append(PreflightFinding(
                    "attachments", SEV_WARNING, label,
                    f"hosted attachment {label} size {hosted_size} != "
                    f"local manifest size {local_size} - stale local "
                    f"copy"))
    for kind, count in (("missing", missing), ("stale", stale)):
        if count > _MAX_LISTED:
            out.append(PreflightFinding(
                "attachments", SEV_WARNING, "",
                f"...and {count - _MAX_LISTED} more {kind} attachment(s)"))
    if not out:
        out.append(PreflightFinding(
            "attachments", SEV_INFO, "",
            f"{len(hosted_attachments)} hosted attachment(s) all "
            f"present locally"))
    return out


# -- report assembly / formatting ----------------------------------------------

def build_preflight_report(*, item_id: str, layer_name: str,
                           checks_run: List[str],
                           findings: List[PreflightFinding],
                           ) -> PreflightReport:
    return PreflightReport(item_id=item_id, layer_name=layer_name,
                           checks_run=checks_run, findings=findings)


def format_preflight_report(report: PreflightReport) -> str:
    """Render a PreflightReport as a human-readable ASCII text block."""
    status = (f"{len(report.warnings)} WARNING(S)"
              if report.has_warnings else "CLEAN")
    lines = [
        f"Field Maps Sync Preflight  [{status}]  "
        f"Item: {report.item_id}  Layer: {report.layer_name}",
    ]
    by_check: Dict[str, List[PreflightFinding]] = {}
    for f in report.findings:
        by_check.setdefault(f.check, []).append(f)
    for key, label in CHECKS:
        lines.append(f"\n{label}")
        lines.append("-" * 60)
        if key not in report.checks_run:
            lines.append("  SKIPPED (input not provided)")
            continue
        for f in by_check.get(key, []):
            lines.append(f"  [{f.severity}] {f.message}")
    return "\n".join(lines)


# -- AGOL fetch seams (lazy arcgis, read-only) ---------------------------------

def _first(record: dict, *keys):
    for key in keys:
        if key in record and record[key] is not None:
            return record[key]
    return None


def fetch_service_state(gis, *, item_id: str, layer_index: int = 0,
                        ) -> Tuple[dict, dict, str]:  # pragma: no cover
    """Fetch (service_props, layer_props, layer_url) for a hosted service.

    Read-only: ``FeatureLayerCollection.fromitem`` + ``.properties`` reads.
    ``layer_index`` is AGOL's REST sublayer id via ``resolve_sublayer``.
    """
    from arcgis.features import FeatureLayer, FeatureLayerCollection

    item = gis.content.get(item_id)
    if item is None:
        raise ValueError(f"AGOL item {item_id!r} not found in this GIS")
    flc = FeatureLayerCollection.fromitem(item)
    layer_url = resolve_sublayer(item, layer_index, item_id).url
    layer_props = dict(FeatureLayer(layer_url, gis).properties)
    return dict(flc.properties), layer_props, layer_url


def fetch_replicas(gis, *, item_id: str) -> List[dict]:  # pragma: no cover
    """List replica info dicts for every replica on the service.

    ``flc.replicas.get_list()`` returns name+ID entries; the per-replica
    ``.get(id)`` read adds creationDate / lastSyncDate (epoch ms).  Both are
    read-only sync-metadata queries.
    """
    from arcgis.features import FeatureLayerCollection

    item = gis.content.get(item_id)
    if item is None:
        raise ValueError(f"AGOL item {item_id!r} not found in this GIS")
    flc = FeatureLayerCollection.fromitem(item)
    replicas: List[dict] = []
    for entry in (flc.replicas.get_list() or []):
        entry = dict(entry or {})
        rid = _first(entry, "replicaID", "replicaId", "id")
        detail = flc.replicas.get(str(rid)) if rid is not None else None
        replicas.append(dict(detail) if detail else entry)
    return replicas


def fetch_attachments(gis, *, layer_url: str,
                      ) -> List[dict]:  # pragma: no cover
    """List hosted attachments, normalized to objectid/attachment_id/name/size.

    Uses ``AttachmentManager.search()`` (one call for the whole layer,
    ``as_df=False`` default returns dicts).  Key casing varies across
    service versions, hence the tolerant ``_first`` lookups — the live gate
    run (#307 sandbox) confirms them.
    """
    from arcgis.features import FeatureLayer

    layer = FeatureLayer(layer_url, gis)
    normalized = []
    for rec in (layer.attachments.search(where="1=1") or []):
        rec = dict(rec)
        normalized.append({
            "objectid": _first(rec, "PARENTOBJECTID", "parentObjectId",
                               "PARENT_OBJECTID"),
            "attachment_id": _first(rec, "ID", "id", "attachmentid"),
            "name": _first(rec, "NAME", "name"),
            "size": _first(rec, "SIZE", "size"),
        })
    return normalized
