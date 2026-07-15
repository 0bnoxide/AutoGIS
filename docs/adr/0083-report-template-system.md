# ADR-0083: Report template system — self-contained HTML + shared DesignSync design

**Status:** Accepted
**Date:** 2026-07-11
**Closes:** #163

## Context
Two envmon report tools (`well-inspection-report`, `generate-event-report`)
emitted plain Markdown; a third (`generate-inspection-report`, ADR-0046) embedded
photos only in XLSX. No tool produced a styled report, and #163 asked for a
deliberate, documented templating decision rather than per-tool improvisation.

## Decision
- **Output: self-contained HTML** — CSS inlined, images as base64 `data:` URIs,
  print-optimized (`@media print`) so PDF is a browser Ctrl-P. No `weasyprint`.
- **"Multi-format" means multi report-TYPE**, one output format (HTML) per run,
  additive to the default Markdown. **DOCX and any PDF-rendering library are
  explicitly deferred** (no clean high-fidelity path; separate future work).
- **One canonical `report.css`** (`autogis/core/common/report_assets/`) is the
  single source of truth, consumed by a stdlib-only Python render layer
  (`report_html.py`) AND by DesignSync preview pages **generated from the same
  builders** — markup cannot drift from the design.
- **Data/render split:** each tool has one gather-data function feeding two thin
  renderers (MD, HTML), so counts (incl. the ADR-0079 canonical exceedance dedup)
  are computed once and never diverge.
- **Photos reuse the existing pipeline** (harvester manifest → `match_photos_to_wells`
  → `prepare_image_bytes`) and the existing `autogis[report]` (Pillow) extra,
  lazy-imported. **No new dependency.**

## Consequences
- Reports are archivable/emailable single files that print cleanly.
- The claude.ai/design "AutoGIS Report Templates" project is the reviewable
  visual spec; regenerate + re-push the bundle when the design changes.
- Word output, if ever needed, is a deliberate future ADR — not a silent gap.
