# AutoGIS — Claude Code session guide

## Codebase memory (optional, local-only)

The codebase-memory MCP server is **no longer wired into the repo** (web sessions
ran it as an untrusted project `.mcp.json` server, so its tools never registered —
see `docs/codebase-memory-mcp.md` for the full diagnosis and the local-install
steps). Use **Grep / Glob / Read / the Explore subagent** as the default way to
answer structural questions (where is X defined, what calls X, what imports Z,
layer overviews).

If you have installed the server **locally** at user scope, its
`mcp__codebase-memory-mcp__*` tools (`search_graph`, `trace_path`,
`get_architecture`, `search_code`, …) and the `/graph` skill are available as a
faster first pass — but they are an aid, not a requirement, and won't exist in
web/cloud sessions. Always fall back to manual search when they're absent.

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
