"""Cross-site portfolio metrics rollup (headless).

Reads a (possibly multi-site) run_history.csv and reports per-site report
readiness by reusing evaluate_readiness() for every distinct site_id found in
the log. No new schema, no arcpy — RunRecord already carries site_id.
"""
from __future__ import annotations

import csv
import dataclasses
from pathlib import Path
from typing import List, Optional

from ..common.qa import QACollector, SEV_INFO
from ..common.run_history import RunHistory
from .evaluate_readiness import evaluate_readiness


@dataclasses.dataclass
class SitePortfolioStatus:
    """Per-site report-readiness rollup."""
    site_id: str
    ready: bool
    missing_tools: str    # semicolon-joined tool names; "" if none missing
    total_runs: int
    last_activity: str    # ISO timestamp of the most recent run; "" if none


def discover_site_ids(run_history: RunHistory) -> List[str]:
    """Return sorted distinct site_ids present in the run history log."""
    return sorted({r.site_id for r in run_history.query()})


def build_portfolio_metrics(
    run_history: RunHistory,
    required_tools: List[str],
    *,
    site_ids: Optional[List[str]] = None,
    qa: QACollector,
) -> List[SitePortfolioStatus]:
    """Roll up per-site report readiness across every site in the run history.

    Args:
        run_history: RunHistory over a (possibly multi-site) run_history.csv.
        required_tools: Tool names that must have a successful run per site.
        site_ids: Optional explicit site list; default discovers every
            distinct site_id present in the log.
        qa: QACollector for the portfolio-level summary message.

    Returns:
        One SitePortfolioStatus per site, sorted by site_id.
    """
    sites = site_ids if site_ids is not None else discover_site_ids(run_history)

    statuses: List[SitePortfolioStatus] = []
    for site_id in sites:
        site_qa = evaluate_readiness(
            site_id=site_id, event_id=None, run_history=run_history,
            required_tools=required_tools,
        )
        ready = site_qa.status() == "PASS"

        missing = []
        for tool in required_tools:
            latest = run_history.latest(tool, site_id)
            if latest is None or latest.status != "success":
                missing.append(tool)

        # missing[] is recomputed independently of evaluate_readiness()'s own
        # pass/fail (see ADR-0030) so it can't silently drift from `ready` if
        # evaluate_readiness() ever grows another failure path (e.g. a
        # qa_csv/figure_spec check) — flag disagreement instead of hiding it.
        if ready != (not missing):
            qa.add(SEV_INFO, "portfolio_status_inconsistent",
                   f"Site {site_id!r}: evaluate_readiness() ready={ready} but "
                   f"missing-tools recomputation found {missing or 'none'}; "
                   f"evaluate_readiness()'s status() is authoritative for `ready`.",
                   site_id=site_id)

        site_records = run_history.query(site_id=site_id)
        last_activity = (
            max(r.finished_at for r in site_records).isoformat(timespec="seconds")
            if site_records else ""
        )

        statuses.append(SitePortfolioStatus(
            site_id=site_id,
            ready=ready,
            missing_tools=";".join(missing),
            total_runs=len(site_records),
            last_activity=last_activity,
        ))

    n_ready = sum(1 for s in statuses if s.ready)
    qa.add(SEV_INFO, "portfolio_metrics_complete",
           f"Portfolio: {n_ready}/{len(statuses)} site(s) report-ready "
           f"({len(required_tools)} required tool(s) checked)")
    return statuses


def write_portfolio_csv(statuses: List[SitePortfolioStatus], output_path: Path) -> None:
    """Write one row per site to CSV."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [f.name for f in dataclasses.fields(SitePortfolioStatus)]
    with open(output_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for s in statuses:
            writer.writerow(dataclasses.asdict(s))
