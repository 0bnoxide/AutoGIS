# Dan-Patterson numpy-geometry Recon — Design

**Date:** 2026-06-23
**Status:** Approved (recon only; no code until license confirmed)
**Scope:** Read-only license audit + algorithm inventory for
`Dan-Patterson/Tools_for_ArcGIS_Pro` before any selective vendor.
**Repo integration source:** `docs/repo-integration-roadmap.md` — Tier 1B
(numpy-first patterns, license ⚠️ verify before copying).

---

## Purpose

`repo-integration-roadmap.md` identifies `Dan-Patterson/Tools_for_ArcGIS_Pro`
(and its geometry source-of-truth `Dan-Patterson/numpy_geometry`) as a source of
numpy-first algorithms that perform operations normally gated behind ArcGIS
Standard / Advanced license — e.g. coordinate rotation, point-in-polygon,
nearest-neighbor, convex hull — using only numpy + `arcpy.da` cursors at the
I/O edge.

Three things must be verified **before a single line is vendored**:

1. **License:** the roadmap explicitly warns "⚠️ verify before copying." The
   GitHub page shows no license badge; the repo's top-level `LICENSE` file (if
   any) must be fetched and classified.
2. **Algorithm inventory:** which functions in the repo solve problems AutoGIS
   actually has (contour point smoothing, coordinate reprojection, spatial
   statistics for callout placement, etc.).
3. **Attribution template:** the roadmap mandates preserving attribution. Drafting
   the attribution note now prevents it being forgotten at vendor time.

This plan runs a two-agent parallel recon wave. No code is written.

---

## Goals

1. Confirm license type and whether vendor copy is permitted.
2. Enumerate 3–5 specific functions/modules that map to AutoGIS use cases.
3. Draft an attribution block for use in vendored files.
4. Produce a `needs-human` queue for any ambiguous license interpretation.

## Non-Goals

- Writing any vendored code (blocked until license confirmed).
- Evaluating the full Tools_for_ArcGIS_Pro repo — focus on algorithms
  useful to `core/envmon/` and `core/agol/` only.
- Evaluating the C#/Pro SDK samples repo (explicitly dropped in roadmap).

---

## Architecture (recon wave)

Two read-only agents run in parallel:

| Agent | Scope | Tool type |
|---|---|---|
| N1 — License auditor | `Dan-Patterson/Tools_for_ArcGIS_Pro` + `Dan-Patterson/numpy_geometry` root files (LICENSE, README, headers) | `Explore` |
| N2 — Algorithm inventory | `Dan-Patterson/Tools_for_ArcGIS_Pro` src modules; match against AutoGIS use cases | `Explore` |

**Output format** (both agents, same schema as the existing recon wave):
```
CLAIM:    <question being answered>
VERDICT:  confirmed | needs-human | blocked (no license / access denied)
EVIDENCE: <file:line or URL>
DELTA:    <what this changes about the integration plan>
RISK:     <what breaks if we proceed without this answer>
```

The orchestrator consolidates into a `specs/2026-06-23-numpy-geo-deltas.md`
artifact (a sibling of `specs/2026-06-19-mergeplan-deltas.md`).

---

## Inputs to the recon agents

**N1 — License questions:**
- Does `Dan-Patterson/Tools_for_ArcGIS_Pro` have a top-level `LICENSE` file?
- If yes, what SPDX license identifier?
- Does `Dan-Patterson/numpy_geometry` (the geometry source of truth) have a
  separate license that differs?
- Do individual Python files carry license headers that restrict copying?

**N2 — Algorithm questions:**
- Which modules/functions perform **coordinate rotation** or **affine
  transform** without arcpy geometry objects?
- Which modules perform **convex hull** or **point cluster bounding box**
  (useful for callout placement)?
- Which modules implement **nearest-neighbor** or **spatial join** equivalents
  using numpy only?
- Is there a **contour smoothing** or **Bezier fitting** utility?
- What is the numpy/arcpy.da boundary: does any algorithm create an `arcpy.Point`
  object (Standard-licensed), or does it only use `arcpy.da` cursors?

---

## Deliverable

`docs/superpowers/specs/2026-06-23-numpy-geo-deltas.md` with:
- Verdict table (N1 + N2)
- License classification + vendor-permitted? (yes / no / needs-human)
- Shortlist of 3–5 functions to vendor (if permitted)
- Draft attribution block
- needs-human queue (surfaced to user before any vendor work begins)
