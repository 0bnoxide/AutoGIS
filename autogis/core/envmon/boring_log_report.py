"""boring_log_report.py — Tool 8.0c GenerateBoringLogPDFs (headless).

Assembles, per boring, a standardized boring-log document as Markdown from the
normalized boring-log SQLite database (8.0a), plus a combined appendix ``.md``,
a photo-log ``.md`` and a sample-summary CSV. PDF rendering (with graphical
lithology / well-construction diagrams) is an explicit downstream step — this
repo keeps zero PDF/graphics dependencies in the arcpy-free layer (see
``docs/superpowers/specs/2026-06-28-generate-boring-log-pdfs-design.md``).

8.0a (``create_boring_log_database.py``) exposes no read API — it only creates
and validates the schema — so this module owns the read side:
``read_boring_records`` returns plain dicts keyed by the
``core/common/schema/boring.py`` dataclass field names (the DB columns are
derived from those same fields, so the shapes match by construction).

Stdlib only (sqlite3 + csv). Arcpy-free.
"""
from __future__ import annotations

import csv
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..common.qa import QACollector, SEV_WARNING
from ..common.schema.boring import (
    BoringPhoto, BoringSample, GroundwaterObservation, LithologyInterval,
    WellConstruction,
)

#: Child tables read per boring, keyed by the build_boring_log kwarg they feed.
_CHILD_TABLES = {
    "lithology": LithologyInterval,
    "samples": BoringSample,
    "construction": WellConstruction,
    "groundwater": GroundwaterObservation,
    "photos": BoringPhoto,
}

#: Fixed column order for sample_summary.csv.
_SAMPLE_CSV_COLUMNS = (
    "boring_id", "sample_id", "sample_type", "top_depth", "bottom_depth",
    "recovery", "blow_counts", "matrix", "analytical_group", "lab_submitted",
    "pid_ppm",
)


@dataclass
class BoringLogDoc:
    boring_id: str
    markdown: str
    sample_rows: list = field(default_factory=list)  # for sample_summary.csv
    photo_rows: list = field(default_factory=list)   # for photo_log.md


# ---- read side (8.0a ships no query API) -----------------------------------

def _record(row: sqlite3.Row) -> dict:
    """Row -> dict keyed by schema field names, dropping the surrogate id."""
    return {k: row[k] for k in row.keys() if k != "id"}


