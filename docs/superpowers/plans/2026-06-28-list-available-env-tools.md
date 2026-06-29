# ListAvailableEnvTools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `ListAvailableEnvTools` (roadmap 10.1) — a headless CLI command `autogis envmon list-tools` that introspects the Click command registry and `capabilities.TOOLS` to enumerate all registered envmon commands with their runtime tier (CLOUD/LOCAL/HYBRID), roadmap ID, docstring summary, and live availability in the current runtime.

**Architecture:**
- New: `autogis/core/envmon/list_available_env_tools.py` — pure Python, arcpy-free; defines `TierLabel`, `ToolEntry`, `build_tool_entries()`, `detect_drift()`, `format_tools_table()`, `format_tools_json()`. Receives `arcpy_available: bool` as a parameter; never tries `import arcpy` itself.
- Modify: `autogis/adapters/cli.py` — add `@envmon.command("list-tools")`. The command walks `envmon.commands` (Click introspection) and passes results to the core module. No hand-maintained command list.
- Modify: `autogis/runtime/capabilities.py` — register `"list-tools": Runtime.CLOUD`.
- New: `tests/envmon/test_list_available_env_tools.py`

**Tech Stack:** Python 3.x, click (group introspection via `.commands`), dataclasses, json, re. No arcpy, no arcgis.

## Global Constraints

- `autogis/core/` and `autogis/adapters/` must import with neither `arcpy` nor `arcgis` present. All tests run headless.
- `autogis/core/envmon/list_available_env_tools.py` must NOT import from `autogis/adapters/` (no core→adapter dependency).
- The core module receives `arcpy_available: bool` as a parameter (keeps it pure and testable with no import side-effects).
- The tier registry source of truth is `autogis/runtime/capabilities.TOOLS`. Commands absent from it are tagged `TierLabel.UNKNOWN`.
- `"list-tools"` must be registered in `capabilities.TOOLS` as `Runtime.CLOUD` before any `requires_arcpy()` call can succeed on it.
- The `envmon.commands` dict is iterated at the **top level only** (no recursion into sub-groups). Sub-group commands like `manage-callout-overrides list` are grouped under their parent entry, matching the flat structure of `TOOLS`.
- Do NOT edit `run-history-report`'s docstring. Its "Tool 10.1" label is a numbering quirk predating this feature; fixing it is out of scope and belongs to the `run-history-summary-report` plan.
- Run tests with: `python -m pytest -q`

## Related Plan

`docs/superpowers/plans/2026-06-28-capabilities-registry-completeness.md` fills in the TOOLS gaps for 9 commands that were missing. Apply it before or after this plan — both are independent. The `--check-drift` output of `list-tools` will show `[DRIFT]` warnings until that plan lands, then `[OK]`.

---

### Task 1: Core module `list_available_env_tools.py` + unit tests

**Files:**
- Create: `autogis/core/envmon/list_available_env_tools.py`
- Create: `tests/envmon/test_list_available_env_tools.py`

**Interfaces:**
- Produces:
  - `TierLabel(str, Enum)` with values `CLOUD | LOCAL | HYBRID | UNKNOWN`
  - `ToolEntry` dataclass: `cli_name: str`, `tier: TierLabel`, `roadmap_id: Optional[str]`, `description: str`, `available: bool`, `unavailable_reason: Optional[str]`
  - `_extract_roadmap_id(help_text: str) -> Optional[str]`
  - `build_tool_entries(commands: dict[str, str], tools_registry: dict[str, Any], arcpy_available: bool) -> list[ToolEntry]`
  - `detect_drift(command_names: list[str], tools_registry: dict[str, Any]) -> list[str]`
  - `format_tools_table(entries: list[ToolEntry]) -> str`
  - `format_tools_json(entries: list[ToolEntry]) -> list[dict]`

- [ ] **Step 1: Write the failing tests**

Create `tests/envmon/test_list_available_env_tools.py`:

