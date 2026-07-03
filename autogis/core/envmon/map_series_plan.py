"""Arcpy-free planner for GenerateSiteMapSeries (Tool 5.6).

Expands a site x event x figure-spec matrix into an ordered, deterministically
named job list. The arcpy export loop lives in the ``gen-map-series`` CLI
command (adapters/cli.py), which replays the proven ExportFigures chain per
job — this module stays pure stdlib.

Spec: docs/superpowers/specs/2026-06-28-generate-site-map-series-design.md
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List

MODES = ("per_site", "per_map_type", "combined_appendix", "historical")
FORMATS = ("pdf", "png")


@dataclass(frozen=True)
class MapJob:
    site_id: str
    event: str
    figure_spec: str
    out_name: str      # deterministic file name (with extension)
    out_format: str    # pdf | png


def _safe(s: str) -> str:
    """Filesystem-safe token: any run outside [A-Za-z0-9_.-] becomes '_'."""
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s.strip())


def _dedupe(items: Iterable[str]) -> List[str]:
    return list(dict.fromkeys(items))


def plan_map_series(
    sites: List[str],
    events: List[str],
    figure_specs: List[str],
    *,
    mode: str = "per_site",
    out_format: str = "pdf",
) -> List[MapJob]:
    """Expand the site x event x figure-spec matrix into an ordered job list.

    The four packet modes are selectors over the same matrix expansion, not
    separate code paths: they differ only in grouping order and file naming.
    Every out_name embeds the full (site, event, spec) triple, so names are
    unique across the matrix; inputs are deduplicated preserving order.
    """
    if mode not in MODES:
        raise ValueError(f"Unknown mode {mode!r}; use one of {MODES}")
    if out_format not in FORMATS:
        raise ValueError(
            f"Unknown out_format {out_format!r}; use one of {FORMATS}")

    sites = _dedupe(sites)
    events = _dedupe(events)
    figure_specs = _dedupe(figure_specs)

    if mode == "per_map_type":       # group packets by figure spec
        triples = [(s, e, f) for f in figure_specs for s in sites for e in events]
    elif mode == "historical":       # group packets by event (input order)
        triples = [(s, e, f) for e in events for s in sites for f in figure_specs]
    else:                            # per_site / combined_appendix: by site
        triples = [(s, e, f) for s in sites for e in events for f in figure_specs]

    jobs: List[MapJob] = []
    for i, (s, e, f) in enumerate(triples, start=1):
        if mode == "combined_appendix":
            stem = f"Appendix_{i:03d}_{_safe(s)}_{_safe(e)}_{_safe(f)}"
        elif mode == "per_map_type":
            stem = f"{_safe(f)}_{_safe(s)}_{_safe(e)}"
        elif mode == "historical":
            stem = f"{_safe(s)}_{_safe(f)}_{_safe(e)}"
        else:  # per_site
            stem = f"{_safe(s)}_{_safe(e)}_{_safe(f)}"
        jobs.append(MapJob(site_id=s, event=e, figure_spec=f,
                           out_name=f"{stem}.{out_format}",
                           out_format=out_format))
    return jobs
