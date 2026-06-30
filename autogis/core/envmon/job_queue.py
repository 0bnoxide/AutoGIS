"""Generate an ordered job queue for multi-site batch runs (Tool 10.4).

Builds an ordered list of ``JobEntry`` objects (one per site × tool) ready to be
dispatched by a runner. Tools are ordered CLOUD → HYBRID → LOCAL so headless
ingest runs before local GDB/figure work.

Headless: stdlib + capabilities registry, no arcpy, no openpyxl.
"""
from __future__ import annotations

import dataclasses
from typing import Any, Dict, List, Optional

from ..common.qa import QACollector, SEV_INFO, SEV_WARNING
from ...runtime.capabilities import TOOLS, Runtime

_RUNTIME_ORDER = {Runtime.CLOUD: 0, Runtime.HYBRID: 1, Runtime.LOCAL: 2}


@dataclasses.dataclass
class JobEntry:
    tool: str
    site_id: str
    runtime: str
    args: Dict[str, Any]
    order: int

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


def generate_job_queue(
    site_ids: List[str],
    tool_names: List[str],
    extra_args: Optional[Dict[str, Dict[str, Any]]],
    *,
    qa: QACollector,
) -> List[JobEntry]:
    """Build ordered job-queue entries for the (site × tool) cross-product.

    Tools not in ``capabilities.TOOLS`` emit a WARNING and are skipped. Tools are
    sorted CLOUD → HYBRID → LOCAL, then alphabetically; for each tool, jobs are
    emitted per site. ``extra_args`` may key by ``tool`` and/or ``tool:site_id``
    (the per-site entry overrides the per-tool one).
    """
    extra_args = extra_args or {}

    valid_tools = []
    for name in tool_names:
        if name not in TOOLS:
            qa.add(SEV_WARNING, "unknown_tool",
                   f"Tool {name!r} not in capabilities.TOOLS; skipped")
        else:
            valid_tools.append(name)

    if not valid_tools:
        qa.add(SEV_WARNING, "no_valid_tools",
               "No valid tools specified; job queue is empty.")

    valid_tools.sort(key=lambda t: (_RUNTIME_ORDER.get(TOOLS[t], 99), t))

    entries: List[JobEntry] = []
    order = 0
    for tool in valid_tools:
        runtime = TOOLS[tool]
        for site_id in site_ids:
            args = {**(extra_args.get(tool) or {}),
                    **(extra_args.get(f"{tool}:{site_id}") or {})}
            entries.append(JobEntry(
                tool=tool, site_id=site_id,
                runtime=runtime.value, args=args, order=order))
            order += 1

    qa.add(SEV_INFO, "job_queue_complete",
           f"generate_job_queue: {len(entries)} job(s) for "
           f"{len(valid_tools)} tool(s) × {len(site_ids)} site(s)")
    return entries