```python
"""Tests for list_available_env_tools — pure-unit (no Click, no arcpy)."""
import json
import pytest
from enum import Enum

from autogis.core.envmon.list_available_env_tools import (
    TierLabel,
    ToolEntry,
    build_tool_entries,
    detect_drift,
    format_tools_table,
    format_tools_json,
    _extract_roadmap_id,
)


# ---------------------------------------------------------------------------
# Lightweight stand-in for Runtime enum — same .value strings as the real one.
# Using a stand-in keeps the tests independent of capabilities.py, which is
# the adapter/runtime layer. The implementation uses duck-typed .value.lower().
# ---------------------------------------------------------------------------
class _RT(str, Enum):
    CLOUD = "cloud"
    LOCAL = "local"
    HYBRID = "hybrid"


_REGISTRY = {
    "inspect": _RT.CLOUD,
    "import-gdb": _RT.LOCAL,
    "reconcile-locations": _RT.HYBRID,
}


# ---------------------------------------------------------------------------
# _extract_roadmap_id
# ---------------------------------------------------------------------------
def test_extract_roadmap_id_simple():
    assert _extract_roadmap_id("Tool 1: inspect an Excel workbook.") == "1"


def test_extract_roadmap_id_decimal():
    assert _extract_roadmap_id("Tool 4.7: compare current vs previous event.") == "4.7"


def test_extract_roadmap_id_alpha_suffix():
    assert _extract_roadmap_id("Tool 7.1a: generate a Survey123 XLSForm.") == "7.1a"


def test_extract_roadmap_id_no_match():
    assert _extract_roadmap_id("Compare events across monitoring events.") is None


def test_extract_roadmap_id_empty_string():
    assert _extract_roadmap_id("") is None


# ---------------------------------------------------------------------------
# build_tool_entries — tier and availability
# ---------------------------------------------------------------------------
def test_cloud_tool_always_available_headless():
    entries = build_tool_entries(
        commands={"inspect": "Tool 1: inspect an Excel workbook (headless)."},
        tools_registry=_REGISTRY,
        arcpy_available=False,
    )
    assert len(entries) == 1
    e = entries[0]
    assert e.tier == TierLabel.CLOUD
    assert e.available is True
    assert e.unavailable_reason is None


def test_local_tool_unavailable_headless():
    entries = build_tool_entries(
        commands={"import-gdb": "Tool 2: import workbook into GDB (ArcGIS Pro)."},
        tools_registry=_REGISTRY,
        arcpy_available=False,
    )
    e = entries[0]
    assert e.tier == TierLabel.LOCAL
    assert e.available is False
    assert e.unavailable_reason is not None
    assert "arcpy" in e.unavailable_reason.lower()


def test_local_tool_available_when_arcpy_present():
    entries = build_tool_entries(
        commands={"import-gdb": "Tool 2: import workbook into GDB (ArcGIS Pro)."},
        tools_registry=_REGISTRY,
        arcpy_available=True,
    )
    e = entries[0]
    assert e.tier == TierLabel.LOCAL
    assert e.available is True
    assert e.unavailable_reason is None


def test_hybrid_tool_available_headless():
    entries = build_tool_entries(
        commands={"reconcile-locations": "Tool 3.2: reconcile sample locations."},
        tools_registry=_REGISTRY,
        arcpy_available=False,
    )
    e = entries[0]
    assert e.tier == TierLabel.HYBRID
    assert e.available is True


def test_unknown_tier_for_unregistered_command():
    """Commands absent from TOOLS get UNKNOWN tier and are treated as available
    (optimistic: we can't know if they need arcpy)."""
    entries = build_tool_entries(
        commands={"orphan-cmd": "Some unregistered command."},
        tools_registry=_REGISTRY,
        arcpy_available=False,
    )
    e = entries[0]
    assert e.tier == TierLabel.UNKNOWN
    assert e.available is True


def test_entries_sorted_by_name():
    cmds = {"zzz-tool": "Last tool.", "aaa-tool": "First tool."}
    reg = {"zzz-tool": _RT.CLOUD, "aaa-tool": _RT.CLOUD}
    entries = build_tool_entries(cmds, reg, arcpy_available=False)
    names = [e.cli_name for e in entries]
    assert names == sorted(names)


def test_description_is_first_line_only():
    entries = build_tool_entries(
        commands={"inspect": "First line summary.\nSecond line — ignored."},
        tools_registry=_REGISTRY,
        arcpy_available=False,
    )
    assert entries[0].description == "First line summary."
    assert "\n" not in entries[0].description


def test_roadmap_id_extracted_from_help():
    entries = build_tool_entries(
        commands={"inspect": "Tool 1: inspect an Excel workbook."},
        tools_registry=_REGISTRY,
        arcpy_available=False,
    )
    assert entries[0].roadmap_id == "1"


def test_roadmap_id_none_when_no_pattern():
    entries = build_tool_entries(
        commands={"inspect": "Inspect an Excel workbook (no Tool prefix)."},
        tools_registry=_REGISTRY,
        arcpy_available=False,
    )
    assert entries[0].roadmap_id is None


def test_empty_help_text_handled():
    entries = build_tool_entries(
        commands={"inspect": ""},
        tools_registry=_REGISTRY,
        arcpy_available=False,
    )
    assert entries[0].description == ""
    assert entries[0].roadmap_id is None


# ---------------------------------------------------------------------------
# detect_drift
# ---------------------------------------------------------------------------
def test_detect_drift_none_when_all_registered():
    warnings = detect_drift(["inspect", "import-gdb"], _REGISTRY)
    assert warnings == []


def test_detect_drift_finds_unregistered_command():
    warnings = detect_drift(["inspect", "orphan-cmd"], _REGISTRY)
    assert "orphan-cmd" in warnings
    assert "inspect" not in warnings


def test_detect_drift_empty_commands():
    assert detect_drift([], _REGISTRY) == []


def test_detect_drift_all_missing():
    warnings = detect_drift(["x", "y", "z"], {})
    assert set(warnings) == {"x", "y", "z"}


# ---------------------------------------------------------------------------
# format_tools_table
# ---------------------------------------------------------------------------
def test_format_tools_table_contains_command_name():
    entries = build_tool_entries(
        commands={"inspect": "Tool 1: inspect workbook (headless)."},
        tools_registry=_REGISTRY,
        arcpy_available=False,
    )
    table = format_tools_table(entries)
    assert "inspect" in table
    assert "CLOUD" in table


def test_format_tools_table_shows_available_yes():
    entries = build_tool_entries(
        commands={"inspect": "Tool 1: inspect workbook."},
        tools_registry=_REGISTRY,
        arcpy_available=False,
    )
    assert "yes" in format_tools_table(entries).lower()


def test_format_tools_table_shows_available_no_for_local():
    entries = build_tool_entries(
        commands={"import-gdb": "Tool 2: import GDB (ArcGIS Pro)."},
        tools_registry=_REGISTRY,
        arcpy_available=False,
    )
    table = format_tools_table(entries)
    assert "LOCAL" in table
    assert "no" in table.lower()


def test_format_tools_table_contains_header_columns():
    entries = build_tool_entries(
        commands={"inspect": "Tool 1: inspect."},
        tools_registry=_REGISTRY,
        arcpy_available=False,
    )
    table = format_tools_table(entries)
    # Header must have recognisable column labels
    assert "command" in table
    assert "tier" in table
    assert "avail" in table


# ---------------------------------------------------------------------------
# format_tools_json
# ---------------------------------------------------------------------------
def test_format_tools_json_structure():
    entries = build_tool_entries(
        commands={"inspect": "Tool 1: inspect workbook."},
        tools_registry=_REGISTRY,
        arcpy_available=False,
    )
    rows = format_tools_json(entries)
    assert isinstance(rows, list)
    assert len(rows) == 1
    row = rows[0]
    for key in ("cli_name", "tier", "roadmap_id", "description",
                "available", "unavailable_reason"):
        assert key in row, f"Missing key '{key}'"


def test_format_tools_json_is_serializable():
    entries = build_tool_entries(
        commands={"import-gdb": "Tool 2: import GDB."},
        tools_registry=_REGISTRY,
        arcpy_available=False,
    )
    raw = json.dumps(format_tools_json(entries))
    parsed = json.loads(raw)
    assert parsed[0]["tier"] == "LOCAL"
    assert parsed[0]["available"] is False


def test_format_tools_json_available_true_for_cloud():
    entries = build_tool_entries(
        commands={"inspect": "Tool 1: inspect."},
        tools_registry=_REGISTRY,
        arcpy_available=False,
    )
    rows = format_tools_json(entries)
    assert rows[0]["available"] is True
    assert rows[0]["unavailable_reason"] is None
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_list_available_env_tools.py -v
```

