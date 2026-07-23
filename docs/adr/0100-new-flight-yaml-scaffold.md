# ADR-0100: `new-flight-yaml` — drone flight inventory scaffold

**Status:** Accepted — user request (this session)

**Date:** 2026-07-22

## Context

`register-drone-flight` (tool 8.6, ADR nearby) *reads* a drone flight inventory
YAML but there was **no generator** for it — no template, example, or scaffold
anywhere in the repo. A one-off had to hand-author all 20 keys from memory or by
reading `load_flight_yaml`'s source. The flight record is a **required** input
to the drone-products pipeline (`register-drone-flight` → `import-drone-products`
→ registry), so the missing scaffold was a recurring blocker for one-off flights.

This mirrors the existing `draft-parser-profile` (2.1) / `draft-edd-profile`
(2.3a) scaffold pattern (inspect/emit a draft YAML the user then edits).

## Decision

Add a headless tool `envmon new-flight-yaml` that writes a ready-to-edit flight
inventory YAML.

- **Core** (`register_drone_flight.py`, the module that owns `DroneFlight` +
  `load_flight_yaml`): `flight_yaml_template(overrides=None) -> dict`. Keys mirror
  `DroneFlight` exactly (a `test_flight_yaml_template` drift guard pins the set),
  **required-first** (`flight_id, site_id, flight_date, pilot, drone_model,
  sensor`) so the must-fill fields head the file. Required fields default
  **empty** — an empty value round-trips into a clean
  `register-drone-flight --dry-run` "missing_required_field" report (and an empty
  `flight_date` coerces to `date.min`, a clean missing rather than a parse crash),
  so the existing validator *is* the "which fields are required" guide. Optional
  fields carry sensible blanks/defaults. `overrides` pre-fill any field.
- **CLI**: `new-flight-yaml --output PATH [--set KEY=VALUE]...`. `--set` is one
  flexible knob covering all 20 fields (validated against the template key set;
  unknown key or missing `=` → `UsageError`), rather than 20 named options. Values
  arrive as strings — `load_flight_yaml`'s existing coercers (`_opt_float`,
  `_as_bool`, `_as_int`, `_coerce_date`) handle typing, so the scaffold stays
  type-agnostic. Emits via `yaml.dump(sort_keys=False)` (the `draft-parser-profile`
  convention) and echoes the required-field list + the exact `--dry-run` command.
- **Discovery**: one `_REGISTRY_SEED` entry (`8.6a`, CLOUD/headless), required for
  `envmon list-tools` parity. Being headless, it also appears automatically in the
  GUI command picker (no `.pyt` tool needed).

## Consequences

- A one-off flight is now `new-flight-yaml → fill required → --dry-run →
  register`, self-guided by the validator; no more hand-authoring from source.
- No inline YAML comments (a `yaml.dump` limitation, same as the sibling
  scaffolds); required-vs-optional is conveyed by required-first ordering, the
  echoed field list, and the `--dry-run` report rather than file comments.
- `--set` values are strings; the loaders coerce them. A future typed/interactive
  builder is deferred (YAGNI) — the scaffold + validator loop covers 1-offs.
- Fully headless: arcpy-free invariant and `test_boundary_imports` hold.

## Alternatives considered

- **Commented YAML string template** (required fields marked `# REQUIRED`):
  rejected — a hand-maintained string drifts from `DroneFlight`, and the
  required-first ordering + `--dry-run` validator already convey the same, reusing
  existing code.
- **20 named `--flight-id/--site-id/...` options:** rejected — one `--set
  KEY=VALUE` covers every field (incl. optional) with less surface.
- **A new `.pyt` toolbox tool:** unnecessary — headless commands surface in the
  GUI picker for free via introspection.

## Related decisions

- ADR-0006 — .pyt toolbox as primary UI for LOCAL tools (this is headless, so CLI/
  GUI, no redirect)
- ADR-0052 — GUI introspection (headless leaf auto-appears in the picker)
