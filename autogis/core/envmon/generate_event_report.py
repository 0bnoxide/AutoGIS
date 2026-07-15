"""Generate Markdown monitoring event report from CSV tool outputs.

Post-roadmap extra tool — not a numbered roadmap tool. (Previously mislabeled
"Tool 10.5" in this docstring and elsewhere; roadmap 10.5 is actually the
unrelated "Run History Dashboard Table" / WriteRunHistory — see issue #104.)

Assembles a single .md review document from the outputs of:
  - import-edd / normalize-results (results CSV)
  - compare-events (comparison CSV with TrendLabel column)
  - run-history-report (history summary CSV)
  - identify-data-gaps (gaps CSV)
  - evaluate-rpd-qa (RPD QA CSV)

`_gather_event_data` performs ALL data policy (including the ADR-0079
canonical-read exceedance dedup) exactly once; `generate_event_report` and
`generate_event_report_html` are thin renderers over its output so the two
formats can never disagree on counts.

No arcpy dependency. No openpyxl. Pure stdlib.
"""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Optional

from autogis.core.common import report_html as rh
from autogis.core.common.qa import QACollector, SEV_INFO
from autogis.core.envmon.canonical_read import canonical_result_rows

_EXCEED_TRUE = ("1", "True", "true", "YES")


def _exceeds(row: dict) -> bool:
    return str(row.get("ExceedsScreeningLevel", "")).strip() in _EXCEED_TRUE


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


def _gather_event_data(
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
) -> dict:
    """Compute all counts/rows shared by the Markdown and HTML renderers.

    Canonical-reads the raw results before counting so QC rows and
    Total/Dissolved pairs don't inflate n_results / n_exceedances (ADR-0079).
    apply_screening stamps ExceedsScreeningLevel on every raw row, so that
    flag alone is not exceedance-count-safe. The other inputs are already-
    canonical tool outputs. No-op on legacy CSVs lacking discriminators.
    """
    generated = (generated_date or date.today()).isoformat()
    results = canonical_result_rows(_load_csv(results_csv), qa)
    comparisons = _load_csv(comparison_csv)
    history = _load_csv(history_csv)
    gaps = _load_csv(gaps_csv)
    rpd = _load_csv(rpd_qa_csv)

    n_results = len(results)
    exceed_results = [r for r in results if _exceeds(r)]
    n_exceedances = len(exceed_results)
    n_gaps = len(gaps)
    n_rpd_errors = sum(1 for r in rpd
                        if str(r.get("severity", "")).upper() == "ERROR")

    summary_rows = [
        ["Total analytical results", n_results],
        ["Screening level exceedances", n_exceedances],
        ["Data gaps identified", n_gaps],
        ["RPD QA errors", n_rpd_errors],
    ]

    trend_rows = None
    if comparisons:
        counts: dict = {}
        for r in comparisons:
            t = str(r.get("TrendLabel", r.get("TrendVsPrevious", "UNKNOWN"))).upper()
            counts[t] = counts.get(t, 0) + 1
        trend_rows = [[t, c] for t, c in sorted(counts.items())]

    history_rows = None
    if history:
        exceed_hist = [h for h in history
                       if str(h.get("LatestExceedance", "")).strip() in ("1", "True", "true")]
        shown = (exceed_hist or history)[:10]
        history_rows = [[h.get("LocationID", ""), h.get("AnalyteCanonicalName", ""),
                         h.get("NTotal", ""), h.get("TrendVsPrevious", ""),
                         h.get("LatestResult", "")] for h in shown]

    gap_rows = [[g.get("LocationID", g.get("location_id", "")),
                 g.get("AnalyteName", g.get("analyte", "")),
                 g.get("Status", g.get("status", "")),
                 g.get("Detail", g.get("detail", ""))] for g in gaps[:20]]
    gaps_overflow = max(0, len(gaps) - 20)

    rpd_error_rows = None
    if n_rpd_errors:
        errs = [r for r in rpd if str(r.get("severity", "")).upper() == "ERROR"][:10]
        rpd_error_rows = [[r.get("location_id", r.get("LocationID", "")),
                           r.get("analyte", r.get("AnalyteName", "")),
                           r.get("message", r.get("Message", ""))] for r in errs]

    # HTML-only detail (MD output is intentionally unchanged): the list of
    # exceeding results. Every row here exceeds screening by construction, so
    # the renderer tones them all "bad". Cap mirrors the other detail sections.
    exceedance_rows = [[r.get("LocationID", ""), r.get("AnalyteCanonicalName", ""),
                        r.get("DisplayText", r.get("ResultRawText", "")),
                        r.get("ScreeningLevel", "")]
                       for r in exceed_results[:20]]

    return {
        "site_id": site_id, "event_id": event_id, "generated": generated,
        "n_results": n_results, "n_exceedances": n_exceedances,
        "n_gaps": n_gaps, "n_rpd_errors": n_rpd_errors, "rpd_total": len(rpd),
        "summary_rows": summary_rows, "trend_rows": trend_rows,
        "history_rows": history_rows, "gap_rows": gap_rows,
        "gaps_overflow": gaps_overflow, "rpd_error_rows": rpd_error_rows,
        "exceedance_rows": exceedance_rows,
    }


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
    d = _gather_event_data(
        site_id, event_id, results_csv=results_csv, comparison_csv=comparison_csv,
        history_csv=history_csv, gaps_csv=gaps_csv, rpd_qa_csv=rpd_qa_csv,
        generated_date=generated_date, qa=qa,
    )
    lines = [
        f"# Monitoring Event Report — {site_id} / {event_id}", "",
        f"**Generated:** {d['generated']}  ", f"**Site:** {site_id}  ",
        f"**Event:** {event_id}  ", "",
        "## Executive Summary", "",
        _md_table(["Metric", "Value"], d["summary_rows"]), "",
    ]
    if d["trend_rows"] is not None:
        lines += ["## Trend vs Previous Event", "",
                  _md_table(["Trend", "Count"], d["trend_rows"]), ""]
    if d["history_rows"] is not None:
        lines += ["## History Summary (Top 10)", "",
                  _md_table(["Location", "Analyte", "N Total", "Trend", "Latest Result"],
                            d["history_rows"]), ""]
    if d["gap_rows"]:
        lines += ["## Data Gaps", "",
                  _md_table(["Location", "Analyte", "Status", "Detail"], d["gap_rows"])]
        if d["gaps_overflow"]:
            lines.append(f"*... and {d['gaps_overflow']} more gap(s) in the full CSV.*")
        lines.append("")
    if d["rpd_total"]:
        lines += ["## Duplicate RPD QA", "",
                  f"{d['rpd_total']} RPD QA record(s) — {d['n_rpd_errors']} ERROR(s).", ""]
        if d["rpd_error_rows"] is not None:
            lines += [_md_table(["Location", "Analyte", "Message"], d["rpd_error_rows"]), ""]
    lines += ["---", "*Report generated by AutoGIS `envmon generate-event-report`.*", ""]
    content = "\n".join(lines)
    qa.add(SEV_INFO, "generate_event_report_complete",
           f"generate_event_report: {site_id}/{event_id}, {len(lines)} lines, "
           f"{d['n_results']} results, {d['n_exceedances']} exceedances")
    return content