Expected: all tests FAIL with `ModuleNotFoundError: No module named 'autogis.core.envmon.list_available_env_tools'`.

- [ ] **Step 3: Create `autogis/core/envmon/list_available_env_tools.py`**

```python
"""list_available_env_tools.py — enumerate registered envmon CLI commands.

Arcpy-free. The arcpy availability check is left to the caller (passed in as
a bool) so this module stays purely importable without any arcpy on the path.

Does NOT import from autogis.adapters (no core→adapter deps).

Typical usage from cli.py:
    from autogis.runtime.capabilities import TOOLS
    from autogis.adapters.guard import _arcpy_present
    from autogis.core.envmon.list_available_env_tools import (
        build_tool_entries, detect_drift, format_tools_table, format_tools_json)

    commands = {name: (cmd.help or "") for name, cmd in envmon.commands.items()}
    entries = build_tool_entries(commands, TOOLS, arcpy_available=_arcpy_present())
"""
from __future__ import annotations

import json as _json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


class TierLabel(str, Enum):
    """Runtime tier for a registered envmon command."""
    CLOUD = "CLOUD"    # headless, arcpy-free — runs in any Python env
    LOCAL = "LOCAL"    # requires arcpy (ArcGIS Pro / cloned arcgispro-py3)
    HYBRID = "HYBRID"  # headless by default; some flags enable arcpy paths
    UNKNOWN = "UNKNOWN"  # registered in CLI but absent from capabilities.TOOLS


@dataclass
class ToolEntry:
    """Single row in the tools listing."""
    cli_name: str                     # e.g. "compare-events"
    tier: TierLabel                   # derived from capabilities.TOOLS
    roadmap_id: Optional[str]         # e.g. "4.7" (from docstring) or None
    description: str                  # first line of the command's help string
    available: bool                   # True when runnable in the current runtime
    unavailable_reason: Optional[str] # non-None only when available is False


# Matches "Tool 4.7:" or "Tool 7.1a:" at the start of a help string.
_ROADMAP_RE = re.compile(
    r"^Tool\s+([\d]+(?:\.[\w]+)?)\s*:",
    re.IGNORECASE,
)


def _extract_roadmap_id(help_text: str) -> Optional[str]:
    """Return roadmap number from a help string like 'Tool 4.7: ...' or None."""
    if not help_text:
        return None
    m = _ROADMAP_RE.match(help_text.strip())
    return m.group(1) if m else None


def _to_tier(rt: Any) -> TierLabel:
    """Convert a Runtime enum value to TierLabel via duck-typed .value."""
    if rt is None:
        return TierLabel.UNKNOWN
    v = getattr(rt, "value", "").lower()
    return {
        "local": TierLabel.LOCAL,
        "hybrid": TierLabel.HYBRID,
        "cloud": TierLabel.CLOUD,
    }.get(v, TierLabel.UNKNOWN)


def build_tool_entries(
    commands: dict[str, str],
    tools_registry: dict[str, Any],
    arcpy_available: bool,
) -> list[ToolEntry]:
    """Build a sorted list of ToolEntry from Click command names + tier registry.

    Args:
        commands:        {cli_name: help_text} — top-level envmon subcommands.
                         Obtain via {n: (c.help or "") for n, c in group.commands.items()}.
        tools_registry:  The capabilities.TOOLS dict mapping name→Runtime enum value.
                         Commands absent from this dict get TierLabel.UNKNOWN.
        arcpy_available: True if arcpy is importable in the current environment.
                         LOCAL tools are unavailable when this is False.

    Returns:
        Sorted (by cli_name) list of ToolEntry.
    """
    entries: list[ToolEntry] = []
    for name in sorted(commands):
        help_text = commands[name] or ""
        first_line = help_text.splitlines()[0] if help_text else ""
        tier = _to_tier(tools_registry.get(name))

        if tier == TierLabel.LOCAL and not arcpy_available:
            available = False
            reason = (
                "arcpy not present — run in ArcGIS Pro or a cloned "
                "arcgispro-py3 environment"
            )
        else:
            available = True
            reason = None

        entries.append(ToolEntry(
            cli_name=name,
            tier=tier,
            roadmap_id=_extract_roadmap_id(first_line),
            description=first_line,
            available=available,
            unavailable_reason=reason,
        ))
    return entries


def detect_drift(
    command_names: list[str],
    tools_registry: dict[str, Any],
) -> list[str]:
    """Return CLI command names that are absent from capabilities.TOOLS.

    These commands have no declared tier:
    - Headless commands: silently degrade to UNKNOWN tier (safe but invisible).
    - Commands that call require_runtime(name): KeyError at runtime — a bug.

    See also: docs/superpowers/plans/2026-06-28-capabilities-registry-completeness.md
    """
    return [n for n in command_names if n not in tools_registry]


def format_tools_table(entries: list[ToolEntry]) -> str:
    """Render a fixed-width text table of ToolEntry rows."""
    if not entries:
        return "(no entries)"
    w_name = max(len(e.cli_name) for e in entries)
    w_name = max(w_name, 7)   # "command" header minimum
    w_tier = 7                 # len("UNKNOWN")
    w_id = 8                   # "roadmap" header
    header = (
        f"{'command':<{w_name}}  {'tier':<{w_tier}}  {'id':<{w_id}}  "
        f"{'avail':<5}  description"
    )
    sep = "-" * min(120, w_name + w_tier + w_id + 20 + 40)
    lines = [header, sep]
    for e in entries:
        avail = "yes" if e.available else "no"
        rid = e.roadmap_id or ""
        desc = (e.description or "")[:60]
        lines.append(
            f"{e.cli_name:<{w_name}}  {e.tier.value:<{w_tier}}  "
            f"{rid:<{w_id}}  {avail:<5}  {desc}"
        )
    return "\n".join(lines)


def format_tools_json(entries: list[ToolEntry]) -> list[dict]:
    """Render entries as a JSON-serializable list of dicts."""
    return [
        {
            "cli_name": e.cli_name,
            "tier": e.tier.value,
            "roadmap_id": e.roadmap_id,
            "description": e.description,
            "available": e.available,
            "unavailable_reason": e.unavailable_reason,
        }
        for e in entries
    ]
```

