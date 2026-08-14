# ListAvailableEnvTools Design

**Date:** 2026-06-28
**Status:** Approved
**Tool:** ListAvailableEnvTools (Phase 5 / Tool 10.1)
**Priority:** MEDIUM — discoverability; reduces "what commands exist?" friction

> **Amended by #468 / PR #475:** `DRAFT` is no longer a `runtime` value — runtime
> holds only a real runtime class (`CLOUD | HYBRID | LOCAL`, see
> `RUNTIME_CLASSES`); draft-ness lives in `status` alone. Mentions of a `DRAFT`
> runtime below are the original design, kept as history.

---

## Problem

With 30+ CLI commands registered under `autogis envmon`, analysts cannot easily
discover which tools are available, which require ArcGIS Pro (LOCAL), which are
headless (CLOUD), or which are pre-production stubs (DRAFT). `--help` shows all
commands in a flat alphabetical list with one-line descriptions — no runtime
filtering, no capability metadata, no readiness status.

---

## Approach

**Chosen:** Tool registry embedded in `autogis/runtime/capabilities.py` (already
used for runtime guards). Extend `ToolCapability` entries with:
- `runtime`: CLOUD | LOCAL | DRAFT
- `roadmap_id`: e.g. `"2.3"`, `"4.1"`
- `status`: `stable | draft | planned`
- `domain`: `intake | qa | analysis | cartography | field | agol | reporting | admin`

`list-tools` command queries the registry and renders a filtered, formatted table.
No arcpy; purely registry metadata.

**Rejected: Click introspection only.** Click's `--help` output doesn't carry
metadata. A separate registry that Click commands register against is necessary.

**Rejected: Separate YAML manifest.** The registry is already in
`capabilities.py`. Adding a second source of truth creates drift. Extend the
existing pattern.

---

## Architecture

```
autogis/
  runtime/
    capabilities.py           ← MODIFY: add metadata fields to ToolCapability
  core/envmon/
    tool_registry.py          ← NEW: query/filter/format registry
  adapters/
    cli.py                    ← add list-tools command (headless)
tests/
  test_tool_registry.py       ← NEW
```

---

## Public API (`tool_registry.py`)

```python
@dataclass
class ToolEntry:
    command: str           # e.g. "import-edd"
    name: str              # e.g. "ImportLabEDD"
    roadmap_id: str        # e.g. "2.3"
    runtime: str           # CLOUD | LOCAL | DRAFT
    status: str            # stable | draft | planned
    domain: str            # intake | qa | analysis | ...
    description: str       # one-line description
    plan_path: str         # relative path to implementation plan doc

def get_all_tools() -> list[ToolEntry]:
    """Return all registered tool entries from capabilities.py."""

def filter_tools(
    entries: list[ToolEntry],
    *,
    runtime: str | None = None,        # CLOUD | LOCAL | DRAFT
    domain: str | None = None,
    status: str | None = None,
    search: str | None = None,         # substring match on name/description
) -> list[ToolEntry]:
    """Filter tool entries by any combination of criteria."""

def format_tool_table(entries: list[ToolEntry], *, verbose: bool = False) -> str:
    """
    Render as text table.
    Compact: command | runtime | domain | description
    Verbose: + roadmap_id | status | plan_path
    """
```

---

## Registry Extension (`capabilities.py`)

Existing `ToolCapability` entries gain optional fields:

```python
@dataclass
class ToolCapability:
    name: str
    runtime: str = "CLOUD"   # already exists
    # NEW:
    roadmap_id: str = ""
    status: str = "stable"    # stable | draft | planned
    domain: str = ""
    description: str = ""
    plan_path: str = ""
```

Backwards-compatible — existing entries without new fields default to `""`.

---

## CLI Command

```
autogis envmon list-tools \
  [--runtime CLOUD|HYBRID|LOCAL] \
  [--domain intake|qa|analysis|cartography|field|agol|reporting|admin] \
  [--status stable|draft|planned] \
  [--search <keyword>] \
  [--verbose]
```

Headless. Example output:

```
command                     runtime  domain    description
──────────────────────────  ───────  ────────  ─────────────────────────────
import-edd                  CLOUD    intake    Import lab EDD CSV/XLSX
reconcile-locations         CLOUD    qa        Reconcile sample location IDs
build-callouts              LOCAL    cartog.   Build analytical callout boxes
gw-contours                 LOCAL    analysis  Generate GW contour features
```

---

## Test Strategy

`tests/test_tool_registry.py` — arcpy-free:

1. `get_all_tools()` returns non-empty list
2. All entries have non-empty `command` and `runtime` fields
3. `filter_tools(runtime="CLOUD")` returns only CLOUD entries
4. `filter_tools(domain="intake")` returns only intake entries
5. `filter_tools(search="edd")` returns entries matching "edd" in name/description
6. `format_tool_table` produces a string with header row and data rows
7. `verbose=True` includes roadmap_id column
8. `filter_tools` with no criteria returns all entries
