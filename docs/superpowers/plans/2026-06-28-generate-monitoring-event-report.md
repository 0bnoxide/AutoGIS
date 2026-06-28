# GenerateMonitoringEventReport — Implementation Plan

**Goal:** Add `envmon generate-event-report` CLI command that assembles a human-readable Markdown report for a monitoring event from multiple CSV inputs: analytical results, comparison vs previous event, history summary, data gaps, and RPD evaluation. Output is a single `.md` file suitable for review before report production. Aggregates key metrics in an executive summary table so reviewers can triage without opening individual CSVs. CLOUD runtime — stdlib only, no arcpy.

**Architecture:** New module `autogis/core/envmon/generate_event_report.py`. Core function `generate_event_report(site_id, event_id, *, results_csv, comparison_csv, history_csv, gaps_csv, rpd_qa_csv, generated_date, qa) -> str`. Returns Markdown string. Reads CSVs using stdlib `csv.DictReader`. All inputs optional — missing files produce empty sections rather than errors. CLOUD runtime.

**Tech stack:** Python 3.14, click, stdlib csv/json/datetime. Reuses: `QACollector` from `autogis/core/common/qa.py`. No openpyxl (Markdown output only).

## Global constraints
- `core/` and `adapters/` import without arcpy or arcgis present
- Use openpyxl for Excel (ADR-008) — this plan produces Markdown, not Excel
- New CLI command added to TOOLS in `autogis/runtime/capabilities.py` as `Runtime.CLOUD`
- Run tests with: `python -m pytest -q`
- CLI command goes in `autogis/adapters/cli.py` under the `envmon` group

---

### Task 1: Create `autogis/core/envmon/generate_event_report.py`

**Files:**
- Create: `autogis/core/envmon/generate_event_report.py`

**Complete code:**

```python
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

    # --- History Summary (Top 10 by exceedance, then by location) ---
    if history:
        # Prioritise rows with latest exceedance
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
```

**Steps:**
- [ ] Create module file as shown above
- [ ] Verify `from autogis.core.envmon.generate_event_report import generate_event_report` works without arcpy

---

### Task 2: Write `tests/test_generate_event_report.py`

**Files:**
- Create: `tests/test_generate_event_report.py`

**Complete code:**

```python
"""Tests for generate_event_report (Tool 10.5)."""
from datetime import date
from pathlib import Path

import pytest

from autogis.core.common.qa import QACollector
from autogis.core.envmon.generate_event_report import generate_event_report


def test_minimal_report():
    """Minimal call with no CSV inputs should produce a valid Markdown document."""
    qa = QACollector()
    md = generate_event_report(
        "H281", "2026Q2", qa=qa, generated_date=date(2026, 6, 28)
    )
    assert "# Monitoring Event Report" in md
    assert "H281" in md
    assert "2026Q2" in md


def test_generated_date_in_report():
    qa = QACollector()
    md = generate_event_report(
        "S", "E", qa=qa, generated_date=date(2026, 6, 28)
    )
    assert "2026-06-28" in md


def test_empty_inputs_no_crash():
    """All inputs absent must not crash."""
    qa = QACollector()
    md = generate_event_report("S", "E", qa=qa, generated_date=date(2026, 1, 1))
    assert md.startswith("# Monitoring Event Report")


def test_qa_info_emitted():
    qa = QACollector()
    generate_event_report("S", "E", qa=qa, generated_date=date(2026, 1, 1))
    assert any(r.category == "generate_event_report_complete" for r in qa.records)


def test_results_csv_counted(tmp_path):
    results_csv = tmp_path / "results.csv"
    results_csv.write_text(
        "ExceedsScreeningLevel\n1\n0\n1\n",
        encoding="utf-8",
    )
    qa = QACollector()
    md = generate_event_report(
        "H281", "2026Q2",
        results_csv=results_csv,
        qa=qa,
        generated_date=date(2026, 6, 28),
    )
    assert "Total analytical results | 3" in md
    assert "Screening level exceedances | 2" in md


def test_executive_summary_present():
    qa = QACollector()
    md = generate_event_report(
        "H281", "2026Q2", qa=qa, generated_date=date(2026, 6, 28)
    )
    assert "## Executive Summary" in md


def test_comparison_csv_produces_trend_section(tmp_path):
    comp_csv = tmp_path / "comparison.csv"
    comp_csv.write_text(
        "TrendLabel\nINCREASE\nINCREASE\nDECREASE\n",
        encoding="utf-8",
    )
    qa = QACollector()
    md = generate_event_report(
        "H281", "2026Q2",
        comparison_csv=comp_csv,
        qa=qa,
        generated_date=date(2026, 6, 28),
    )
    assert "## Trend vs Previous Event" in md
    assert "INCREASE" in md
    assert "DECREASE" in md


def test_gaps_csv_produces_data_gaps_section(tmp_path):
    gaps_csv = tmp_path / "gaps.csv"
    gaps_csv.write_text(
        "LocationID,AnalyteName,Status,Detail\n"
        "MW-1,Benzene,MISSING,Not sampled\n",
        encoding="utf-8",
    )
    qa = QACollector()
    md = generate_event_report(
        "H281", "2026Q2",
        gaps_csv=gaps_csv,
        qa=qa,
        generated_date=date(2026, 6, 28),
    )
    assert "## Data Gaps" in md
    assert "MW-1" in md
    assert "MISSING" in md


def test_history_csv_top_10(tmp_path):
    history_csv = tmp_path / "history.csv"
    rows = "\n".join(
        f"MW-{i},Benzene,GW,5,5,0,1.0,10.0,5.5,2026-04-01,5.0,1,INCREASE,ug/L"
        for i in range(15)
    )
    history_csv.write_text(
        "LocationID,AnalyteCanonicalName,Matrix,NTotal,NDetects,NNonDetects,"
        "MinResult,MaxResult,MeanResult,LatestDate,LatestResult,LatestExceedance,"
        "TrendVsPrevious,Units\n" + rows,
        encoding="utf-8",
    )
    qa = QACollector()
    md = generate_event_report(
        "H281", "2026Q2",
        history_csv=history_csv,
        qa=qa,
        generated_date=date(2026, 6, 28),
    )
    assert "## History Summary" in md


def test_rpd_section_shown(tmp_path):
    rpd_csv = tmp_path / "rpd.csv"
    rpd_csv.write_text(
        "severity,location_id,analyte,message\n"
        "ERROR,MW-1,Benzene,RPD 35% exceeds 20% limit\n",
        encoding="utf-8",
    )
    qa = QACollector()
    md = generate_event_report(
        "H281", "2026Q2",
        rpd_qa_csv=rpd_csv,
        qa=qa,
        generated_date=date(2026, 6, 28),
    )
    assert "## Duplicate RPD QA" in md
    assert "1 RPD QA record" in md


def test_nonexistent_csv_ignored(tmp_path):
    """Paths that don't exist should be silently skipped."""
    qa = QACollector()
    md = generate_event_report(
        "H281", "2026Q2",
        results_csv=tmp_path / "nonexistent.csv",
        qa=qa,
        generated_date=date(2026, 6, 28),
    )
    assert "# Monitoring Event Report" in md  # report still generated
```