- [ ] **Step 4: Run unit tests**

```
python -m pytest tests/envmon/test_list_available_env_tools.py -v
```

Expected: all 30 tests PASS.

- [ ] **Step 5: Full suite regression check**

```
python -m pytest -q
```

Expected: all existing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add autogis/core/envmon/list_available_env_tools.py \
        tests/envmon/test_list_available_env_tools.py
git commit -m "feat(envmon): list_available_env_tools — ToolEntry + build/detect/format (arcpy-free)"
```

---

### Task 2: Register in capabilities.TOOLS

**Files:**
- Modify: `autogis/runtime/capabilities.py` — add one entry

**Interfaces:**
- Consumes: nothing new
- Produces: `TOOLS["list-tools"] == Runtime.CLOUD` — allows `requires_arcpy("list-tools")` to succeed without KeyError

- [ ] **Step 1: Write the failing test**

Add to `tests/envmon/test_list_available_env_tools.py`:

```python
def test_list_tools_registered_in_capabilities():
    from autogis.runtime.capabilities import TOOLS, Runtime
    assert "list-tools" in TOOLS, (
        "'list-tools' must be in capabilities.TOOLS. "
        "Add: \"list-tools\": Runtime.CLOUD,")
    assert TOOLS["list-tools"] is Runtime.CLOUD
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_list_available_env_tools.py::test_list_tools_registered_in_capabilities -v
```

Expected: FAIL with `AssertionError: 'list-tools' must be in capabilities.TOOLS`.

- [ ] **Step 3: Add the entry to `autogis/runtime/capabilities.py`**

Open `autogis/runtime/capabilities.py`. Locate the line:

```python
    "run-history": Runtime.CLOUD,  # tool 10.1b (query CLI)
