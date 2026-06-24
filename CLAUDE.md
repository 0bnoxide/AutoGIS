# AutoGIS — Claude Code session guide

## Codebase memory

The codebase-memory MCP server is **installed at user scope and running locally**.
The `.mcp.json` in the repo root wires it in as a trusted project server.
Its tools are available in every local session — use them as a fast first pass
before falling back to manual search.

**At the start of every session:**
1. Call `mcp__codebase-memory-mcp__index_status` (project `C-Users-ichbi-AutoGIS`).
2. If `status` is not `"ready"` or `nodes` looks stale (e.g. missing recent files),
   run `mcp__codebase-memory-mcp__detect_changes` then
   `mcp__codebase-memory-mcp__index_repository` before querying.

Use the `/graph` skill to query the index. Key tools:

| Question type | Tool |
|---|---|
| Find a symbol / module / concept | `search_graph` |
| Find code by keyword or pattern | `search_code` |
| How does A call / depend on B? | `trace_path` |
| Layer / module overview | `get_architecture` |
| Fetch a specific snippet | `get_code_snippet` |

Fall back to Grep / Glob / Read / the Explore subagent when tools are absent
(web/cloud sessions) or when the index hasn't caught a very recent change.

---

## Project layout (quick reference)

| Path | Purpose |
|------|---------|
| `autogis/core/harvest/` | Attachment harvester — arcpy-free |
| `autogis/core/envmon/` | Environmental monitoring tools (23 modules) |
| `autogis/core/common/` | Shared config, QA, logging, seen-index |
| `autogis/adapters/` | CLI (`cli.py`), `.pyt` toolbox, toolbox_core seam |
| `autogis/runtime/` | ArcGIS Pro session providers + capability guard |
| `autogis/config/` | Site configs, parser profiles, screening levels, figure specs |
| `tests/` | 132 arcpy-free tests; run with `python -m pytest -q` |

## Key invariants

- `core/` and `adapters/` import with neither `arcpy` nor `arcgis` present.
- Tools 1, 9, 10 are headless (openpyxl only). Tools 2-8 are LOCAL (arcpy) — CLI
  commands for 2-8 guard then redirect to the `.pyt` toolbox.
- `HarvestConfig` is canonical in `core/common/config.py`; re-exported from
  `core/harvest/models.py` for back-compat.
- Screening levels and the H281 parser profile are pre-production stubs — do not
  remove DRAFT banners or `_TODO` markers until verified against real data.
