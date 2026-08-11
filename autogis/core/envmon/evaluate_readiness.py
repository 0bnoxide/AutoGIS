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

# Tools that structurally cannot carry a site identity: their CLI commands
# accept no site parameter at all, and their .pyt counterparts are decorated
# `site_config_param=None`, so BOTH execution paths record site_id="" (#412).
#
# This is a deliberate ALLOWLIST, not "any record whose site_id is empty".
# `_record_site_id` also returns "" for the many per-site commands identified
# by --gdb/--results rather than --site-id, and for any command whose site
# config merely failed to load. Treating every "" record as site-agnostic
# would let a run against ANOTHER site's data satisfy this site's delivery
# gate — a false PASS on the report-readiness check, which is worse than the
# unsatisfiable check it was meant to fix.
#
# RESIDUAL, accepted knowingly: these tools are not site-*free*, they are
# site-*unattributed*. `validate-db --gdb <a site's gdb>` plainly concerns one
# site; `_record_site_id` simply cannot parse a site out of a path (#412
# rejected doing so as fragile — a path is not a site_id). So one site-less
# record satisfies EVERY site's check. That is why the widened match is a
# WARNING and not an INFO: it must not read as a clean PASS, and
# `--fail-on warning` must be able to catch it.
# A .pyt `site_config_param=None` decoration is NECESSARY but NOT SUFFICIENT for
# membership — this list is curated, and deliberately stays at the six tools
# #412 scoped. ADR-0125/#447 later decorated five more (harvest, inspect,
# parser-profile, figure-spec, download-dem); they are *not* admitted here,
# because none of them is evidence that anything happened for a given site.
SITE_LESS_TOOLS = frozenset({
    "validate-db", "condition-dem", "compare-drone-surfaces",
    "build-cad-package", "export-civil3d", "transform-landxml",
})


def latest_run(run_history: RunHistory, tool: str, site_id: str):
    """Return ``(record_or_None, matched_site_less)`` for `tool` at `site_id`.

    The single definition of "has this tool run for this site", shared by
    `evaluate_readiness` and `portfolio_metrics` so the two cannot disagree
    about it — `portfolio_metrics` recomputes its `missing` list independently
    and flags drift, so a widening applied to only one of them produces a row
    that is internally self-contradictory (`ready=True` next to
    `missing_tools=...`).

    Raises `RunHistoryError` from the underlying reads; callers handle it.
    """
    latest = run_history.latest(tool, site_id)
    if latest is None and site_id and tool in SITE_LESS_TOOLS:
        latest = run_history.latest(tool, "")
        return latest, latest is not None
    return latest, False


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
            # Strict equality in RunHistory.latest() can never match a tool
            # that records site_id="" on every path, so the check was
            # unsatisfiable AND its recommended action ("run it again") wrote
            # another unmatchable record — the operator loops forever (#412).
            # latest_run() widens to the site-less series for exactly the tools
            # that cannot carry a site, and for no others.
            latest, site_less_match = latest_run(run_history, tool, site_id)
        except RunHistoryError as exc:
            qa.add(SEV_ERROR, "run_history_unreadable",
                   f"cannot read run history: {exc}", site_id=site_id)
            failed.append(tool)
            continue

        if site_less_match:
            qa.add(SEV_WARNING, "tool_run_not_site_scoped",
                   f"tool {tool!r} has no site-scoped run record; matched its "
                   f"site-less run history instead (it takes no site input, so "
                   f"it records site_id=\"\"). That record may be from a run "
                   f"against a DIFFERENT site — it cannot be attributed.",
                   site_id=site_id,
                   recommended_action=f"confirm {tool!r} was run against this "
                                      f"site's data, or use --fail-on warning "
                                      f"to treat an unattributable run as a "
                                      f"failure")

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
