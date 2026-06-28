"""Generate Markdown monitoring event report from CSV tool outputs (Tool 10.5).

Assembles a single .md review document from the outputs of:
  - import-edd / normalize-results (results CSV)
  - compare-events (comparison CSV with TrendLabel column)
  - run-history-report (history summary CSV)
  - identify-data-gaps (gaps CSV)
  - evaluate-rpd-qa (RPD QA CSV)

No arcpy dependency. No openpyxl. Pure stdlib.
"""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Optional

from autogis.core.common.qa import QACollector, SEV_INFO


def _load_csv(path: Optional[Path]) -> list:
    """Load CSV rows as list of dicts. Returns [] if path is None or absent."""
    if not path or not Path(path).exists():
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _md_table(headers: list, rows: list) -> str:
    """Build a Markdown pipe table from headers and list-of-list rows."""
    lines = []
    lines.append("| " + " | ".join(str(h) for h in headers) + " |")
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        lines.append("| " + " | ".join(str(v) for v in row) + " |")
    return "\n".join(lines)


def generate_event_report(
    site_id: str,
    event_id: str,
    *,
    results_csv: Optional[Path] = None,
    comparison_csv: Optional[Path] = None,
    history_csv: Optional[Path] = None,
    gaps_csv: Optional[Path] = None,
    rpd_qa_csv: Optional[Path] = None,
    generated_date: Optional[date] = None,
    qa: QACollector,
) -> str:
    """Assemble a Markdown monitoring event report.

    Args:
        site_id: Site identifier string.
        event_id: Event identifier string (e.g. "2026Q2").
        results_csv: Optional path to analytical results CSV.
        comparison_csv: Optional path to compare-events CSV (TrendLabel column).
        history_csv: Optional path to run-history-report CSV.
        gaps_csv: Optional path to identify-data-gaps CSV.
        rpd_qa_csv: Optional path to evaluate-rpd-qa CSV.
        generated_date: Date to stamp on the report (default: today).
        qa: QACollector for status messages.

    Returns:
        Markdown string ready to write to a .md file.
    """
    generated = (generated_date or date.today()).isoformat()

    results = _load_csv(results_csv)
    comparisons = _load_csv(comparison_csv)
    history = _load_csv(history_csv)
    gaps = _load_csv(gaps_csv)
    rpd = _load_csv(rpd_qa_csv)

    lines = [
        f"# Monitoring Event Report — {site_id} / {event_id}",
        "",
        f"**Generated:** {generated}  ",
        f"**Site:** {site_id}  ",
        f"**Event:** {event_id}  ",
        "",
    ]

    # --- Executive Summary ---
    n_results = len(results)
    n_exceedances = sum(
        1 for r in results
        if str(r.get("ExceedsScreeningLevel", "")).strip() in ("1", "True", "true", "YES")
    )
    n_gaps = len(gaps)
    n_rpd_errors = sum(
        1 for r in rpd
        if str(r.get("severity", "")).upper() == "ERROR"
    )

    summary_rows = [
        ["Total analytical results", n_results],
        ["Screening level exceedances", n_exceedances],
        ["Data gaps identified", n_gaps],
        ["RPD QA errors", n_rpd_errors],
    ]
    lines += [
        "## Executive Summary",
        "",
        _md_table(["Metric", "Value"], summary_rows),
        "",
    ]

    # --- Trend vs Previous Event ---
    if comparisons:
        trend_counts: dict = {}
        for r in comparisons:
            trend = str(r.get("TrendLabel", r.get("TrendVsPrevious", "UNKNOWN"))).upper()
            trend_counts[trend] = trend_counts.get(trend, 0) + 1
        trend_rows = [[t, c] for t, c in sorted(trend_counts.items())]
        lines += [
            "## Trend vs Previous Event",
            "",
            _md_table(["Trend", "Count"], trend_rows),
            "",
        ]

    # --- History Summary (up to 10 rows) ---
    if history:
        # If any rows carry a latest exceedance, show those; otherwise fall back
        # to the input rows in their existing order. Either way, cap at 10.
        exceed_rows = [h for h in history if str(h.get("LatestExceedance", "")).strip() in ("1", "True", "true")]
        shown = (exceed_rows or history)[:10]
        table_rows = [
            [
                h.get("LocationID", ""),
                h.get("AnalyteCanonicalName", ""),
                h.get("NTotal", ""),
                h.get("TrendVsPrevious", ""),
                h.get("LatestResult", ""),
            ]
            for h in shown
        ]
        lines += [
            "## History Summary (Top 10)",
            "",
            _md_table(
                ["Location", "Analyte", "N Total", "Trend", "Latest Result"],
                table_rows,
            ),
            "",
        ]

    # --- Data Gaps ---
    if gaps:
        gap_rows = [
            [
                g.get("LocationID", g.get("location_id", "")),
                g.get("AnalyteName", g.get("analyte", "")),
                g.get("Status", g.get("status", "")),
                g.get("Detail", g.get("detail", "")),
            ]
            for g in gaps[:20]  # cap at 20 rows in report
        ]
        lines += [
            "## Data Gaps",
            "",
            _md_table(["Location", "Analyte", "Status", "Detail"], gap_rows),
        ]
        if len(gaps) > 20:
            lines.append(f"*... and {len(gaps) - 20} more gap(s) in the full CSV.*")
        lines.append("")

    # --- RPD QA ---
    if rpd:
        lines += [
            "## Duplicate RPD QA",
            "",
            f"{len(rpd)} RPD QA record(s) — {n_rpd_errors} ERROR(s).",
            "",
        ]
        if n_rpd_errors:
            error_rows = [r for r in rpd if str(r.get("severity", "")).upper() == "ERROR"][:10]
            tbl_rows = [
                [
                    r.get("location_id", r.get("LocationID", "")),
                    r.get("analyte", r.get("AnalyteName", "")),
                    r.get("message", r.get("Message", "")),
                ]
                for r in error_rows
            ]
            lines += [
                _md_table(["Location", "Analyte", "Message"], tbl_rows),
                "",
            ]

    lines += [
        "---",
        "*Report generated by AutoGIS `envmon generate-event-report`.*",
        "",
    ]

    content = "\n".join(lines)
    qa.add(
        SEV_INFO, "generate_event_report_complete",
        f"generate_event_report: {site_id}/{event_id}, "
        f"{len(lines)} lines, {n_results} results, {n_exceedances} exceedances",
    )
    return content
