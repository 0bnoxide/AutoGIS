"""Evaluate whether a monitoring event is ready for report delivery.

Checks that required tools have run successfully for the event, flags any
import QA errors, and optionally validates the figure spec.  All inputs are
files or in-memory objects — no arcpy required.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import List, Optional

from ..common.qa import QACollector, SEV_ERROR, SEV_INFO, SEV_WARNING
from ..common.run_history import RunHistory, RunHistoryError


def evaluate_readiness(
    site_id: str,
    event_id: Optional[str],
    run_history: RunHistory,
    required_tools: List[str],
    qa_csv: Optional[Path] = None,
    figure_spec_path: Optional[Path] = None,
) -> QACollector:
    """Return a QACollector whose status() reflects report readiness.

    Checks:
    1. Each tool in required_tools has a 'success' run for site_id.
    2. If qa_csv is provided, any ERROR rows yield a QA WARNING.
    3. If figure_spec_path is provided, it must load without error.
    """
    qa = QACollector()
    passed, failed = [], []

    for tool in required_tools:
        try:
            latest = run_history.latest(tool, site_id)
            site_less_match = False
            if latest is None and site_id:
                # Site-less tools record site_id="" on BOTH execution paths:
                # the CLI takes no site input so _record_site_id returns "",
                # and the .pyt decorates with site_config_param=None. Strict
                # equality in RunHistory.latest() therefore never matches a
                # site-scoped lookup, so the check was unsatisfiable AND its
                # recommended action ("run it again") wrote another unmatchable
                # record — the operator loops forever. Fall back to the
                # site-less series rather than reporting a tool that did run as
                # never run (#412). Recorded, not silent: a site-less run is
                # weaker evidence than a site-scoped one.
                latest = run_history.latest(tool, "")
                site_less_match = latest is not None
        except RunHistoryError as exc:
            qa.add(SEV_ERROR, "run_history_unreadable",
                   f"cannot read run history: {exc}", site_id=site_id)
            failed.append(tool)
            continue

        if site_less_match:
            qa.add(SEV_INFO, "tool_run_not_site_scoped",
                   f"tool {tool!r} has no site-scoped run record; matched its "
                   f"site-less run history instead (this tool takes no site "
                   f"input, so it records site_id=\"\").",
                   site_id=site_id)

        if latest is None or latest.status != "success":
            last_status = latest.status if latest else "never run"
            qa.add(SEV_ERROR, "required_tool_not_run",
                   f"tool {tool!r} has not completed successfully for site "
                   f"{site_id!r} (last status: {last_status})",
                   site_id=site_id,
                   recommended_action=f"run 'autogis envmon {tool}' and verify it succeeds")
            failed.append(tool)
        else:
            passed.append(tool)

    if qa_csv is not None and Path(qa_csv).exists():
        error_count = 0
        try:
            with Path(qa_csv).open(newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    if row.get("severity", "").upper() == "ERROR":
                        error_count += 1
        except Exception as exc:
            qa.add(SEV_WARNING, "qa_csv_unreadable",
                   f"cannot read QA report at {qa_csv}: {exc}",
                   site_id=site_id)
        if error_count:
            qa.add(SEV_WARNING, "import_qa_errors_present",
                   f"{error_count} ERROR record(s) found in QA report {Path(qa_csv).name}; "
                   f"review before delivery",
                   site_id=site_id,
                   recommended_action="resolve all QA errors in the import QA report")

    if figure_spec_path is not None:
        from ..common.config import FigureSpec
        try:
            FigureSpec.load(Path(figure_spec_path))
        except Exception as exc:
            qa.add(SEV_WARNING, "figure_spec_invalid",
                   f"figure spec {figure_spec_path} failed to load: {exc}",
                   site_id=site_id)

    summary_parts = []
    if passed:
        summary_parts.append(f"tools passed: {', '.join(passed)}")
    if failed:
        summary_parts.append(f"tools failed/missing: {', '.join(failed)}")
    qa.add(SEV_INFO, "readiness_summary",
           (f"Readiness check for site={site_id!r} event={event_id!r}: "
            + "; ".join(summary_parts)) if summary_parts else "no tools checked",
           site_id=site_id)

    return qa