```

Insert the new entry **immediately before** it:

```python
    "list-tools": Runtime.CLOUD,     # tool 10.1 (ListAvailableEnvTools)
    "run-history": Runtime.CLOUD,    # tool 10.1b (query CLI)
```

- [ ] **Step 4: Run the new test**

```
python -m pytest tests/envmon/test_list_available_env_tools.py::test_list_tools_registered_in_capabilities -v
```

Expected: PASS.

- [ ] **Step 5: Full suite regression check**

```
python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add autogis/runtime/capabilities.py \
        tests/envmon/test_list_available_env_tools.py
git commit -m "feat(capabilities): register list-tools as Runtime.CLOUD (tool 10.1)"
```

---

### Task 3: CLI command `envmon list-tools` + integration tests

**Files:**
- Modify: `autogis/adapters/cli.py` — add `@envmon.command("list-tools")`
- Modify: `tests/envmon/test_list_available_env_tools.py` — add CLI integration tests

**Interfaces:**
- Consumes (from Task 1): `build_tool_entries`, `detect_drift`, `format_tools_table`, `format_tools_json`, `TierLabel` from `autogis.core.envmon.list_available_env_tools`
- Consumes (from Task 2): `TOOLS` from `autogis.runtime.capabilities`
- Consumes: `_arcpy_present()` from `autogis.adapters.guard` (private but accessible within the same adapter layer)
- Produces: `autogis envmon list-tools [--format table|json] [--tier all|cloud|local|hybrid|unknown] [--available-only] [--check-drift]`

- [ ] **Step 1: Write the failing CLI tests**

Append to `tests/envmon/test_list_available_env_tools.py`:

```python
# ---------------------------------------------------------------------------
# CLI integration tests — use Click's CliRunner (no subprocess, no arcpy)
# ---------------------------------------------------------------------------
import json as _json
from click.testing import CliRunner
from autogis.adapters.cli import autogis