**Steps:**
- [ ] Write test file
- [ ] Run `python -m pytest tests/test_generate_event_report.py -q` — expect ImportError
- [ ] Create `generate_event_report.py` (Task 1)
- [ ] Run tests again — expect all pass

---

### Task 3: Wire CLI command in `autogis/adapters/cli.py`

**Files:**
- Modify: `autogis/adapters/cli.py`

**Complete command code:**

```python
@envmon.command("generate-event-report")
@click.option("--site", "site_id", required=True, help="Site ID.")
@click.option("--event", "event_id", required=True,
              help="Event identifier (e.g. 2026Q2).")
@click.option("--output", required=True, type=click.Path(),
              help="Output Markdown (.md) file path.")
@click.option("--results-csv", default=None, type=click.Path(exists=True),
              help="Analytical results CSV.")
@click.option("--comparison-csv", default=None, type=click.Path(exists=True),
              help="compare-events output CSV.")
@click.option("--history-csv", default=None, type=click.Path(exists=True),
              help="run-history-report output CSV.")
@click.option("--gaps-csv", default=None, type=click.Path(exists=True),
              help="identify-data-gaps output CSV.")
@click.option("--rpd-qa-csv", default=None, type=click.Path(exists=True),
              help="evaluate-rpd-qa output CSV.")
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error",
              show_default=True)
def generate_event_report_cmd(
    site_id, event_id, output,
    results_csv, comparison_csv, history_csv, gaps_csv, rpd_qa_csv,
    report, fail_on,
):
    """Tool 10.5: assemble Markdown monitoring event report from CSV tool outputs."""
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.generate_event_report import generate_event_report

    qa = QACollector()
    content = generate_event_report(
        site_id, event_id,
        results_csv=Path(results_csv) if results_csv else None,
        comparison_csv=Path(comparison_csv) if comparison_csv else None,
        history_csv=Path(history_csv) if history_csv else None,
        gaps_csv=Path(gaps_csv) if gaps_csv else None,
        rpd_qa_csv=Path(rpd_qa_csv) if rpd_qa_csv else None,
        qa=qa,
    )
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8")
    click.echo(f"Written: {out}")
    _render_qa(qa, report, fail_on)
```

**Steps:**
- [ ] Add command to `autogis/adapters/cli.py`
- [ ] Add `"generate-event-report": Runtime.CLOUD` to `TOOLS` dict in `autogis/runtime/capabilities.py`
- [ ] Run `python -m pytest -q` — expect all pass
- [ ] Commit: `feat(envmon): generate-event-report — Markdown monitoring event report assembly (Tool 10.5)`

---

## Run commands

```bash
# TDD step 1: verify tests fail before module exists
python -m pytest tests/test_generate_event_report.py -q

# TDD step 2: after creating generate_event_report.py
python -m pytest tests/test_generate_event_report.py -q

# TDD step 3: full suite
python -m pytest -q
```
