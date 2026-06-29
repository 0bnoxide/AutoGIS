# ListAvailableEnvTools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Implement `ListAvailableEnvTools` — introduce a `ToolCapability` dataclass to `capabilities.py`, add metadata fields, and expose a `list-tools` CLI command with runtime/domain/status filtering.
See spec: `docs/superpowers/specs/2026-06-28-list-available-env-tools-design.md`.

**Architecture:**
- Modify: `autogis/runtime/capabilities.py` — add `ToolCapability` dataclass; convert `TOOLS` dict to `TOOL_REGISTRY` list; keep `requires_arcpy()` working
- New: `autogis/core/envmon/tool_registry.py` — query/filter/format helpers
- Modify: `autogis/adapters/cli.py` — add `list-tools` command (headless)
- New: `tests/test_tool_registry.py`

## Global Constraints

- Arcpy-free. stdlib only: `dataclasses`, `textwrap`.
- `requires_arcpy()` must continue to work for all callers; update to use new dataclass.
- Run tests with `python -m pytest -q`.

---

### Task 1: Extend `capabilities.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_tool_registry.py`:

```python
import pytest
from autogis.core.envmon.tool_registry import (
    get_all_tools, filter_tools, format_tool_table, ToolEntry,
)
from autogis.runtime.capabilities import requires_arcpy, ToolCapability, TOOL_REGISTRY


def test_get_all_tools_nonempty():
    tools = get_all_tools()
    assert len(tools) > 0


def test_all_entries_have_command_and_runtime():
    tools = get_all_tools()
    for t in tools:
        assert t.command, f"Empty command in {t}"
        assert t.runtime in ("CLOUD", "LOCAL", "HYBRID", "DRAFT"), \
            f"Bad runtime '{t.runtime}' for {t.command}"


def test_filter_cloud_only():
    tools = get_all_tools()
    cloud = filter_tools(tools, runtime="CLOUD")
    assert all(t.runtime == "CLOUD" for t in cloud)
    assert len(cloud) > 0


def test_filter_local_only():
    tools = get_all_tools()
    local = filter_tools(tools, runtime="LOCAL")
    assert all(t.runtime == "LOCAL" for t in local)


def test_filter_by_domain():
    tools = get_all_tools()
    # Only test if there are entries with domain set
    with_domain = [t for t in tools if t.domain]
    if with_domain:
        domain = with_domain[0].domain
        result = filter_tools(tools, domain=domain)
        assert all(t.domain == domain for t in result)


def test_filter_search_substring():
    tools = get_all_tools()
    result = filter_tools(tools, search="import")
    assert all("import" in t.command.lower() or "import" in t.description.lower()
               for t in result)


def test_filter_no_criteria_returns_all():
    tools = get_all_tools()
    assert filter_tools(tools) == tools


def test_format_tool_table_has_header():
    tools = get_all_tools()
    table = format_tool_table(tools[:3])
    assert "command" in table.lower() or "──" in table


def test_format_tool_table_verbose_roadmap_id():
    tools = [t for t in get_all_tools() if t.roadmap_id]
    if not tools:
        pytest.skip("No tools with roadmap_id populated yet")
    table = format_tool_table(tools[:3], verbose=True)
    assert any(t.roadmap_id in table for t in tools[:3])


def test_requires_arcpy_still_works():
    assert requires_arcpy("import-gdb") is True
    assert requires_arcpy("import-edd") is False
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/test_tool_registry.py -v
```

- [ ] **Step 3: Update `autogis/runtime/capabilities.py`**

Replace the current module content:

