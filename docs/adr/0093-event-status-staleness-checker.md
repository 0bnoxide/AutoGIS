# ADR-0093: Event status & staleness checker (roadmap Phase 2)

**Status:** Accepted — owner sign-off for roadmap Phase 2

**Date:** 2026-07-20

## Context

The production roadmap (ADR-0087, `docs/production-roadmap.md`) Phase 2 asks for
`envmon event-status`: a headless command that compares source hashes,
configuration, run history, snapshots, approvals, and package manifests, and
reports each expected artifact of a monitoring event as **current, stale,
missing, failed, or awaiting-review** — naming the upstream change that caused
the state — with stable exit codes for automation. It must not modify
production data.

**Production gate:** changes to an input workbook, site configuration, screening
levels, figure specification, and approved model each invalidate *only* the
correct downstream artifacts without modifying production data.

The material already exists but no checker does. Two append-only ledgers carry
almost everything needed, arcpy-free:

- **`RunHistory`** (`run_history.csv`): one `RunRecord` per tool run —
  `tool_name`, `site_id`, `event_id`, `finished_at`, `status`
  (`success|warning|error|cancelled`). It answers *did the producer run, and
  how did it end* — but its `inputs` are CLI param **paths**, `outputs` is
  always `{}`, so it cannot on its own tell whether an output is **stale**
  relative to its inputs.
- **`SourceRegistry`** (`source_docs.csv`): append-only rows
  `registered_at, file_path, sha256, file_size_bytes, site_id, event_id, tool,
  notes`. The one place an input's SHA-256 is persisted, already event-scoped.

`compute_sha256`, `evaluate_readiness` (coarse per-tool success gate — the
nearest prior art, reused as a pattern), `read_tracker_csv`
(`ReviewerComment.status` — the only arcpy-free "awaiting review" signal), and
the CLI's `_render_qa`/registry/recording seams round out the reuse surface.

The gaps that are the actual work: (G1) no dependency map linking each artifact
to its inputs; (G2) no per-artifact record of the input hashes it was built
from; (G3) no config-file hash baseline; (G4) approved-model state lives only in
the arcpy GDB (`GW_ModelRun.ReviewStatus`); (G5) no five-state vocabulary or
multi-value exit codes; (G6) a nonzero exit self-logs the read-only run as
`error`.

## Decision

### Architecture

- **Core:** one new arcpy-free module `autogis/core/envmon/event_status.py` —
  the `ArtifactState` vocabulary, a hardcoded `DEPENDENCY_GRAPH`, the
  classifier, exit-code mapping, JSON/table rendering, and `accept_baseline`.
  It receives plain values, a `RunHistory`, a `SourceRegistry`, and reviewer
  comments; it never imports arcpy/arcgis or an adapter. `datetime` parsing
  only (no module-level `datetime`/`math`/`numpy`/`time` names).
- **CLI adapter:** leaf `envmon event-status` in `cli.py`. No `_guard` (headless,
  `Runtime.CLOUD`). One `_REGISTRY_SEED` entry (parity tests require it); **not**
  in `TOOLS` (only guarded LOCAL tools are).

### Baseline acquisition — reuse `SourceRegistry`, no new store (G2/G3)

`SourceRegistry.register` is generic. `event-status --accept` hashes each
declared input and registers it with `tool="event-status"`, `notes=<input-kind>`
(`workbook`/`site-config`/`screening`/`figure-spec`). Zero schema change, zero
new store, one already-accepted write path. The baseline for a kind is the
**latest** registry row (append-only) with matching `(site_id, event_id, notes)`
— **matched on kind, not path** (Windows case / abs-rel drift makes path
equality fragile).

### Freshness rule — two ledgers, per artifact (the correctness core)

