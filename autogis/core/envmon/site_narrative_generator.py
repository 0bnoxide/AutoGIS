"""site_narrative_generator.py — deterministic template-driven site narrative."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..common.qa import QACollector, QARecord, SEV_INFO


@dataclass
class NarrativeSection:
    heading: str
    text: str
    data_rows: list = field(default_factory=list)


@dataclass
class SiteNarrativeResult:
    sections: list
    full_text: str
    site_id: str
    event_label: str
    qa: QACollector


def _parse_float(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def build_highest_detections_section(
    max_result_rows: list,
    *,
    top_n: int = 5,
    screening_levels: Optional[dict] = None,
) -> NarrativeSection:
    sl = screening_levels or {}

    # Sort by max_result_value desc
    sortable = []
    for r in max_result_rows:
        val = _parse_float(r.get("max_result_value", ""))
        if val is not None:
            sortable.append((val, r))
    sortable.sort(key=lambda x: -x[0])
    top = [r for _, r in sortable[:top_n]]

    if not top:
        text = "No detections were reported during this monitoring event.\n"
        return NarrativeSection("Highest Detections", text, [])

    lines = []
    for r in top:
        loc = r.get("location_id", "")
        analyte = r.get("analyte_name", "")
        val = r.get("max_result_value", "")
        units = r.get("reported_units", "ug/L")
        date = r.get("max_sample_date", "")
        ratio_str = r.get("exceedance_ratio", "")
        ratio = _parse_float(ratio_str)
        mcl = sl.get(analyte)
        if ratio and ratio >= 1.0 and mcl:
            exceed_clause = (f", which exceeded the MCL of {mcl} {units} "
                             f"({ratio:.1f}×)")
        else:
            exceed_clause = ""
        lines.append(
            f"The highest concentration of {analyte} was {val} {units} at "
            f"{loc} (sampled {date}){exceed_clause}."
        )

    text = "\n".join(lines) + "\n"
    return NarrativeSection("Highest Detections", text, top)


def build_exceedance_change_section(change_log_rows: list) -> NarrativeSection:
    new_exc = [r for r in change_log_rows
               if r.get("change_type", "") == "exceedance_new"]
    resolved = [r for r in change_log_rows
                if r.get("change_type", "") == "exceedance_resolved"]

    lines = []
    if new_exc:
        lines.append("The following new exceedances were identified this event:")
        for r in new_exc:
            lines.append(f"  - {r.get('analyte_name', '')} at "
                         f"{r.get('location_id', '')} "
                         f"({r.get('new_value', '')} vs. previous ND).")
    else:
        lines.append("No new exceedances were identified this event.")

    if resolved:
        lines.append("\nThe following previously reported exceedances were resolved:")
        for r in resolved:
            lines.append(f"  - {r.get('analyte_name', '')} at "
                         f"{r.get('location_id', '')} "
                         f"(previously {r.get('old_value', '')}, now ND).")
    else:
        lines.append("No previously identified exceedances were resolved this event.")

    text = "\n".join(lines) + "\n"
    return NarrativeSection("Exceedance Changes", text, change_log_rows)


def build_not_sampled_section(
    plan_rows: list,
    result_rows: list,
) -> NarrativeSection:
    plan_ids = {r.get("SampleID", "") for r in plan_rows}
    result_ids = {r.get("SampleID", "") for r in result_rows}
    missing_ids = sorted(plan_ids - result_ids)

    # Map SampleID → LocationID from plan
    id_to_loc = {r.get("SampleID", ""): r.get("LocationID", "")
                 for r in plan_rows}
    missing_locs = [id_to_loc.get(sid, sid) for sid in missing_ids]

    if not missing_locs:
        text = ("All scheduled monitoring locations were sampled during "
                "this event.\n")
    else:
        text = (f"The following {len(missing_locs)} location(s) were not "
                f"sampled during this event: "
                f"{', '.join(missing_locs)}.\n")

    return NarrativeSection("Sampling Completeness", text, [])


def generate_site_narrative(
    site_id: str,
    event_label: str,
    *,
    max_result_rows: Optional[list] = None,
    max_result_path: Optional[Path] = None,
    change_log_rows: Optional[list] = None,
    change_log_path: Optional[Path] = None,
    plan_rows: Optional[list] = None,
    plan_path: Optional[Path] = None,
    result_rows: Optional[list] = None,
    result_path: Optional[Path] = None,
    screening_levels: Optional[dict] = None,
    top_n: int = 5,
    qa: Optional[QACollector] = None,
) -> SiteNarrativeResult:
    if qa is None:
        qa = QACollector()

    def _read_csv(path):
        with Path(path).open(newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))

    mr_rows = max_result_rows or (_read_csv(max_result_path) if max_result_path else [])
    cl_rows = change_log_rows or (_read_csv(change_log_path) if change_log_path else [])
    pl_rows = plan_rows or (_read_csv(plan_path) if plan_path else [])
    rs_rows = result_rows or (_read_csv(result_path) if result_path else [])

    sections = []
    header_text = f"# Site Narrative — {site_id} — {event_label}\n\n"

    if mr_rows:
        sections.append(build_highest_detections_section(
            mr_rows, top_n=top_n, screening_levels=screening_levels))

    if cl_rows:
        sections.append(build_exceedance_change_section(cl_rows))

    if pl_rows or rs_rows:
        sections.append(build_not_sampled_section(pl_rows, rs_rows))

    parts = [header_text]
    for s in sections:
        parts.append(f"## {s.heading}\n\n{s.text}\n")
    full_text = "\n".join(parts)

    qa.add(QARecord(SEV_INFO, "narrative_generated",
                    f"{len(sections)} sections for {site_id} {event_label}"))

    return SiteNarrativeResult(
        sections=sections, full_text=full_text,
        site_id=site_id, event_label=event_label, qa=qa,
    )
