# ADR-0099: Monitoring-event review notebook (roadmap Phase 4)

**Status:** Accepted — owner sign-off for roadmap Phase 4 (async, 2026-07-22:
"I approve recommended items, log your judgement")

**Date:** 2026-07-22

**Addresses:** Production roadmap Phase 4 (`docs/production-roadmap.md`);
ordering per ADR-0087

**Design spec:** `docs/superpowers/specs/2026-07-22-phase4-event-review-notebook-design.md`

**Judgment audit:** `docs/adr/logs/2026-07-22-agent-decisions.md`

## Context

Phase 4 of the post-catalog roadmap ships the first user-facing review surface: a
single supported notebook that presents a monitoring event's import summary, QA
findings, completeness, screening, comparisons, trends, map-ready data,
readiness state, and reviewer decision. Governance for the phase is explicit:
reusable behavior stays in `autogis.core`; notebooks are review/exploration
surfaces, **not** a fourth implementation; start with the smallest useful slice.

`generate_event_report.py` already renders five of the nine sections
(results/screening, comparisons, trends, data gaps, RPD QA) as Markdown and
HTML. It does **not** cover import summary, readiness state, reviewer decision,
map-ready data, or version/hash provenance, and nothing aggregates all nine into
one surface. The marginal value of the notebook is therefore *aggregation +
interactivity*, and every missing section already has a public, headless (no
arcpy) core producer.

Two facts shaped the slice:
- The headless path to a results dataset is a **records-CSV**
  (`read_records_csv(path, AnalyticalResultRecord)`), not the GDB. `import-edd`
  targets a file GDB and needs ArcGIS Pro; the review producers all consume
  CSVs. The notebook stays entirely on the arcpy-free CSV path.
- The `gen-synthetic-workbook` command is a dead end for this purpose: its output
  has no lab profile / importer path into a results CSV (only cell-level parser
  tests consume it). A purpose-built fixture is required.

## Decision

Ship one notebook, `notebooks/monitoring_event_review.ipynb`, that **only**
imports existing core producers and displays their output — no new domain logic,
no logic in cells. (One incidental **1-line** core fix: `generate_event_report`
now recognizes the `TrendClass` column that `compare-events` actually emits, so
the trend section stops rendering all-`UNKNOWN` off real producer output — a
latent integration bug surfaced while wiring the notebook, covered by a
regression test. No other core change.) Sections map to existing producers: provenance
(`importlib.metadata.version` with a pyproject fallback + `compute_sha256`),
the five-section `generate_event_report_html` rendered inline via
`IPython.display.HTML`, `results_to_feature_collection` for map-ready data,
`evaluate_readiness` for readiness, and the reviewer-comment tracker summary.

`compliance_summary` and `qc_sample_summary` are **excluded** from slice 1 — not
among the roadmap's nine sections (YAGNI; `qc_sample_summary` already carries a
`ponytail:` deferral).

**Fixture (the real deliverable of the phase).** A synthetic, sanitized
**two-event** results records-CSV (so comparisons/trends are non-empty), plus a
samples CSV (RPD), a schedule YAML (completeness), and a screening YAML scoped to
the fixture's analytes. All generated — no client data, no redaction dependency.
The fixture's screening levels come from its own YAML so the pre-production
`screening_levels.yaml` DRAFT stub stays untouched (CLAUDE.md invariant).

**Verification.** A new opt-in extra `notebook = ["nbclient", "ipykernel"]` (the
only new dependency in the phase, not in the default install). One
`pytest.importorskip("nbclient")`-gated test executes the notebook fresh against
the fixture in a real kernel and asserts a clean restart-run-all. The arcpy-free
dev suite, lacking the extra, skips it and stays green.

## Consequences

- The first end-to-end reviewer surface exists and runs headlessly; no ArcGIS
  Pro, no client data.
- One new opt-in dependency group. Default installs and CI (such as it is) are
  unaffected; only the notebook-execution test needs it.
- The notebook is committed outputs-stripped by hand (the test regenerates
  outputs in a tmp dir). No nbstripout/`.gitattributes` automation until a
  second notebook justifies it (YAGNI).
- Adding a section later is a cell that calls an existing producer; genuinely new
  review logic must land in `autogis.core` first, per governance.

## Alternatives considered

- **Skip Phase 4 as "already shipped" and jump to a greenfield phase (7/8).**
  Rejected: `generate_event_report` covers only ~5 of 9 sections, and reordering
  phases requires an explicit user decision (ADR-0087); the user directed a
  roadmap task and Phase 4 is next.
- **Drive the fixture through `import-edd` → GDB.** Rejected: pulls arcpy into a
  headless review surface and its verification; the CSV path is arcpy-free and is
  what every producer already consumes.
- **`gen-synthetic-workbook` as the fixture source.** Rejected: no profile/import
  path turns its output into a results CSV — a missing link, not a shortcut.
- **Zero-dependency notebook-execution test** (exec code cells in a namespace).
  Rejected by owner in favor of a real-kernel `nbclient` run; the exec approach
  breaks on `IPython.display` which the inline-HTML design uses.

## Related decisions

- ADR-0087 (roadmap ordering), ADR-0093 (Phase 2 event-status — readiness inputs)
- ADR-0002 (arcpy-free core invariant), ADR-0008 (dependency-as-base bar)
- ADR-0075 (canonical schema / screening DRAFT stub invariant)
