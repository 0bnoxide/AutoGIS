"""Generate Markdown well inspection reports (headless).

Assembles one Markdown report per well from a wells CSV plus an optional
maintenance-log CSV, and a site summary Markdown flagging wells with no
inspection history or a non-passing latest condition. Photo attachments are
explicitly out of scope for this tool — see the related ADR for the deferred
follow-up.

No arcpy dependency. No openpyxl. Pure stdlib.
"""
from __future__ import annotations

import base64
import csv
import re
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from autogis.core.common import report_html as rh
from autogis.core.common.qa import QACollector, SEV_INFO, SEV_WARNING

_PASSING_CONDITIONS = {"GOOD", "OK", "PASS", "SATISFACTORY"}
_UNSAFE_NAME_CHARS = re.compile(r"[\\/]")


def _sanitize_well_id(well_id: str, *, qa: QACollector) -> str:
    """Return a filesystem-safe well ID for use as a bare file stem.

    WellID values come from a caller-supplied CSV, so a value like
    ``"../../evil"`` must not be allowed to escape ``output_dir``.
    """
    safe = _UNSAFE_NAME_CHARS.sub("_", well_id).strip()
    if safe in ("", ".", ".."):
        safe = "_invalid_well_id"
    if safe != well_id:
        qa.add(SEV_WARNING, "unsafe_well_id",
               f"WellID {well_id!r} is not filesystem-safe; using {safe!r} instead.")
    return safe


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


def generate_well_report_html(
    well_id: str,
    well_row: dict,
    inspections: List[dict],
    *,
    generated_date: Optional[date] = None,
    photos: "list[tuple[str, str]]" = (),
) -> str:
    """Self-contained HTML report for one well (mirror of generate_well_report).

    photos: (data-URI, caption) pairs; empty -> no photo section.
    """
    generated = (generated_date or date.today()).isoformat()
    meta = {k: v for k, v in well_row.items() if k != "WellID"}
    sections: List[str] = []
    if inspections:
        latest = inspections[0]
        cond = latest.get("Condition", "")
        tone = "ok" if cond.strip().upper() in _PASSING_CONDITIONS else "warn"
        latest_html = (
            f'<p>Date: {rh.esc(latest.get("InspectionDate", ""))} · '
            f'Condition: {rh.badge(cond or "—", tone)} · '
            f'Notes: {rh.esc(latest.get("Notes", ""))}</p>'
        )
        sections.append(rh.section("Latest Inspection", latest_html))
        hist = rh.table(
            ["Date", "Condition", "Notes"],
            [[i.get("InspectionDate", ""), i.get("Condition", ""),
              i.get("Notes", "")] for i in inspections],
        )
        sections.append(rh.section("Inspection History", hist))
    else:
        sections.append(rh.section("Inspection History",
                                   "<p><em>No inspection records on file.</em></p>"))
    if photos:
        sections.append(rh.section("Field Photos", rh.photo_grid(photos)))
    return rh.render_document(
        title=f"Well Inspection Report — {well_id}",
        meta=meta, sections=sections, generated=generated,
    )


