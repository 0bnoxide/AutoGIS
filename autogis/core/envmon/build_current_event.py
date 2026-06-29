"""Build the wide current-event table (Env_CurrentEventWide).

Reads long-format Env_AnalyticalResults, applies the figure spec's
sample-selection / depth / duplicate rules, pivots to one row per
location (or per location+depth for soil), and writes the result with
sanitized field names plus a LabelText_Fallback column.

arcpy is imported lazily; the pure rule logic lives in module-level
functions so it can be unit tested without ArcGIS.
"""

from __future__ import annotations

import datetime as _dt
import re
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from ..common.logging import get_logger
from ..common.qa import QACollector, QARecord, SEV_ERROR, SEV_INFO, SEV_WARNING
from ..common.config import FigureSpec

LOG = get_logger(__name__)

SAMPLE_SELECTION_RULES = (
    "latest_per_location", "specific_event_date", "date_range_latest",
    "max_detected_per_location", "max_exceedance_per_location",
    "all_samples", "specific_sample_ids",
)
DUPLICATE_RULES = (
    "exclude_duplicates", "include_duplicates", "prefer_parent",
    "average_parent_and_duplicate", "flag_only",
)


def sanitize_field_name(name: str, used: set) -> str:
    """GDB-safe field name: alnum+underscore, no leading digit, unique."""
    s = re.sub(r"[^0-9A-Za-z_]", "_", name).strip("_") or "F"
    if s[0].isdigit():
        s = "F_" + s
    s = s[:60]
    base, i = s, 1
    while s.upper() in used:
        i += 1
        s = f"{base[:57]}_{i}"
    used.add(s.upper())
    return s


def select_samples(
    rows: Sequence[dict],
    rule: str,
    qa: QACollector,
    event_date: Optional[str] = None,
    date_range: Optional[Tuple[str, str]] = None,
    sample_ids: Optional[Sequence[str]] = None,
    target_analyte: Optional[str] = None,
) -> List[dict]:
    """Apply the sample_selection_rule to long-format result rows.

    Each row dict needs: LocationID, SampleID, SampleDate (datetime),
    AnalyteCanonicalName, IsDetected, ExceedsScreening, NumericValue.
    """
    if rule not in SAMPLE_SELECTION_RULES:
        raise ValueError(f"Unknown sample_selection_rule {rule!r}")

    def d(x):
        return x.strftime("%Y-%m-%d") if isinstance(x, (_dt.date, _dt.datetime)) else str(x or "")

    if rule == "all_samples":
        return list(rows)

    if rule == "specific_sample_ids":
        wanted = {s.strip().upper() for s in (sample_ids or [])}
        out = [r for r in rows if str(r["SampleID"]).strip().upper() in wanted]
        missing = wanted - {str(r["SampleID"]).strip().upper() for r in out}
        for m in sorted(missing):
            qa.add(QARecord(severity=SEV_WARNING, category="sample_id_not_found",
                            message=f"Requested SampleID {m} not found.",
                            recommended_action="Check figure spec sample_ids."))
        return out

    if rule == "specific_event_date":
        if not event_date:
            raise ValueError("specific_event_date requires event_date")
        return [r for r in rows if d(r["SampleDate"]) == event_date]

    candidates = rows
    if rule == "date_range_latest":
        if not date_range:
            raise ValueError("date_range_latest requires date_range")
        lo, hi = date_range
        candidates = [r for r in rows if lo <= d(r["SampleDate"]) <= hi]

    by_loc: Dict[str, List[dict]] = defaultdict(list)
    for r in candidates:
        by_loc[r["LocationID"]].append(r)

    out: List[dict] = []
    for loc, lr in by_loc.items():
        if rule in ("latest_per_location", "date_range_latest"):
            latest = max(d(r["SampleDate"]) for r in lr)
            out.extend(r for r in lr if d(r["SampleDate"]) == latest)
        elif rule in ("max_detected_per_location", "max_exceedance_per_location"):
            pred = (lambda r: bool(r.get("IsDetected"))) \
                if rule == "max_detected_per_location" \
                else (lambda r: bool(r.get("ExceedsScreening")))
            pool = [r for r in lr
                    if pred(r) and r.get("NumericValue") is not None
                    and (target_analyte is None
                         or r["AnalyteCanonicalName"] == target_analyte)]
            if not pool:
                qa.add(QARecord(
                    severity=SEV_INFO, category="max_rule_no_candidates",
                    message=f"{loc}: no rows satisfy {rule}"
                            + (f" for {target_analyte}" if target_analyte else "")
                            + "; falling back to latest sample.",
                    location_id=loc,
                ))
                latest = max(d(r["SampleDate"]) for r in lr)
                out.extend(r for r in lr if d(r["SampleDate"]) == latest)
                continue
            best = max(pool, key=lambda r: r["NumericValue"])
            key = (best["SampleID"], d(best["SampleDate"]))
            out.extend(r for r in lr
                       if (r["SampleID"], d(r["SampleDate"])) == key)
    return out