```python
"""capabilities.py — tool registry with runtime metadata."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Runtime(Enum):
    CLOUD = "cloud"
    LOCAL = "local"
    HYBRID = "hybrid"


@dataclass
class ToolCapability:
    name: str                    # CLI subcommand name (e.g. "import-edd")
    runtime: str = "CLOUD"       # CLOUD | LOCAL | HYBRID | DRAFT
    roadmap_id: str = ""         # e.g. "2.3"
    status: str = "stable"       # stable | draft | planned
    domain: str = ""             # intake | qa | analysis | cartography | ...
    description: str = ""
    plan_path: str = ""


TOOL_REGISTRY: list[ToolCapability] = [
    ToolCapability("harvest",    runtime="HYBRID",  domain="intake",
                   description="Harvest AGOL attachments"),
    ToolCapability("inspect",    runtime="CLOUD",   domain="qa",
                   description="Inspect GDB / CSV schema (tool 1)"),
    ToolCapability("parser-profile", runtime="CLOUD", domain="admin",
                   description="Manage parser profiles (tool 9)"),
    ToolCapability("figure-spec",    runtime="CLOUD", domain="admin",
                   description="Manage figure specs (tool 10)"),
    ToolCapability("import-gdb",  runtime="LOCAL", domain="intake",
                   description="Import GDB into envmon tables (tool 2)"),
    ToolCapability("build-event", runtime="LOCAL", domain="analysis",
                   description="Build analytical monitoring event (tool 3)"),
    ToolCapability("build-callouts", runtime="LOCAL", domain="cartography",
                   description="Build analytical callout boxes (tool 4)"),
    ToolCapability("gw-contours",    runtime="LOCAL", domain="analysis",
                   description="Generate GW contour features (tool 5)"),
    ToolCapability("export-figures", runtime="LOCAL", domain="reporting",
                   description="Export figures to PDF (tool 6)"),
    ToolCapability("full-pipeline",  runtime="LOCAL", domain="analysis",
                   description="Run full envmon pipeline (tool 7)"),
    ToolCapability("validate-db",    runtime="LOCAL", domain="qa",
                   description="Validate envmon GDB schema (tool 8)"),
    ToolCapability("validate-config", runtime="CLOUD", domain="admin",
                   description="Validate site config YAML"),
    ToolCapability("manage-analyte-dict", runtime="CLOUD", domain="admin",
                   description="Manage analyte dictionary"),
    ToolCapability("validate-units",   runtime="CLOUD", domain="qa",
                   description="Validate unit consistency"),
    ToolCapability("reconcile-locations", runtime="HYBRID", domain="qa",
                   description="Reconcile sample location IDs"),
    ToolCapability("import-edd",  runtime="CLOUD", domain="intake",
                   description="Import lab EDD CSV/XLSX"),
    ToolCapability("upgrade-schema", runtime="LOCAL", domain="admin",
                   description="Upgrade envmon GDB schema (phase 1.4)"),
    ToolCapability("export-snapshot", runtime="LOCAL", domain="reporting",
                   description="Export envmon data snapshot"),
    ToolCapability("evaluate-rpd",  runtime="CLOUD", domain="qa",
                   description="Evaluate relative percent difference"),
    ToolCapability("manage-screening-levels", runtime="CLOUD", domain="admin",
                   description="Manage screening levels"),
    ToolCapability("optimize-callouts", runtime="LOCAL", domain="cartography",
                   description="Optimize callout placement (tool 5.2)"),
    ToolCapability("manage-callout-overrides", runtime="LOCAL", domain="cartography",
                   description="Manage callout position overrides (tool 5.3)"),
    ToolCapability("build-survey-form", runtime="CLOUD", domain="field",
                   description="Build Survey123 XLSForm (tool 7.1a)"),
    ToolCapability("compare-events", runtime="CLOUD", domain="analysis",
                   description="Compare analytical events (tool 4.7)"),
    ToolCapability("process-level-loop", runtime="CLOUD", domain="analysis",
                   description="Run level-loop closure (tool 8.1)"),
    ToolCapability("identify-data-gaps", runtime="CLOUD", domain="qa",
                   description="Identify data gaps (tool 4.10)"),
    ToolCapability("run-history-report", runtime="CLOUD", domain="reporting",
                   description="Generate history report (tool 10.1)"),
    ToolCapability("validate-schedule", runtime="CLOUD", domain="qa",
                   description="Validate sampling schedule (tool 10.2)"),
    ToolCapability("apply-screening", runtime="CLOUD", domain="analysis",
                   description="Apply screening levels (tool 3.5)"),
    ToolCapability("compare-schedule-vs-actual", runtime="CLOUD", domain="qa",
                   description="Compare schedule vs actual samples (tool 10.x)"),
    ToolCapability("drone-checkpoint-qa", runtime="CLOUD", domain="field",
                   description="GCP checkpoint QA (tool 11.1)"),
    ToolCapability("export-geojson", runtime="CLOUD", domain="reporting",
                   description="Export results as GeoJSON (tool 10.3)"),
    ToolCapability("generate-event-report", runtime="CLOUD", domain="reporting",
                   description="Generate monitoring event report (tool 10.5)"),
    ToolCapability("run-history", runtime="CLOUD", domain="reporting",
                   description="Query run history (tool 10.1b)"),
]

# Backwards-compatible name→runtime mapping (for requires_arcpy)
TOOLS: dict[str, Runtime] = {
    t.name: Runtime[t.runtime] if t.runtime in ("CLOUD", "LOCAL", "HYBRID")
    else Runtime.CLOUD
    for t in TOOL_REGISTRY
}


def requires_arcpy(name: str) -> bool:
    return TOOLS[name] is Runtime.LOCAL
```