def generate_event_report_html(
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
    """Self-contained HTML monitoring event report (mirror of the MD tool)."""
    d = _gather_event_data(
        site_id, event_id, results_csv=results_csv, comparison_csv=comparison_csv,
        history_csv=history_csv, gaps_csv=gaps_csv, rpd_qa_csv=rpd_qa_csv,
        generated_date=generated_date, qa=qa,
    )
    kpi = rh.kpi_row([
        ("Results", d["n_results"], "neutral"),
        ("Exceedances", d["n_exceedances"], "bad" if d["n_exceedances"] else "ok"),
        ("Data gaps", d["n_gaps"], "warn" if d["n_gaps"] else "ok"),
        ("RPD errors", d["n_rpd_errors"], "bad" if d["n_rpd_errors"] else "ok"),
    ])
    sections = [rh.section("Executive Summary", kpi)]
    if d["exceedance_rows"]:
        # Every row exceeds screening, so the Status cell is uniformly "EXCEED"
        # with a "bad" tone. The tone must color the cell via tone_of, not be an
        # embedded badge() string: table() escapes cell text, so a badge's HTML
        # would render as visible markup.
        rows = [[r[0], r[1], r[2], r[3], "EXCEED"] for r in d["exceedance_rows"]]
        body = rh.table(
            ["Location", "Analyte", "Result", "Screening Level", "Status"], rows,
            tone_of=lambda i, j: "bad" if j == 4 else None,
        )
        sections.append(rh.section("Screening Exceedances", body))
    if d["trend_rows"] is not None:
        sections.append(rh.section("Trend vs Previous Event",
                                   rh.table(["Trend", "Count"], d["trend_rows"])))
    if d["history_rows"] is not None:
        sections.append(rh.section("History Summary (Top 10)", rh.table(
            ["Location", "Analyte", "N Total", "Trend", "Latest Result"], d["history_rows"])))
    if d["gap_rows"]:
        gaps_tbl = rh.table(["Location", "Analyte", "Status", "Detail"], d["gap_rows"])
        extra = (f'<p><em>… and {d["gaps_overflow"]} more gap(s) in the full CSV.</em></p>'
                 if d["gaps_overflow"] else "")
        sections.append(rh.section("Data Gaps", gaps_tbl + extra))
    if d["rpd_total"]:
        rpd_body = f'<p>{d["rpd_total"]} RPD QA record(s) — {d["n_rpd_errors"]} ERROR(s).</p>'
        if d["rpd_error_rows"] is not None:
            rpd_body += rh.table(["Location", "Analyte", "Message"], d["rpd_error_rows"])
        sections.append(rh.section("Duplicate RPD QA", rpd_body))
    return rh.render_document(
        title=f"Monitoring Event Report — {site_id} / {event_id}",
        meta={"Site": site_id, "Event": event_id},
        sections=sections, generated=d["generated"],
    )