def test_list_tools_appears_in_envmon_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert result.exit_code == 0, result.output
    assert "list-tools" in result.output


def test_list_tools_table_has_header_columns():
    result = CliRunner().invoke(autogis, ["envmon", "list-tools"])
    assert result.exit_code == 0, result.output
    assert "command" in result.output
    assert "tier" in result.output
    assert "avail" in result.output


def test_list_tools_table_contains_stable_commands():
    """Stable anchors: inspect (CLOUD), import-gdb (LOCAL) — always in TOOLS."""
    result = CliRunner().invoke(autogis, ["envmon", "list-tools"])
    assert result.exit_code == 0, result.output
    assert "inspect" in result.output
    assert "import-gdb" in result.output
    assert "compare-events" in result.output


def test_list_tools_json_valid_structure():
    result = CliRunner().invoke(autogis, ["envmon", "list-tools", "--format", "json"])
    assert result.exit_code == 0, result.output
    data = _json.loads(result.output)
    assert isinstance(data, list)
    assert len(data) > 10  # many commands exist
    for row in data:
        for key in ("cli_name", "tier", "roadmap_id", "description",
                    "available", "unavailable_reason"):
            assert key in row, f"Missing key '{key}' in entry {row['cli_name']!r}"


def test_list_tools_json_roadmap_ids_from_real_docstrings():
    """End-to-end: cmd.help → splitlines()[0] → regex → roadmap_id field.

    'compare-events' docstring starts with 'Tool 4.7: ...'
    'process-level-loop' docstring starts with 'Tool 8.1: ...'
    Both should have populated roadmap_id values.
    """
    result = CliRunner().invoke(autogis, ["envmon", "list-tools", "--format", "json"])
    assert result.exit_code == 0, result.output
    data = _json.loads(result.output)
    by_name = {row["cli_name"]: row for row in data}

    assert "compare-events" in by_name, "compare-events not found in list-tools output"
    assert by_name["compare-events"]["roadmap_id"] == "4.7", (
        f"Expected roadmap_id '4.7' for compare-events, "
        f"got {by_name['compare-events']['roadmap_id']!r}"
    )

    assert "process-level-loop" in by_name, "process-level-loop not found"
    assert by_name["process-level-loop"]["roadmap_id"] == "8.1", (
        f"Expected roadmap_id '8.1' for process-level-loop, "
        f"got {by_name['process-level-loop']['roadmap_id']!r}"
    )


