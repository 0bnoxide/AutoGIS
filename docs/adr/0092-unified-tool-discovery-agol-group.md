# ADR-0092: Unified tool discovery — `agol` group joins the `list-tools` registry

**Status:** Accepted

**Date:** 2026-07-19

## Context

The `envmon list-tools` discovery registry (`capabilities._REGISTRY_SEED`,
Tool 10.1) covered only `envmon` subcommands. The 9 commands of the top-level
`agol` group (tools 6.1–6.11) were invisible to discovery, and the drift-guard
test `test_registry_commands_exist_in_live_cli` recorded that scoping as
deliberate ("top-level/agol/sub-group commands are intentionally out of the
registry"). PR #265's gap survey flagged the question — envmon-scoped
discovery vs unified — and the user decided: unify.

## Decision

- All `agol` group commands are registered in `_REGISTRY_SEED` with
  **group-qualified command strings** (`"agol publish-layer"`, …), domain
  `agol`, matching what the user actually types (`autogis agol …` vs bare
  envmon names for `autogis envmon …`).
- `agol sync-to-gdb` displays `LOCAL` (its `--gdb` upsert path is arcpy-
  guarded, matching `capabilities.TOOLS`); the other 8 display `CLOUD`
  (arcgis-API-only, headless).
- Drift guards are bidirectional for both groups: seed entries must resolve
  to a live click command (`test_no_ghost_seed_entries`,
  `test_registry_commands_exist_in_live_cli`), and every envmon **and** agol
  command must be registered (`test_every_envmon_command_registered_for_discovery`,
  `test_every_agol_command_registered_for_discovery` — the #98/#106
  "forgot the discovery registry" bug class).
- The TOOLS↔seed runtime parity check maps a group-qualified seed command to
  its bare `TOOLS` key (last token), so agol entries stay covered.

## Consequences

### Positive consequences

- `envmon list-tools` is the one discovery surface for the whole CLI tool
  catalog; the agol batch can no longer silently drift out of it.
- A future agol command missing its registry entry is a red test, not a
  memory obligation.

### Negative consequences

- Discovery for `agol` commands lives under the `envmon` group's
  `list-tools` command — mildly asymmetric, but not worth a second command
  or a CLI move that breaks scripts.

## Alternatives considered

- **Keep the registry envmon-scoped** (status quo): `agol --help` covers its
  own 9 commands, but leaves two discovery surfaces and a standing survey
  finding; rejected by user decision on 2026-07-19.
- **Bare command names for agol entries**: collides with future envmon names
  and lies about what the user types; group-qualified strings follow the
  existing `UNREACHABLE` label precedent (`"envmon <name>"`).

## Related decisions

- [ADR-0069: Tool-registry single-source consolidation](0069-tool-registry-single-source-consolidation.md)
- [PR #265](https://github.com/0bnoxide/AutoGIS/pull/265) — gap survey that surfaced the question
