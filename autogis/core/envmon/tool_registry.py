"""tool_registry.py — Tool 10.1 ListAvailableEnvTools.

Query / filter / format the human-facing tool registry that backs the
`envmon list-tools` discovery command. The registry data itself lives in
``autogis.runtime.capabilities.TOOL_REGISTRY`` (single source of truth);
this module is the pure, arcpy-free query + rendering layer.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from ...runtime.capabilities import TOOL_REGISTRY


@dataclass
class ToolEntry:
    command: str
    name: str
    roadmap_id: str
    runtime: str            # CLOUD | LOCAL | DRAFT
    status: str             # stable | draft | planned
    domain: str
    description: str
    plan_path: str = ""


def get_all_tools() -> List[ToolEntry]:
    """Return all registered tool entries (sorted by domain then command)."""
    entries = [
        ToolEntry(
            command=c.command, name=c.name, roadmap_id=c.roadmap_id,
            runtime=c.runtime, status=c.status, domain=c.domain,
            description=c.description, plan_path=c.plan_path,
        )
        for c in TOOL_REGISTRY
    ]
    return sorted(entries, key=lambda t: (t.domain, t.command))


def filter_tools(
    entries: List[ToolEntry],
    *,
    runtime: Optional[str] = None,
    domain: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
) -> List[ToolEntry]:
    """Filter entries by any combination of criteria (case-insensitive)."""
    out = list(entries)
    if runtime:
        out = [t for t in out if t.runtime.upper() == runtime.upper()]
    if domain:
        out = [t for t in out if t.domain.lower() == domain.lower()]
    if status:
        out = [t for t in out if t.status.lower() == status.lower()]
    if search:
        needle = search.lower()
        out = [t for t in out
               if needle in f"{t.command} {t.name} {t.description}".lower()]
    return out


def _render(rows: List[List[str]], headers: List[str]) -> str:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    sep = "  ".join("-" * widths[i] for i in range(len(headers)))
    body = [
        "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row))
        for row in rows
    ]
    return "\n".join([line, sep] + body)


def format_tool_table(entries: List[ToolEntry], *, verbose: bool = False) -> str:
    """Render entries as a fixed-width text table.

    Compact: command | runtime | domain | description
    Verbose: + roadmap_id | status | plan_path
    """
    if verbose:
        headers = ["command", "runtime", "domain", "status", "roadmap",
                   "description"]
        rows = [[t.command, t.runtime, t.domain, t.status, t.roadmap_id,
                 t.description] for t in entries]
    else:
        headers = ["command", "runtime", "domain", "description"]
        rows = [[t.command, t.runtime, t.domain, t.description]
                for t in entries]
    return _render(rows, headers)
