# ADR-0029 — The validate_*/manage_* modules are intentionally thin adapters

**Status:** Accepted
**Date:** 2026-06-29
**Deciders:** Greg / Claude Code
**Related:** ADR-0001 (core/adapters separation), ADR-0005 (thread-safe QA substrate),
ADR-0009 (config dataclass style)

---

## Context

An architecture-deepening review (graph-codebase-navigator cluster #10/#15,
cohesion ~0.54) flagged a recurring shape across `validate_units.py`,
`validate_config.py`, `manage_analyte_dict.py`, and `evaluate_readiness.py`:
each does roughly *load config → run a validator → wrap results in a
`QACollector` → add an INFO summary*. The recurring shape invites a suggestion
to fuse the four into a single `validate_config_bundle(mode=...)` orchestrator.

We ran the deletion test on each module honestly:

- **`config_validation.py`** (`core/common`) is the deep module: ~10 pure,
  arcpy-free validators (`validate_site`, `validate_parser_profile`,
  `validate_screening_levels`, `validate_analyte_dictionary`, …) that take
  already-loaded dicts and return `List[QARecord]`. It explicitly owns *no* file
  I/O. This is where the real validation leverage lives.
- **`validate_config.py`** is a genuine orchestrator: it loads a five-part config
  bundle (site, parser profiles, figure specs, analyte dictionary, screening
  levels), runs every validator, and reports. Not a pass-through.
- **`validate_units.py`** is a thin adapter: load two configs defensively, call
  `cv.validate_units`, summarize.
- **`manage_analyte_dict.py`** has its own logic (`_clean` strips `_`-prefixed
  keys; `list_analytes` formats a table) — not a pass-through.
- **`evaluate_readiness.py`** is independently deep and does **not** fit the
  config-load shape at all: it reads run history, scans a QA CSV, and validates a
  figure spec.

## Decision

**Do not fuse these modules.** They are intentionally thin, single-purpose
adapters that compose `core/common/config_validation` validators with file
loading and a per-tool QA summary, one adapter per CLI command. The validation
*leverage* already lives in one deep module (`config_validation`); the adapters
are the seam between that module and each `envmon <command>`.

Fusing them into a `mode`-switched orchestrator would create a **shallow
multiplexer**: the `mode` parameter would leak each tool's shape through one
interface, `evaluate_readiness` does not even share the config-load shape, and
the result would be harder to test and reason about than four focused adapters.
Per the deletion test, deleting any adapter *scatters* its small load+summarize
ritual back to its CLI command — it does not concentrate hidden complexity.

### One concrete cleanup (done)

The only real friction was a leaky seam: `validate_units` imported the
**private** `validate_config._safe` defensive-load helper across a module
boundary. `_safe` was promoted to a public `validate_config.safe_load` (it stays
at the orchestrator layer, since `config_validation` is deliberately I/O-free),
and both adapters now call the public name. No behavior change.

## Consequences

### Positive
- Future architecture reviews have a recorded reason not to re-suggest fusing the
  validation adapters.
- The pure/​I/O split is explicit: validators in `config_validation` (no I/O),
  defensive loading in `validate_config.safe_load` (orchestrator layer).

### Negative
- The recurring load→validate→summarize shape remains visible across the
  adapters. This is accepted as the cost of keeping each adapter focused and
  independently testable, rather than hidden behind a `mode` switch.

## Alternatives considered
- **`validate_config_bundle(mode=...)` god-orchestrator:** rejected — shallow
  multiplexer; `evaluate_readiness` doesn't fit; worse testability.
- **Move `safe_load` into `config_validation`:** rejected — that module is
  deliberately pure/no-I/O (its docstring: "the orchestrator owns file I/O").

## Related decisions
- [ADR-0001: core/adapters separation](0001-core-adapters-separation.md)
- [ADR-0005: thread-safe QA substrate](0005-thread-safe-qa-substrate.md)