- [ ] **Step 4: Create `autogis/core/envmon/tool_registry.py`**

```python
"""tool_registry.py — query, filter, format the envmon tool registry."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from autogis.runtime.capabilities import TOOL_REGISTRY, ToolCapability


@dataclass
class ToolEntry:
    command: str
    name: str
    roadmap_id: str
    runtime: str
    status: str
    domain: str
    description: str
    plan_path: str


def _cap_to_entry(cap: ToolCapability) -> ToolEntry:
    return ToolEntry(
        command=cap.name,
        name=cap.name,
        roadmap_id=cap.roadmap_id,
        runtime=cap.runtime,
        status=cap.status,
        domain=cap.domain,
        description=cap.description,
        plan_path=cap.plan_path,
    )


def get_all_tools() -> list:
    return [_cap_to_entry(c) for c in TOOL_REGISTRY]


def filter_tools(
    entries: list,
    *,
    runtime: Optional[str] = None,
    domain: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
) -> list:
    result = entries
    if runtime:
        result = [t for t in result if t.runtime.upper() == runtime.upper()]
    if domain:
        result = [t for t in result if t.domain.lower() == domain.lower()]
    if status:
        result = [t for t in result if t.status.lower() == status.lower()]
    if search:
        s = search.lower()
        result = [t for t in result
                  if s in t.command.lower() or s in t.description.lower()
                  or s in t.name.lower()]
    return result


def format_tool_table(entries: list, *, verbose: bool = False) -> str:
    if not entries:
        return "(no tools match)"

    if verbose:
        cols = ["command", "runtime", "domain", "roadmap_id", "status", "description"]
        widths = [32, 8, 14, 10, 8, 48]
    else:
        cols = ["command", "runtime", "domain", "description"]
        widths = [32, 8, 14, 48]

    def _cell(val: str, w: int) -> str:
        return val[:w].ljust(w)

    sep = "  "
    header = sep.join(_cell(c, w) for c, w in zip(cols, widths))
    rule = sep.join("─" * w for w in widths)
    rows = [header, rule]

    for t in entries:
        vals = [
            getattr(t, c if c != "command" else "command", "")
            for c in cols
        ]
        rows.append(sep.join(_cell(str(v), w) for v, w in zip(vals, widths)))

    return "\n".join(rows)
```

- [ ] **Step 5: Run tests**

```
python -m pytest tests/test_tool_registry.py -v
```

Expected: all 10 PASS.

- [ ] **Step 6: Full suite + commit**

```bash
git add autogis/runtime/capabilities.py \
        autogis/core/envmon/tool_registry.py \
        tests/test_tool_registry.py
git commit -m "feat(envmon): tool_registry — ToolCapability dataclass + filter/format helpers"
```

---

### Task 2: CLI command

- [ ] **Step 1: Add to `cli.py`**

```python
@envmon.command("list-tools")
@click.option("--runtime", default=None,
              type=click.Choice(["CLOUD", "LOCAL", "HYBRID", "DRAFT"],
                                case_sensitive=False))
@click.option("--domain", default=None)
@click.option("--status", default=None,
              type=click.Choice(["stable", "draft", "planned"],
                                case_sensitive=False))
@click.option("--search", default=None, help="Substring match on name/description.")
@click.option("--verbose", "-v", is_flag=True, default=False)
def list_tools_cmd(runtime, domain, status, search, verbose):
    """List available envmon tools with runtime and domain metadata (headless)."""
    from autogis.core.envmon.tool_registry import (
        get_all_tools, filter_tools, format_tool_table)

    tools = get_all_tools()
    tools = filter_tools(tools, runtime=runtime, domain=domain,
                         status=status, search=search)
    click.echo(format_tool_table(tools, verbose=verbose))
    click.echo(f"\n{len(tools)} tool(s) shown.")
```

- [ ] **Step 2: Help test + commit**

```python
def test_list_tools_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "list-tools" in result.output


def test_list_tools_runs():
    result = CliRunner().invoke(autogis, ["envmon", "list-tools"])
    assert result.exit_code == 0
    assert "tool(s) shown" in result.output
```

```bash
git add autogis/adapters/cli.py tests/test_tool_registry.py
git commit -m "feat(cli): add list-tools command with runtime/domain/search filtering"
```