def apply_duplicate_rule(
    rows: Sequence[dict],
    rule: str,
    qa: QACollector,
) -> List[dict]:
    """Resolve parent/field-duplicate pairs per the figure spec.

    Rows need IsFieldDuplicate (bool) and ParentSampleID (str or '').
    """
    if rule not in DUPLICATE_RULES:
        raise ValueError(f"Unknown duplicate_handling_rule {rule!r}")
    if rule in ("include_duplicates", "flag_only"):
        if rule == "flag_only":
            for r in rows:
                if r.get("IsFieldDuplicate"):
                    qa.add(QARecord(
                        severity=SEV_INFO, category="field_duplicate_present",
                        message=f"Field duplicate {r['SampleID']} included as-is.",
                        location_id=r.get("LocationID"),
                        sample_id=r.get("SampleID"),
                    ))
        return list(rows)
    if rule in ("exclude_duplicates", "prefer_parent"):
        return [r for r in rows if not r.get("IsFieldDuplicate")]

    # average_parent_and_duplicate — chemically dubious with nondetects;
    # we average only detect+detect pairs, prefer the parent otherwise,
    # and flag every averaged value.
    out: List[dict] = []
    by_key: Dict[Tuple, List[dict]] = defaultdict(list)
    for r in rows:
        parent = r.get("ParentSampleID") or r["SampleID"]
        by_key[(r["LocationID"], parent, r["AnalyteCanonicalName"],
                str(r.get("DepthIntervalText") or ""))].append(r)
    for key, group in by_key.items():
        parents = [g for g in group if not g.get("IsFieldDuplicate")]
        dups = [g for g in group if g.get("IsFieldDuplicate")]
        if not dups or not parents:
            out.extend(group if parents else group)  # singletons pass through
            continue
        p, dvp = parents[0], dups[0]
        if p.get("IsDetected") and dvp.get("IsDetected") \
                and p.get("NumericValue") is not None \
                and dvp.get("NumericValue") is not None:
            avg = (p["NumericValue"] + dvp["NumericValue"]) / 2.0
            merged = dict(p)
            merged["NumericValue"] = avg
            merged["DisplayText"] = f"{avg:g}"
            merged["WasAveraged"] = True
            qa.add(QARecord(
                severity=SEV_WARNING, category="averaged_parent_duplicate",
                message=(f"{key[0]} {key[2]}: parent {p['NumericValue']} and "
                         f"duplicate {dvp['NumericValue']} averaged to {avg:g}. "
                         "Averaging field duplicates is not standard practice; "
                         "verify this is intended."),
                location_id=key[0], analyte_name=key[2],
            ))
            out.append(merged)
        else:
            qa.add(QARecord(
                severity=SEV_WARNING, category="average_rule_nondetect_pair",
                message=(f"{key[0]} {key[2]}: cannot average a nondetect pair; "
                         "parent result used."),
                location_id=key[0], analyte_name=key[2],
            ))
            out.append(p)
    return out


def apply_depth_rule(rows: Sequence[dict], rule: Optional[str],
                     qa: QACollector) -> List[dict]:
    """Soil depth handling: all_depths | shallowest | deepest |
    max_per_analyte (max detected across depths)."""
    if not rule or rule == "all_depths":
        return list(rows)
    by_loc: Dict[str, List[dict]] = defaultdict(list)
    for r in rows:
        by_loc[r["LocationID"]].append(r)
    out: List[dict] = []
    for loc, lr in by_loc.items():
        depths = sorted({(r.get("DepthTopFt"), r.get("DepthIntervalText"))
                         for r in lr},
                        key=lambda t: (t[0] is None, t[0]))
        if not depths:
            out.extend(lr)
            continue
        if rule == "shallowest":
            keep = depths[0][1]
            out.extend(r for r in lr if r.get("DepthIntervalText") == keep)
        elif rule == "deepest":
            keep = depths[-1][1]
            out.extend(r for r in lr if r.get("DepthIntervalText") == keep)
        elif rule == "max_per_analyte":
            by_an: Dict[str, List[dict]] = defaultdict(list)
            for r in lr:
                by_an[r["AnalyteCanonicalName"]].append(r)
            for an, ar in by_an.items():
                pool = [r for r in ar if r.get("IsDetected")
                        and r.get("NumericValue") is not None]
                out.append(max(pool, key=lambda r: r["NumericValue"])
                           if pool else ar[0])
            qa.add(QARecord(
                severity=SEV_INFO, category="depth_rule_max_per_analyte",
                message=f"{loc}: per-analyte max across depths selected; "
                        "values in one callout may come from different depths.",
                location_id=loc,
            ))
        else:
            raise ValueError(f"Unknown depth rule {rule!r}")
    return out