def read_boring_records(
    db_path: Path, *,
    boring_ids: Optional[list] = None,
    qa: Optional[QACollector] = None,
) -> dict:
    """Read per-boring record bundles from the 8.0a SQLite database.

    Returns ``{boring_id: {"location": dict, "lithology": [...], "samples":
    [...], "construction": [...], "groundwater": [...], "photos": [...]}}``
    — exactly the keyword args ``build_boring_log`` expects. *boring_ids*
    limits the result (default: every boring with a BoringLocations row);
    requested IDs without a location row are QA-warned, not silently dropped.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        locs = [_record(r) for r in conn.execute(
            'SELECT * FROM "BoringLocations" ORDER BY boring_id')]
        if boring_ids is not None:
            found = {loc["boring_id"] for loc in locs}
            for missing in [b for b in boring_ids if b not in found]:
                if qa is not None:
                    qa.add(SEV_WARNING, "boring_not_found",
                           f"Requested boring {missing!r} has no "
                           f"BoringLocations row; skipped.")
            locs = [loc for loc in locs if loc["boring_id"] in set(boring_ids)]
        out = {loc["boring_id"]: {"location": loc,
                                  **{k: [] for k in _CHILD_TABLES}}
               for loc in locs}
        for key, dc in _CHILD_TABLES.items():
            for r in conn.execute(f'SELECT * FROM "{dc.table_name}"'):
                rec = _record(r)
                bundle = out.get(rec["boring_id"])
                if bundle is not None:
                    bundle[key].append(rec)
    finally:
        conn.close()
    return out


# ---- Markdown assembly ------------------------------------------------------

def _fmt(v) -> str:
    return "" if v is None else str(v)


def _md_table(headers: list, rows: list) -> list:
    """Markdown pipe table as a list of lines. (generate_event_report has a
    str-returning cousin; kept local — the shared shape is two lines of code.)"""
    lines = ["| " + " | ".join(str(h) for h in headers) + " |",
             "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(_fmt(v) for v in row) + " |")
    return lines


def _sample_pid(sample: dict, lithology: list) -> Optional[float]:
    """Max PID (ppm) over lithology intervals overlapping the sample interval.

    PID readings live on LithologyIntervals in the 8.0a schema, not on
    samples; the log's sample table reports the reading for the sampled depth.
    """
    pids = [iv["pid_ppm"] for iv in lithology
            if iv["pid_ppm"] is not None
            and iv["top_depth"] < sample["bottom_depth"]
            and iv["bottom_depth"] > sample["top_depth"]]
    return max(pids) if pids else None


def build_boring_log(
    boring_id: str,
    *,
    location: dict,
    lithology: list,
    samples: list,
    construction: list,
    groundwater: list,
    photos: list,
    qa: Optional[QACollector] = None,
) -> BoringLogDoc:
    """Assemble one boring-log Markdown document + summary rows from DB records.

    All record dicts are keyed by the ``schema/boring.py`` field names (the
    shape ``read_boring_records`` returns). A boring with no samples still
    renders, with an empty sample section and a QA WARNING.
    """
    loc = location
    lines = [f"# Boring Log — {boring_id}", "", "## Header", ""]
    # ponytail: no drilling_method row — the 8.0a schema has no such column
    # (closest fields: completion_type, driller). Add when 8.0a grows one.
    lines += _md_table(["Field", "Value"], [
        ["Site", loc.get("site_id")],
        ["Location type", loc.get("location_type")],
        ["Status", loc.get("status")],
        ["Northing / Easting", f"{_fmt(loc.get('northing'))} / "
                               f"{_fmt(loc.get('easting'))}"],
        ["Coordinate system", loc.get("coordinate_system")],
        ["Ground elevation", loc.get("ground_elevation")],
        ["TOC elevation", loc.get("toc_elevation")],
        ["Vertical datum", loc.get("vertical_datum")],
        ["Total depth (ft)", loc.get("total_depth_ft")],
        ["Completion type", loc.get("completion_type")],
        ["Drilling start / end", f"{_fmt(loc.get('drilling_start_date'))} / "
                                 f"{_fmt(loc.get('drilling_end_date'))}"],
        ["Driller", loc.get("driller")],
        ["Logged by", loc.get("logged_by")],
    ])

    lines += ["", "## Lithologic Column", ""]
    if lithology:
        ordered = sorted(lithology, key=lambda iv: iv["top_depth"])
        lines += _md_table(
            ["Top (ft)", "Bottom (ft)", "USCS", "Graphic", "Material",
             "Color", "Moisture", "PID (ppm)", "Description"],
            [[iv["top_depth"], iv["bottom_depth"], iv["uscs"],
              iv["graphic_pattern"], iv["primary_material"], iv["color"],
              iv["moisture"], iv["pid_ppm"], iv["description"]]
             for iv in ordered])
    else:
        lines.append("_No lithology intervals recorded._")

    lines += ["", "## Samples", ""]
    sample_rows: list = []
    if samples:
        ordered = sorted(samples, key=lambda s: s["top_depth"])
        table = []
        for s in ordered:
            pid = _sample_pid(s, lithology)
            table.append([s["sample_id"], s["sample_type"], s["top_depth"],
                          s["bottom_depth"], s["recovery"], s["blow_counts"],
                          s["matrix"], "Y" if s["lab_submitted"] else "N",
                          pid])
            sample_rows.append({
                "boring_id": boring_id, "sample_id": s["sample_id"],
                "sample_type": s["sample_type"], "top_depth": s["top_depth"],
                "bottom_depth": s["bottom_depth"], "recovery": s["recovery"],
                "blow_counts": s["blow_counts"], "matrix": s["matrix"],
                "analytical_group": s["analytical_group"],
                "lab_submitted": "Y" if s["lab_submitted"] else "N",
                "pid_ppm": pid,
            })
        lines += _md_table(
            ["Sample ID", "Type", "Top (ft)", "Bottom (ft)", "Recovery",
             "Blow Counts", "Matrix", "Lab", "PID (ppm)"], table)
    else:
        lines.append("_No samples recorded._")
        if qa is not None:
            qa.add(SEV_WARNING, "no_samples",
                   f"Boring {boring_id} has no sample records.")

    lines += ["", "## Well Construction", ""]
    if construction:
        ordered = sorted(construction, key=lambda c: c["top_depth"])
        lines += _md_table(
            ["Top (ft)", "Bottom (ft)", "Component", "Diameter", "Material",
             "Slot Size", "Notes"],
            [[c["top_depth"], c["bottom_depth"], c["component_type"],
              c["diameter"], c["material"], c["slot_size"], c["notes"]]
             for c in ordered])
    else:
        lines.append("_No well construction records (no well installed)._")

    lines += ["", "## Groundwater Observations", ""]
    if groundwater:
        lines += _md_table(
            ["Date/Time", "Depth to Water (ft)", "Type", "Reference",
             "Notes"],
            [[g["observation_datetime"], g["depth_to_water"],
              g["observation_type"], g["reference_point"], g["notes"]]
             for g in groundwater])
    else:
        lines.append("_No groundwater observations recorded._")

    lines += ["", "## Photos", ""]
    photo_rows = [{"boring_id": boring_id, **p} for p in photos]
    if photos:
        lines += _md_table(
            ["Photo ID", "Depth (ft)", "Caption", "Taken By", "Path"],
            [[p["photo_id"], p["depth"], p["caption"], p["taken_by"],
              p["photo_path"]] for p in photos])
    else:
        lines.append("_No photos recorded._")

    lines += ["", "## Approval", ""]
    lines += _md_table(["Role", "Name", "Signature", "Date"], [
        ["Logged by", loc.get("logged_by"), "", ""],
        ["Reviewed by", "", "", ""],
        ["Approved by", "", "", ""],
    ])

    return BoringLogDoc(boring_id=boring_id, markdown="\n".join(lines) + "\n",
                        sample_rows=sample_rows, photo_rows=photo_rows)


def build_appendix(docs: list) -> str:
    """Combine per-boring docs into one appendix Markdown with a contents list."""
    lines = ["# Boring Log Appendix", "", "## Contents", ""]
    lines += [f"- {d.boring_id}" for d in docs]
    for d in docs:
        lines += ["", "---", "", d.markdown.rstrip()]
    return "\n".join(lines) + "\n"


# ---- outputs ----------------------------------------------------------------

def _safe_name(boring_id: str) -> str:
    return re.sub(r"[^\w.-]", "_", boring_id)


def write_outputs(docs: list, out_dir: Path) -> list:
    """Write per-boring .md, appendix .md, photo-log .md and sample CSV.

    Returns every path written. The photo log and sample CSV are always
    written (header-only when empty) so downstream packaging can rely on them.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for d in docs:
        p = out / f"boring_log_{_safe_name(d.boring_id)}.md"
        p.write_text(d.markdown, encoding="utf-8")
        paths.append(p)

    appendix = out / "appendix.md"
    appendix.write_text(build_appendix(docs), encoding="utf-8")
    paths.append(appendix)

    photo_lines = ["# Photo Log", ""]
    photo_lines += _md_table(
        ["Boring", "Photo ID", "Depth (ft)", "Caption", "Taken By", "Path"],
        [[p["boring_id"], p["photo_id"], p["depth"], p["caption"],
          p["taken_by"], p["photo_path"]]
         for d in docs for p in d.photo_rows])
    photo_log = out / "photo_log.md"
    photo_log.write_text("\n".join(photo_lines) + "\n", encoding="utf-8")
    paths.append(photo_log)

    csv_path = out / "sample_summary.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=_SAMPLE_CSV_COLUMNS)
        w.writeheader()
        for d in docs:
            for row in d.sample_rows:
                w.writerow(row)
    paths.append(csv_path)
    return paths
