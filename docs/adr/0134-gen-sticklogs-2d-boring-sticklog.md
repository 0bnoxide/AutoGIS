# ADR-0134 — GenerateBoringSticklogs: 2D per-boring sticklog from the 8.0a database

**Status:** Accepted
**Date:** 2026-08-20
**Deciders:** Greg / Claude Code
**Related:** ADR-0033 (boring-log DB, 8.0a), ADR-0042 (boring-log report owns
the 8.0a read side)

---

## Context

The boring-log domain renders lithology two ways: tabular (`gen-boring-logs`,
8.0c Markdown) and multi-boring graphical (`generate-subsurface-profile`,
columns positioned along a section line, elevation-anchored). There was no
single-boring graphical log — the classic 2D "sticklog" figure (depth-indexed
lithology column) used in field summaries and quick reviews.

## Decision

Ship `envmon gen-sticklogs` → `core/envmon/sticklog.py`:

- **Reuses the existing seams, adds none:** reads via ADR-0042's
  `read_boring_records`, renders with the same lazy-imported matplotlib under
  the existing `profile` extra, mirrors `render_profile`'s figure conventions
  (neutral `#d9c9a3` lithology fill, identity carried by USCS text labels,
  recessive dotted grid).
- **Depth-based, not elevation-based:** the y-axis is feet below ground
  surface, so a boring with no ground elevation still renders (unlike the
  profile, which must anchor columns to a shared elevation datum).
- **Per-figure content:** hatched lithology bands (USCS-derived texture via
  `uscs_hatch`, a first-letter heuristic — G/S/M/C/O/P — shared with
  `render_profile` so both renderers stay consistent) with in-band USCS
  labels; sample intervals as a bracket lane left of the column with rotated
  sample IDs; a well-construction column right of the lithology column
  (screen components hatched) drawn only when construction rows exist;
  `primary_material, description — PID n ppm` text alongside; the first
  `GroundwaterObservations.depth_to_water` as a dashed water-level line with
  marker. PID is rendered as text, not a second axis (one-axis rule).
- **Skip, don't fake:** a boring with no lithology intervals is skipped with
  a QA warning (`sticklog_no_lithology`) rather than rendered empty — same
  posture as `render_profile`'s missing-ground-elevation skip.
- **Outputs** are `sticklog_<id>.png` or `.svg` per boring into `--out-dir`
  (`--fmt png|svg`, default png; `--borings` filters); the CLI validates the
  DB first via 8.0a's `validate_boring_log_database`, matching
  `gen-boring-logs`.
- **Drive-by fix in `render_profile`** (issue #509): explicit axes limits —
  text artists never autoscale, so a drawable boring with no lithology
  patches left its station label outside the autoscaled view and
  `bbox_inches="tight"` ballooned the canvas (~160 s renders, huge files).
- Registered in `_REGISTRY_SEED` as a post-roadmap extra (`roadmap_id=""`),
  CLOUD, `cartography` — the same registration shape as
  `generate-subsurface-profile` (no `TOOLS` entry: CLOUD, never guarded).

## Consequences

### Positive

- Field teams get the standard single-boring log figure with zero new
  dependencies or read paths; the 8.0a → render pipeline now covers table,
  section and stick views from one database.

### Negative

- The USCS hatch map is a first-letter heuristic, not the full ASTM D2488
  graphic standard (dual symbols key off the primary fraction; the
  `LithologyIntervals.graphic_pattern` column is ignored because its
  vocabulary is undefined). Swap in per-symbol patterns if a deliverable
  requires the ASTM fills.
- Well-construction component labels are drawn only for components thicker
  than 4% of total depth (thin seals would render as unreadable smears);
  thin components remain visible but unlabeled.
- Blow counts/recovery are not on the figure; the 8.0c Markdown log remains
  the complete record.

## Alternatives considered

- **Extending `render_profile` with a single-boring mode:** rejected — the
  profile is elevation-anchored and station-positioned; a depth-axis
  sticklog shares its patterns but not its coordinate system.
- **A new `sticklog` extra:** rejected — same dependency (matplotlib), same
  domain; a second extra is registration noise.

## Related decisions

- [ADR-0033: boring-log DB and attachment index](0033-boring-log-db-and-attachment-index.md)
- [ADR-0042: gen-boring-logs headless Markdown assembly](0042-gen-boring-logs-headless-markdown-assembly.md)
