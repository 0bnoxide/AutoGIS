# ADR-042: GenerateBoringLogPDFs (8.0c) — headless Markdown assembly; report module owns the read side 8.0a never shipped

**Status:** Accepted

**Date:** 2026-07-02

## Context

Roadmap tool 8.0c (GenerateBoringLogPDFs) had an approved spec
(`docs/superpowers/specs/2026-06-28-generate-boring-log-pdfs-design.md`) but no
implementation. The spec's core calls were sound: fully headless Markdown/CSV
assembly from the 8.0a boring database, zero PDF/graphics dependencies in core,
PDF conversion an explicit downstream step, lithology and well construction
rendered as depth-indexed tables (no graphical diagrams in v1).

Verifying the spec's assumptions against the shipped 8.0a code surfaced real
discrepancies the implementation had to resolve:

1. **The read source named in the spec does not exist.** The spec (and the
   2026-07-02 remaining-roadmap brief) reference `boring_database.py`; 8.0a
   actually shipped as `core/envmon/create_boring_log_database.py`.
2. **8.0a exposes no read/query API at all** — only `create_boring_log_database`
   and `validate_boring_log_database` (schema scaffold + schema check). The
   spec's `build_boring_log(...)` signature assumes pre-fetched dicts/lists but
   nothing existed to fetch them.
3. **The 8.0a schema has no `drilling_method` column** (closest fields:
   `completion_type`, `driller`), yet the spec's header section and test 1 name
   a drilling-method item.
4. **PID readings live on `LithologyIntervals.pid_ppm`, not on samples**, yet
   the spec's test 3 expects PID readings in the sample table.
5. The spec's `write_outputs(docs, out_dir)` must emit a photo-log `.md`, but
   its `BoringLogDoc` carries only `boring_id`/`markdown`/`sample_rows` — docs
   alone could not feed the photo log.

## Decision

Implement 8.0c as `core/envmon/boring_log_report.py` (stdlib only: sqlite3 +
csv), CLI `envmon gen-boring-logs --db --out-dir [--borings] [--report]`,
adapting to the real 8.0a API rather than the spec's guesses:

- **The report module owns the read side.** `read_boring_records(db_path,
  boring_ids=..., qa=...)` reads the seven-table SQLite DB with
  `sqlite3.Row`, returning per-boring bundles keyed exactly as
  `build_boring_log`'s kwargs (`location`, `lithology`, `samples`,
  `construction`, `groundwater`, `photos`), each record a dict keyed by the
  `schema/boring.py` dataclass field names — the DB columns are derived from
  those same fields (`common/sqlite_schema.py`), so shapes match by
  construction. No changes to 8.0a.
- **Spec signatures honored with two additive deviations:**
  `build_boring_log` gains an optional `qa` kwarg (the spec's own test 7
  requires a WARNING for a sample-less boring), and `BoringLogDoc` gains
  `photo_rows` so `write_outputs(docs, out_dir)` can write `photo_log.md` from
  docs alone.
- **No drilling-method header row** — the schema has no such column; the
  header renders the fields that exist (driller, logged-by, drilling start/end,
  completion type, etc.). Add the row when 8.0a grows the column.
- **Sample-table PID is derived**: max `pid_ppm` over lithology intervals
  overlapping the sample interval (that is where 8.0a stores PID); the
  lithologic column table also shows per-interval PID directly.
- **Outputs:** per-boring `boring_log_<id>.md`, `appendix.md` (with contents
  list), `photo_log.md` and `sample_summary.csv` — photo log and CSV are always
  written (header-only when empty) so downstream packaging can rely on them.
- The CLI validates the DB first (reusing 8.0a's
  `validate_boring_log_database`) and fails cleanly on schema errors; it is
  registered in `runtime/capabilities.py` (TOOLS + `_REGISTRY_SEED`, enforced
  by the drift-guard test).
- `BoringComments` (remarks/approval workflow) are not rendered in v1 — the
  spec's public API omits them; add a remarks section when a deliverable needs
  one.

## Consequences

### Positive consequences

- 8.0c ships fully headless with zero new dependencies; the arcpy-free
  invariant holds (verified by import check and the existing test gate).
- The read API gap in 8.0a is closed where it is consumed, without touching
  8.0a; any future reader can reuse `read_boring_records`.
- Spec-vs-reality discrepancies are recorded here instead of being silently
  papered over.

### Negative consequences

- Lithology/well-construction render as tables, not graphics — a downstream
  PDF/layout step must draw the traditional column if a client requires it
  (explicitly accepted by the spec).
- Deriving sample PID from overlapping lithology intervals is a heuristic; if
  PID ever moves onto samples in the schema, the derivation should be dropped.

## Alternatives considered

- **reportlab/weasyprint in core** — rejected by the spec and by this repo's
  zero-PDF-dependency budget.
- **Adding a read API to `create_boring_log_database.py`** — rejected: 8.0a is
  a scaffold/validate tool; only 8.0c consumes reads today (YAGNI — move the
  reader to `common/` when a second consumer appears).
- **Renaming/aliasing the module to `boring_database.py`** to match the spec's
  name — rejected: back-compat alias for a file that never existed helps no
  one; the spec text is corrected by this ADR instead.

## Related decisions

- [ADR-033: Boring-log DB and attachment index](0033-boring-log-db-and-attachment-index.md) (8.0a)
- Spec: `docs/superpowers/specs/2026-06-28-generate-boring-log-pdfs-design.md`
- Brief: `docs/superpowers/specs/2026-07-02-remaining-roadmap-items-brief.md` §3
