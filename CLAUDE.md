# AutoGIS — Claude Code session guide

## Codebase memory: check the graph first

This repo is indexed in the codebase-memory MCP server. **Before doing any manual
exploration (Glob, Grep, Explore subagent, file reads) to answer a structural
question about the codebase, check the indexed graph first.**

Structural questions include:
- Where is X defined / what calls X?
- What files are affected if I change Y?
- What modules import Z?
- Give me an overview of how the harvest / envmon / adapter layers fit together.

Workflow:
1. Use `mcp__codebase-memory-mcp__search_graph` or `mcp__codebase-memory-mcp__search_code`
   for the answer.
2. Use `mcp__codebase-memory-mcp__trace_path` for call-chain / dependency questions.
3. Use `mcp__codebase-memory-mcp__get_architecture` for layer/module overviews.
4. Fall back to Grep / Read only for things the graph can't answer (raw file content,
   line-level context, uncommitted changes).

If the graph returns stale or missing results, run
`mcp__codebase-memory-mcp__detect_changes` then `mcp__codebase-memory-mcp__index_repository`
to refresh before falling back to manual search.

Invoke `/graph` at any point for a guided graph-query workflow.

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
| `tests/` | 126 arcpy-free tests; run with `python -m pytest -q` |

## Key invariants

- `core/` and `adapters/` import with neither `arcpy` nor `arcgis` present.
- Tools 1, 9, 10 are headless (openpyxl only). Tools 2-8 are LOCAL (arcpy) — CLI
  commands for 2-8 guard then redirect to the `.pyt` toolbox.
- `HarvestConfig` is canonical in `core/common/config.py`; re-exported from
  `core/harvest/models.py` for back-compat.
- Screening levels and the H281 parser profile are pre-production stubs — do not
  remove DRAFT banners or `_TODO` markers until verified against real data.