def build_wide_rows(
    selected: Sequence[dict],
    analytes: Sequence[str],
    qa: QACollector,
    per_depth: bool = False,
) -> List[dict]:
    """Pivot long rows -> one dict per location(+depth)."""
    keyfn = (lambda r: (r["LocationID"], str(r.get("DepthIntervalText") or ""))) \
        if per_depth else (lambda r: (r["LocationID"], ""))
    grouped: Dict[Tuple[str, str], List[dict]] = defaultdict(list)
    for r in selected:
        grouped[keyfn(r)].append(r)

    wide: List[dict] = []
    for (loc, depth), rows in sorted(grouped.items()):
        first = rows[0]
        results = {r["AnalyteCanonicalName"]: r for r in rows}
        if len(results) < len(rows):
            # Multiple rows for the same analyte after rule application.
            seen: Dict[str, dict] = {}
            for r in rows:
                an = r["AnalyteCanonicalName"]
                if an in seen and seen[an] is not r:
                    qa.add(QARecord(
                        severity=SEV_WARNING,
                        category="multiple_results_after_rules",
                        message=(f"{loc} {an}: multiple results remain after "
                                 "selection rules; last one wins. Tighten the "
                                 "figure spec rules."),
                        location_id=loc, analyte_name=an,
                    ))
                seen[an] = r
            results = seen
        row = {
            "LocationID": loc,
            "SampleID": first.get("SampleID"),
            "SampleDate": first.get("SampleDate"),
            "DepthIntervalText": depth or None,
            "results": results,
        }
        flags = {
            "HasExceedance": any(r.get("ExceedsScreening") for r in results.values()),
            "HasDetection": any(r.get("IsDetected") for r in results.values()),
            "HasOnlyNonDetects": bool(results) and all(
                (not r.get("IsDetected")) for r in results.values()),
            "HasMissingRequiredAnalytes": any(a not in results for a in analytes),
        }
        row.update(flags)
        label_bits = []
        for a in analytes:
            r = results.get(a)
            label_bits.append(f"{a}: {r.get('DisplayText', '--') if r else '--'}")
        row["LabelText_Fallback"] = (f"{loc}"
                                     + (f" ({depth})" if depth else "")
                                     + "\n" + "\n".join(label_bits))
        wide.append(row)
    return wide


def parse_event_date(ev_str: Optional[str],
                     qa: QACollector) -> Optional[_dt.datetime]:
    """Parse a YYYY-MM-DD event date, or None. A malformed value records a
    ``bad_event_date`` WARNING and returns None (stored as NULL). Pure."""
    if not ev_str:
        return None
    try:
        return _dt.datetime.strptime(ev_str, "%Y-%m-%d")
    except ValueError:
        qa.add(QARecord(severity=SEV_WARNING, category="bad_event_date",
                        message=f"Event date {ev_str!r} is not "
                                "YYYY-MM-DD; stored as NULL."))
        return None


def build_insert_rows(
    wide: Sequence[dict],
    analytes: Sequence[str],
    *,
    site_id: str,
    figure_spec_id: str,
    event_dt: Optional[_dt.datetime],
    matrix: str,
) -> List[list]:
    """Build the Env_CurrentEventWide InsertCursor rows from wide rows.

    Returns one list per wide row, aligned to the cursor's field order:
    13 base fields then one column per analyte (DisplayText or "--", capped at
    64 chars; LabelText_Fallback capped at 2000). Pure — no arcpy.
    """
    rows: List[list] = []
    for w in wide:
        row = [
            site_id, figure_spec_id, event_dt, matrix,
            w["LocationID"], w["SampleID"], w["SampleDate"],
            w["DepthIntervalText"],
            int(w["HasExceedance"]), int(w["HasDetection"]),
            int(w["HasOnlyNonDetects"]),
            int(w["HasMissingRequiredAnalytes"]),
            w["LabelText_Fallback"][:2000],
        ]
        for a in analytes:
            r = w["results"].get(a)
            txt = (r or {}).get("DisplayText") or "--"
            row.append(txt[:64])
        rows.append(row)
    return rows


# --------------------------------------------------------------------------
# arcpy I/O
# --------------------------------------------------------------------------

from ...runtime.sessions import arcpy_env as _arcpy