An artifact is **current** iff its producer's latest run for `(tool, site,
event)` ended `success`/`warning` **and** every declared file input's current
`compute_sha256` equals its latest baseline hash **and** that baseline was not
registered at/after the build **and** no upstream artifact was rebuilt at/after
this build or is itself not-current. Otherwise:

- producer never ran → **missing**; last run `error` → **failed**; last run
  `cancelled` → **missing** (not a build).
- input hash ≠ baseline → **stale**, cause "`<kind>` changed since baseline".
- input hash = baseline but baseline registered at/after the build → **stale**,
  cause "rebuild pending after re-baseline of `<kind>`". *This is what makes a
  partial rebuild classify correctly:* change → stale(drift) → `--accept` →
  stale(rebuild-pending) → rebuild in order → current, each transition naming
  its cause. A pure hash-vs-accepted comparison cannot express it.
- upstream rebuilt at/after this build, or upstream not-current → **stale**
  (transitive), naming the upstream. Staleness propagates down the DAG, so a
  changed workbook (import stale) carries every downstream artifact to stale.

Timestamps are parsed to `datetime` (never string-compared); a same-second tie
classifies **stale** (safe direction: stale-when-fresh over fresh-when-stale).

### Dependency graph — hardcoded, tested as a matrix (G1)

A frozen tuple of `ArtifactSpec(kind, producer, file_inputs, upstream, review)`
in the core module — one site exists today, so per-site YAML is dead
flexibility (promote when a second site needs a different shape). Slice-1 graph
(five artifacts spanning all five gate inputs and all five states):

| artifact | producer (`tool_name`) | file inputs | upstream | review |
|---|---|---|---|---|
| canonical-import | `import-edd` | workbook, site-config | — | — |
| snapshot | `export-snapshot` | — | canonical-import | — |
| screening-evaluation | `apply-screening` | screening | canonical-import | — |
| figures | `export-figures` | figure-spec | canonical-import | reviewer-tracker |
| groundwater-surface | `run-gw-model-pipeline` | — | canonical-import | approved-model |

The gate's "**only** the correct downstream" clause is a property of the *non*-
edges, so the test asserts the full state vector across all artifacts for each
changed input — including the artifacts that must stay `current` (screening must
not touch figures; figure-spec must not touch screening-evaluation).

### Approvals / awaiting-review — arcpy-free inference (G4)

Reading `GW_ModelRun` is forbidden by the arcpy-free invariant, so slice 1 infers:

- **figures:** any `OPEN`/`IN_REVIEW` reviewer-tracker comment ⇒
  awaiting-review.
- **groundwater-surface:** latest `run-gw-model-pipeline` for `(site, event)`
  with no later successful `approve-gw-model` ⇒ awaiting-review.

Awaiting-review is an overlay on an otherwise-current artifact; staleness/failure
outrank it (precedence below). Documented ceilings: **revocation is invisible**
(an approval flipped back to DRAFT in the GDB after `approve-gw-model` logged
success still reads approved — the GDB is truth, RunHistory a proxy); the
**ledger is the horizon** (runs recorded to a different `run_history.csv` are
invisible — hence explicit `--run-history`/`--source-registry` paths defaulting
to the producers' defaults).

### Exit codes — semantic, always (G5/G6)

`0` all-current, `1` internal error, `2` usage (Click-native), `3` stale, `4`
missing, `5` failed, `6` awaiting-review. The report's exit code is the code of
the **worst** state by **precedence** `failed > missing > stale >
awaiting-review > current` (a failed build outranks a pending review) — not
numeric `max`. Semantic exits are the default (the requirement is literally
"stable exit codes for automation"; `grep`-style default-nonzero is the
contract scripts want), so no dual-mode flag.

To keep the ledger truthful under nonzero semantic exits, `event-status` joins
`_SELF_LOGGING_COMMANDS` (the cli.py comment invited the second member) and
writes its **own** `RunRecord`: `status="success"` whenever classification
completed (finding stale artifacts is not a failure), `outputs={state: count}`.
Genuine crashes exit `1` and self-log `error`.

### Read-only definition

Production data = workbooks, configs, the GDB, and generated artifacts.
Observability/audit ledgers (`run_history.csv`, `source_docs.csv`) are
explicitly **not** production data — importers and `register-source-doc` already
append to the registry, and every command appends run history. Default
`event-status` appends only its own run record; `--accept` appends registry
rows. It never touches production data.

### Report

`--format table` (default, human) or `json` (machine, schema 1:
`{schema, site_id, event_id, artifacts:[{kind, state, producer, causes[]}],
summary:{state:count}}`), to stdout — modeled on the `run-history` command's
read-only emitter. No file output / `--out DIR` in slice 1 (add when a consumer
needs it).

### Deferred (not licensed by this ADR)

- Reading `GW_ModelRun.ReviewStatus`/`ApprovedModel` via an arcpy-gated seam or
  a headless approval export (removes the revocation ceiling).
- Letting an importer's own registration serve as the workbook baseline
  (so re-import needs no re-`--accept`); slice 1 baselines all inputs uniformly
  via `--accept`.
- Multi-event / portfolio sweep (Phase 10 territory), config-closure hashing
  (transitive site-config→referenced-file), and per-build input-hash capture at
  the producer (would remove `--accept`, but is a producer-wide change for a
  consumer-side need).

## Consequences

- Easier: a repeatable, scriptable answer to "what must be rebuilt for this
  event, and why" with a stable exit code; the five gate inputs each invalidate
  exactly their downstream set, proven by the matrix test.
- Duties: the baseline is operator-maintained (`--accept` after a blessed
  build). Closed-world — classification covers declared input kinds and
  registered instances; an unregistered second workbook or an undeclared config
  is invisible, stated in help text. The approved-model leg is inference with
  documented ceilings until the deferred arcpy-gated read lands.
- The arcpy-free invariant and `test_boundary_imports` hold; the command is
  headless and never needs Pro to run.

## Alternatives considered

- **New per-event status sidecar (lockfile):** rejected — `SourceRegistry`
  already provides the store and an accepted write path; a sidecar would
  re-argue the read-only story from scratch.
- **Pure hash-vs-accepted comparison (no timestamp clause):** rejected —
  misclassifies partial rebuilds (a shared input re-accepted after rebuilding
  only one dependent falsely marks the others current), undermining the gate in
  real workflows.
- **Hashing input-path params at the `RecordingCommand._record` choke point:**
  rejected for slice 1 — a producer-side change across every command for a
  consumer-side need (which params are inputs, config closure).
- **Make-style mtime staleness:** rejected — unreliable across clones/copies;
  the roadmap says compare hashes. (Run-record `finished_at` *is* used for the
  chain order — those are our own ledger timestamps, reliable across clones in a
  way file mtimes are not.)
- **Dual-mode exit codes (default 0 + opt-in flag):** rejected — the phase's
  point is automation; a mode that exits 0 on stale is the mode nobody scripts.

## Related decisions

- ADR-0087 — post-catalog production roadmap (Phase 2 ordering)
- ADR-0076 — run-history canonical tool/site identity (the run-history leg)
- ADR-0017 — CSV append-only run history log
- ADR-0091 — Phase 1 qualification runner (sibling: core report model + CLI leaf
  + registry seed pattern)
- ADR-0002 / ADR-0001 — arcpy-free core invariant and core/adapters separation
