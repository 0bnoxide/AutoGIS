"""Generate Markdown well inspection reports (headless).

Assembles one Markdown report per well from a wells CSV plus an optional
maintenance-log CSV, and a site summary Markdown flagging wells with no
inspection history or a non-passing latest condition. Photo attachments are
explicitly out of scope for this tool — see the related ADR for the deferred
follow-up.

No arcpy dependency. No openpyxl. Pure stdlib.
"""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from autogis.core.common.qa import QACollector, SEV_INFO, SEV_WARNING

_PASSING_CONDITIONS = {"GOOD", "OK", "PASS", "SATISFACTORY"}


def _load_csv(path: Optional[Path]) -> List[dict]:
    """Load CSV rows as list of dicts. Returns [] if path is None or absent."""
    if not path or not Path(path).exists():
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _md_table(headers: list, rows: list) -> str:
    """Build a Markdown pipe table from headers and list-of-list rows."""
    lines = ["| " + " | ".join(str(h) for h in headers) + " |",
             "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(v) for v in row) + " |")
    return "\n".join(lines)


def generate_well_report(
    well_id: str,
    well_row: dict,
    inspections: List[dict],
    *,
    generated_date: Optional[date] = None,
) -> str:
    """Assemble a Markdown report for one well.

    Args:
        well_id: Well identifier.
        well_row: Dict of well metadata (from the wells CSV row).
        inspections: Maintenance-log rows for this well, newest first
            (caller/build_well_inspection_reports is responsible for the
            ordering; this function does not re-sort).
        generated_date: Date to stamp on the report (default: today).
    """
    generated = (generated_date or date.today()).isoformat()
    lines = [
        f"# Well Inspection Report — {well_id}",
        "",
        f"**Generated:** {generated}  ",
    ]
    for key, value in well_row.items():
        if key == "WellID":
            continue
        lines.append(f"**{key}:** {value}  ")
    lines.append("")

    if inspections:
        latest = inspections[0]
        lines += [
            "## Latest Inspection",
            "",
            f"- Date: {latest.get('InspectionDate', '')}",
            f"- Condition: {latest.get('Condition', '')}",
            f"- Notes: {latest.get('Notes', '')}",
            "",
            "## Inspection History",
            "",
            _md_table(
                ["Date", "Condition", "Notes"],
                [[i.get("InspectionDate", ""), i.get("Condition", ""), i.get("Notes", "")]
                 for i in inspections],
            ),
            "",
        ]
    else:
        lines += ["## Inspection History", "", "*No inspection records on file.*", ""]

    return "\n".join(lines)


def generate_site_summary(
    wells: List[dict],
    inspections_by_well: Dict[str, List[dict]],
    *,
    site_id: str,
    generated_date: Optional[date] = None,
    qa: QACollector,
) -> str:
    """Assemble a Markdown site summary across all wells.

    Flags wells with no inspection history and wells whose latest recorded
    condition is not in the passing-condition set.
    """
    generated = (generated_date or date.today()).isoformat()
    never_inspected = []
    needs_attention = []
    rows = []
    for w in wells:
        wid = w.get("WellID", "")
        history = inspections_by_well.get(wid, [])
        if not history:
            never_inspected.append(wid)
            latest_condition, latest_date = "NEVER INSPECTED", ""
        else:
            latest_condition = history[0].get("Condition", "")
            latest_date = history[0].get("InspectionDate", "")
            if latest_condition.strip().upper() not in _PASSING_CONDITIONS:
                needs_attention.append(wid)
        rows.append([wid, latest_date, latest_condition])

    lines = [
        f"# Well Inspection Site Summary — {site_id}",
        "",
        f"**Generated:** {generated}  ",
        f"**Total wells:** {len(wells)}  ",
        f"**Never inspected:** {len(never_inspected)}  ",
        f"**Needs attention:** {len(needs_attention)}  ",
        "",
        "## Well Status",
        "",
        _md_table(["WellID", "Latest Inspection", "Condition"], rows),
        "",
    ]

    if never_inspected:
        qa.add(SEV_WARNING, "wells_never_inspected",
               f"{len(never_inspected)} well(s) have no inspection history: "
               f"{', '.join(never_inspected)}")
    if needs_attention:
        qa.add(SEV_WARNING, "wells_need_attention",
               f"{len(needs_attention)} well(s) have a non-passing latest condition: "
               f"{', '.join(needs_attention)}")

    qa.add(SEV_INFO, "well_inspection_summary_complete",
           f"Site summary: {len(wells)} well(s), {len(never_inspected)} never inspected, "
           f"{len(needs_attention)} need attention")
    return "\n".join(lines)


def build_well_inspection_reports(
    wells_csv: Path,
    output_dir: Path,
    *,
    site_id: str,
    maintenance_log_csv: Optional[Path] = None,
    generated_date: Optional[date] = None,
    qa: QACollector,
) -> List[Path]:
    """Load inputs and write one Markdown file per well plus a site summary.

    Returns the list of Markdown file paths written (wells first, summary last).
    """
    wells = _load_csv(wells_csv)
    inspections = _load_csv(maintenance_log_csv)

    inspections_by_well: Dict[str, List[dict]] = {}
    for row in inspections:
        inspections_by_well.setdefault(row.get("WellID", ""), []).append(row)
    for wid in inspections_by_well:
        # Newest first; ISO date strings sort lexically.
        inspections_by_well[wid].sort(
            key=lambda r: r.get("InspectionDate", ""), reverse=True)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    for well_row in wells:
        wid = well_row.get("WellID", "")
        content = generate_well_report(
            wid, well_row, inspections_by_well.get(wid, []),
            generated_date=generated_date,
        )
        path = output_dir / f"{wid}.md"
        path.write_text(content, encoding="utf-8")
        written.append(path)

    summary_content = generate_site_summary(
        wells, inspections_by_well, site_id=site_id,
        generated_date=generated_date, qa=qa,
    )
    summary_path = output_dir / "SiteSummary.md"
    summary_path.write_text(summary_content, encoding="utf-8")
    written.append(summary_path)

    return written