# Physical Env_AnalyticalResults fields -> internal rule-engine keys.
LONG_FIELD_MAP = [
    ("SiteID", "SiteID"), ("Matrix", "Matrix"),
    ("LocationID", "LocationID"), ("SampleID", "SampleID"),
    ("ParentSampleID", "ParentSampleID"), ("SampleDate", "SampleDate"),
    ("DepthTop_ft", "DepthTopFt"), ("DepthIntervalText", "DepthIntervalText"),
    ("AnalyteCanonicalName", "AnalyteCanonicalName"),
    ("IsNonDetect", "IsNonDetect"), ("IsDetected", "IsDetected"),
    ("ExceedsScreeningLevel", "ExceedsScreening"),
    ("ResultNumeric", "NumericValue"), ("DisplayText", "DisplayText"),
    ("DisplayColorClass", "DisplayColorClass"), ("Units", "Units"),
    ("ScreeningLevel", "ScreeningLevelValue"),
]


def read_long_results(gdb, site_id: str, matrix: str) -> List[dict]:
    arcpy = _arcpy()
    table = str(gdb / "Env_AnalyticalResults")
    where = f"SiteID = '{site_id}' AND Matrix = '{matrix}'"
    phys = [p for p, _k in LONG_FIELD_MAP]
    out: List[dict] = []
    with arcpy.da.SearchCursor(table, phys, where_clause=where) as cur:
        for row in cur:
            d = {key: val for (_p, key), val in zip(LONG_FIELD_MAP, row)}
            d["IsFieldDuplicate"] = bool(d.get("ParentSampleID"))
            out.append(d)
    return out


def build_current_event_wide(
    gdb,
    site_id: str,
    figure_spec: FigureSpec,
    analyte_dictionary: Dict[str, dict],
    qa: QACollector,
    event_date: Optional[str] = None,
) -> List[dict]:
    """Compute and persist Env_CurrentEventWide for one figure spec.

    Returns the wide rows (also used directly by callout generation).
    """
    arcpy = _arcpy()
    spec = figure_spec
    matrix = spec.get("matrix", "GW")
    analytes = spec.analyte_list(analyte_dictionary)

    rows = read_long_results(gdb, site_id, matrix)
    if not rows:
        qa.add(QARecord(severity=SEV_ERROR, category="no_results_for_figure",
                        message=f"No {matrix} results for {site_id}; "
                                "cannot build current event table.",
                        site_id=site_id))
        return []

    rule = spec.get("sample_selection_rule", "latest_per_location")
    selected = select_samples(
        rows, rule, qa,
        event_date=event_date or spec.get("event_date"),
        date_range=tuple(spec.data["date_range"]) if spec.get("date_range") else None,
        sample_ids=spec.get("sample_ids"),
        target_analyte_name=spec.get("max_rule_analyte"),
    )
    selected = apply_duplicate_rule(
        selected, spec.get("duplicate_handling_rule", "prefer_parent"), qa
    )
    if matrix == "SOIL":
        selected = apply_depth_rule(selected, spec.get("depth_rule"), qa)

    wide = build_wide_rows(selected, analytes, qa,
                           per_depth=(matrix == "SOIL"
                                      and spec.get("depth_rule", "all_depths")
                                      == "all_depths"))

    # Persist (delete-then-insert for this site/spec/event).
    table = str(gdb / "Env_CurrentEventWide")
    used: set = set()
    afields = {a: sanitize_field_name(a, used) for a in analytes}

    existing = {f.name.upper() for f in arcpy.ListFields(table)}
    for a, fname in afields.items():
        if fname.upper() not in existing:
            arcpy.management.AddField(table, fname, "TEXT", field_length=64,
                                      field_alias=a)
            existing.add(fname.upper())

    ev_dt = parse_event_date(event_date or spec.get("event_date"), qa)
    where = (f"SiteID = '{site_id}' AND FigureSpecID = '{spec.figure_spec_id}'")
    with arcpy.da.UpdateCursor(table, ["OID@"], where_clause=where) as cur:
        for _ in cur:
            cur.deleteRow()

    base_fields = ["SiteID", "FigureSpecID", "EventDate", "Matrix",
                   "LocationID", "SampleID", "SampleDate", "DepthIntervalText",
                   "HasExceedance", "HasDetection", "HasOnlyNonDetects",
                   "HasMissingRequiredAnalytes", "LabelText_Fallback"]
    all_fields = base_fields + [afields[a] for a in analytes]
    insert_rows = build_insert_rows(
        wide, analytes, site_id=site_id, figure_spec_id=spec.figure_spec_id,
        event_dt=ev_dt, matrix=matrix)
    with arcpy.da.InsertCursor(table, all_fields) as cur:
        for row in insert_rows:
            cur.insertRow(row)

    LOG.info("Env_CurrentEventWide: wrote %s rows for %s / %s",
             len(wide), site_id, spec.figure_spec_id)
    return wide