def test_list_tools_tier_filter_cloud_only():
    result = CliRunner().invoke(
        autogis, ["envmon", "list-tools", "--tier", "cloud"])
    assert result.exit_code == 0, result.output
    # LOCAL commands must be absent
    assert "import-gdb" not in result.output
    assert "build-event" not in result.output
    # A known CLOUD command must be present
    assert "inspect" in result.output


def test_list_tools_tier_filter_local_only():
    result = CliRunner().invoke(
        autogis, ["envmon", "list-tools", "--tier", "local"])
    assert result.exit_code == 0, result.output
    assert "import-gdb" in result.output
    # Headless commands must be absent
    assert "inspect" not in result.output


def test_list_tools_available_only_excludes_local_in_headless_env():
    """In CI (no arcpy), LOCAL commands are unavailable and must be filtered out."""
    result = CliRunner().invoke(
        autogis, ["envmon", "list-tools", "--available-only"])
    assert result.exit_code == 0, result.output
    # Stable LOCAL commands (always in TOOLS) must be absent
    assert "import-gdb" not in result.output
    assert "build-event" not in result.output
    # Stable CLOUD commands must still appear
    assert "inspect" in result.output


def test_list_tools_check_drift_outputs_status_line():
    """--check-drift must end with either [OK] or one or more [DRIFT] lines."""
    result = CliRunner().invoke(
        autogis, ["envmon", "list-tools", "--check-drift"])
    assert result.exit_code == 0, result.output
    assert "[OK]" in result.output or "[DRIFT]" in result.output


def test_list_tools_json_tier_filter_local_all_local():
    result = CliRunner().invoke(
        autogis,
        ["envmon", "list-tools", "--format", "json", "--tier", "local"])
    assert result.exit_code == 0, result.output
    data = _json.loads(result.output)
    assert len(data) > 0, "Expected at least one LOCAL command"
    assert all(row["tier"] == "LOCAL" for row in data), (
        "Non-LOCAL entry appeared with --tier local"
    )
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_list_available_env_tools.py -k "list_tools_appears_in_envmon_help" -v
```

Expected: FAIL — `"list-tools" not in result.output` (command not yet registered).

- [ ] **Step 3: Add the `list-tools` command to `autogis/adapters/cli.py`**

Insert the block below immediately after the `_render_qa` function definition (around line 925) and **before** the `# LOCAL tools (2-8)` comment block. Position it here so it appears early in `envmon --help` output.