def generate_site_summary_html(
    wells: List[dict],
    inspections_by_well: Dict[str, List[dict]],
    *,
    site_id: str,
    generated_date: Optional[date] = None,
    qa: QACollector,
) -> str:
    """HTML site summary (mirror of generate_site_summary; same QA emits)."""
    generated = (generated_date or date.today()).isoformat()
    never, attention, rows = [], [], []
    for w in wells:
        wid = w.get("WellID", "")
        history = inspections_by_well.get(wid, [])
        if not history:
            never.append(wid)
            cond, dt = "NEVER INSPECTED", ""
        else:
            cond = history[0].get("Condition", "")
            dt = history[0].get("InspectionDate", "")
            if cond.strip().upper() not in _PASSING_CONDITIONS:
                attention.append(wid)
        rows.append([wid, dt, cond])

    def tone_of(i, j):
        if j != 2:
            return None
        c = rows[i][2].strip().upper()
        if c == "NEVER INSPECTED":
            return "warn"
        return "ok" if c in _PASSING_CONDITIONS else "bad"

    kpi = rh.kpi_row([
        ("Total wells", len(wells), "neutral"),
        ("Never inspected", len(never), "warn" if never else "ok"),
        ("Needs attention", len(attention), "bad" if attention else "ok"),
    ])
    tbl = rh.table(["WellID", "Latest Inspection", "Condition"], rows, tone_of=tone_of)
    body = rh.render_document(
        title=f"Well Inspection Site Summary — {site_id}",
        sections=[rh.section("Summary", kpi), rh.section("Well Status", tbl)],
        generated=generated,
    )
    if never:
        qa.add(SEV_WARNING, "wells_never_inspected",
               f"{len(never)} well(s) have no inspection history: {', '.join(never)}")
    if attention:
        qa.add(SEV_WARNING, "wells_need_attention",
               f"{len(attention)} well(s) have a non-passing latest condition: "
               f"{', '.join(attention)}")
    qa.add(SEV_INFO, "well_inspection_summary_complete",
           f"Site summary: {len(wells)} well(s), {len(never)} never inspected, "
           f"{len(attention)} need attention")
    return body


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
    fmt: str = "md",
    manifest_path: Optional[Path] = None,
    harvest_dir: Optional[Path] = None,
    qa: QACollector,
) -> List[Path]:
    """Load inputs and write one report file per well plus a site summary.

    fmt: "md" (default) writes Markdown; "html" writes self-contained HTML.
    manifest_path/harvest_dir: optional harvester manifest + harvest root,
        reused (fmt="html" only) to embed a per-well photo grid via
        well_inspection_photo_report's matching/thumbnail pipeline.

    Returns the list of file paths written (wells first, summary last).
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

    # Photo grid (HTML only): reuse the harvester pipeline. Fail fast on a
    # missing Pillow BEFORE writing any file (reports are written per-well).
    photos_by_well: Dict[str, list] = {}
    if fmt == "html" and manifest_path and harvest_dir:
        from autogis.core.envmon.index_field_attachments import load_manifest
        from autogis.core.envmon.well_inspection_photo_report import (
            match_photos_to_wells, prepare_image_bytes,
        )
        try:
            import PIL  # noqa: F401  (fail-fast capability probe)
        except ImportError as exc:
            raise ImportError('Pillow is required to embed photos. Install with: '
                              'pip install "autogis[report]"') from exc
        manifest_rows = load_manifest(Path(manifest_path))
        photo_map = match_photos_to_wells(manifest_rows, Path(harvest_dir), qa=qa)
        missing: List[str] = []
        for wid, entries in photo_map.items():
            imgs = []
            for e in entries:
                data = prepare_image_bytes(e.get("saved_path", ""), (300, 225))
                if data is None:
                    missing.append(e.get("original_name") or e.get("saved_path", ""))
                    continue
                uri = "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii")
                imgs.append((uri, e.get("original_name") or ""))
            if imgs:
                photos_by_well[wid] = imgs
        if missing:
            # Parity with the XLSX tool's photo_files_missing WARNING.
            qa.add(SEV_WARNING, "photo_files_missing",
                   f"{len(missing)} manifest photo(s) not found on disk: "
                   f"{', '.join(missing)}")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    seen_well_ids: set = set()
    deduped_wells: List[dict] = []
    for well_row in wells:
        wid = well_row.get("WellID", "")
        if wid in seen_well_ids:
            qa.add(SEV_WARNING, "duplicate_well_id",
                   f"WellID {wid!r} appears more than once in the wells CSV; "
                   f"only the first occurrence's report was written.")
            continue
        seen_well_ids.add(wid)
        deduped_wells.append(well_row)

        safe_wid = _sanitize_well_id(wid, qa=qa)
        if fmt == "html":
            content = generate_well_report_html(
                wid, well_row, inspections_by_well.get(wid, []),
                generated_date=generated_date,
                photos=photos_by_well.get(wid, ()),
            )
            path = output_dir / f"{safe_wid}.html"
        else:
            content = generate_well_report(
                wid, well_row, inspections_by_well.get(wid, []),
                generated_date=generated_date,
            )
            path = output_dir / f"{safe_wid}.md"
        path.write_text(content, encoding="utf-8")
        written.append(path)

    if fmt == "html":
        summary_content = generate_site_summary_html(
            deduped_wells, inspections_by_well, site_id=site_id,
            generated_date=generated_date, qa=qa,
        )
        summary_path = output_dir / "SiteSummary.html"
    else:
        summary_content = generate_site_summary(
            deduped_wells, inspections_by_well, site_id=site_id,
            generated_date=generated_date, qa=qa,
        )
        summary_path = output_dir / "SiteSummary.md"
    summary_path.write_text(summary_content, encoding="utf-8")
    written.append(summary_path)

    return written