```python
@envmon.command("list-tools")
@click.option(
    "--format", "fmt",
    type=click.Choice(["table", "json"]),
    default="table",
    show_default=True,
    help="Output format.",
)
@click.option(
    "--tier",
    type=click.Choice(["all", "cloud", "local", "hybrid", "unknown"]),
    default="all",
    show_default=True,
    help="Filter by runtime tier.",
)
@click.option(
    "--available-only",
    is_flag=True,
    default=False,
    help="Show only commands available in the current runtime.",
)
@click.option(
    "--check-drift",
    is_flag=True,
    default=False,
    help=(
        "Warn about CLI commands not in capabilities.TOOLS. "
        "Commands calling require_runtime() without a TOOLS entry will "
        "raise KeyError at runtime."
    ),
)
def list_tools_cmd(fmt, tier, available_only, check_drift):
    """Tool 10.1: enumerate registered envmon commands with tier and availability."""
    import json as _json
    from autogis.runtime.capabilities import TOOLS
    from autogis.core.envmon.list_available_env_tools import (
        TierLabel,
        build_tool_entries,
        detect_drift,
        format_tools_table,
        format_tools_json,
    )
    from autogis.adapters.guard import _arcpy_present

    # Walk the envmon Click group — top-level only (no recursion into sub-groups).
    # Sub-group commands (e.g. manage-callout-overrides list/clear/lock/unlock)
    # are represented by their parent group entry, matching the TOOLS dict structure.
    commands: dict[str, str] = {
        name: (cmd.help or "")
        for name, cmd in envmon.commands.items()
    }

    entries = build_tool_entries(commands, TOOLS, arcpy_available=_arcpy_present())

    # Apply filters
    if tier != "all":
        tier_label = TierLabel(tier.upper())
        entries = [e for e in entries if e.tier == tier_label]
    if available_only:
        entries = [e for e in entries if e.available]

    # Render
    if fmt == "json":
        click.echo(_json.dumps(format_tools_json(entries), indent=2))
    else:
        click.echo(format_tools_table(entries))

    # Drift check — report after the main output
    if check_drift:
        all_names = list(envmon.commands.keys())
        drifted = detect_drift(all_names, TOOLS)
        if drifted:
            for d in sorted(drifted):
                click.echo(
                    f"[DRIFT] '{d}' is registered in the CLI but absent from "
                    f"capabilities.TOOLS. Tier is UNKNOWN; calls to "
                    f"require_runtime('{d}') will raise KeyError at runtime."
                )
            click.echo(
                f"Fix: add missing entries to autogis/runtime/capabilities.py "
                f"(see docs/superpowers/plans/"
                f"2026-06-28-capabilities-registry-completeness.md)"
            )
        else:
            click.echo("[OK] No registry drift detected.")
```

- [ ] **Step 4: Run all tests in the file**

```
python -m pytest tests/envmon/test_list_available_env_tools.py -v
```

Expected: all tests PASS.

Note on `test_list_tools_check_drift_outputs_status_line`: if the
`capabilities-registry-completeness` plan has already landed, the output will
contain `[OK]`. If it has not landed, it will contain multiple `[DRIFT]` lines.
The test accepts both outcomes.

Note on `test_list_tools_json_roadmap_ids_from_real_docstrings`: this exercises
the full chain `cmd.help → splitlines()[0] → _extract_roadmap_id()`. If it fails,
check that `compare-events` and `process-level-loop` command docstrings still start
with `"Tool 4.7: ..."` and `"Tool 8.1: ..."` respectively.

- [ ] **Step 5: Full suite regression check**

```
python -m pytest -q
```

Expected: all tests pass. The total test count increases by the number of new tests added.

- [ ] **Step 6: Final commit**

```bash
git add autogis/adapters/cli.py \
        tests/envmon/test_list_available_env_tools.py
git commit -m "feat(cli): add envmon list-tools command (ListAvailableEnvTools 10.1)"
```

---

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| **Registry drift** — CLI commands added without a TOOLS entry show as `UNKNOWN` tier; commands that also call `require_runtime()` raise `KeyError` at runtime | Medium | `--check-drift` exposes the gap immediately; companion plan `capabilities-registry-completeness` fills known gaps (run it in parallel or before) |
| **cmd.help returns None** for a newly-added Click command | Low | `build_tool_entries` coerces to `""` before any splitlines call; UNKNOWN tier appears cleanly |
| **Sub-group commands missed** (`manage-callout-overrides list/clear/lock/unlock`) | Low by design | Top-level iteration matches the flat TOOLS dict; sub-commands inherit the group's tier. Document this scope explicitly in the command `--help` if users ask |
| **import-edd calls `_guard("LOCAL")` (wrong argument)** — KeyError at runtime | Low (existing bug, not introduced here) | `--check-drift` does NOT catch this variant (import-edd IS in TOOLS; it's the argument that's wrong). This bug is tracked in MEMORY.md; fix it in a dedicated PR |
| **`compare-events` or `process-level-loop` docstrings edited** — breaks `roadmap_id` extraction | Low | `test_list_tools_json_roadmap_ids_from_real_docstrings` catches it; update the docstring pattern to match `_ROADMAP_RE` if changed |
| **Ordering dependency on `capabilities-registry-completeness` plan** | Low | Plans are independent; the only behavioral difference is whether `--check-drift` shows `[OK]` or `[DRIFT]`. Tests accept both |
