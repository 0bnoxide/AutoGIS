# Dan-Patterson numpy-geometry Recon Dispatch — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> to implement this plan. Dispatch both recon agents in a SINGLE message (true
> parallel). Steps use checkbox (`- [ ]`) syntax.

**Goal:** Parallel read-only recon wave that answers license + algorithm
questions for `Dan-Patterson/Tools_for_ArcGIS_Pro` and its geometry source
repo `Dan-Patterson/numpy_geometry` before any vendor copy begins.

**Architecture:** Orchestrator dispatches N1 + N2 as `Explore` agents in one
message. Both are read-only. Orchestrator consolidates into the deltas doc.

**Tech Stack:** Claude Code `Explore` subagents, GitHub MCP tools, markdown.

**Source spec:** `docs/superpowers/specs/2026-06-23-numpy-geo-recon.md`
**Repo integration source:** `docs/repo-integration-roadmap.md` Tier 1B

## Global Constraints

- Recon agents are **READ-ONLY.** No file writes, no git operations.
- Both agents dispatched in **one message** (parallel). Do not sequence them.
- Every agent returns the fixed `CLAIM/VERDICT/EVIDENCE/DELTA/RISK` format.
- Do NOT vendor any code before the deltas doc is reviewed by the user.
- The deltas doc is the sole writable output of this plan.

## File Structure

- **Create:** `docs/superpowers/specs/2026-06-23-numpy-geo-deltas.md`
- **Read-only audit targets:** `Dan-Patterson/Tools_for_ArcGIS_Pro` (GitHub),
  `Dan-Patterson/numpy_geometry` (GitHub)

---

### Task 1: Dispatch the recon wave (N1 + N2, parallel)

**Files:** read-only (GitHub MCP tools or WebFetch)

**Interfaces:**
- Consumes: `Dan-Patterson/Tools_for_ArcGIS_Pro` and `Dan-Patterson/numpy_geometry`
  public GitHub repos
- Produces: 2 agent reports in `CLAIM/VERDICT/EVIDENCE/DELTA/RISK` format

**Shared suffix appended to every agent prompt:**
```
You are READ-ONLY. Do not edit, write, or create any file. Return findings
ONLY in this exact format, one block per claim:

CLAIM:    <the question being answered>
VERDICT:  confirmed | needs-human | blocked
EVIDENCE: <file:line, URL, or "not found">
DELTA:    <what this changes about integration; "none" if confirmed>
RISK:     <what breaks if unanswered; "none" if confirmed>
```

- [x] **Step 1: Dispatch both agents in a single message**

**N1 — License auditor (Explore):**
```
Audit the license situation for two public GitHub repos:
(1) Dan-Patterson/Tools_for_ArcGIS_Pro
(2) Dan-Patterson/numpy_geometry

For each repo: fetch the root directory listing, then fetch any LICENSE,
LICENSE.md, LICENSE.txt, or COPYING file. Also check README.md for license
mentions. Also scan the first 20 lines of 3–5 Python source files for
copyright/license headers.

Answer these claims:
CLAIM: Does Dan-Patterson/Tools_for_ArcGIS_Pro have a top-level LICENSE file,
       and if so what SPDX identifier (MIT, Apache-2.0, GPL-*, etc.)?
CLAIM: Does Dan-Patterson/numpy_geometry have a top-level LICENSE file,
       and if so what SPDX identifier?
CLAIM: Do individual Python files in either repo carry license headers that
       restrict or permit copying?
CLAIM: Is vendor copy (copy selected source files with attribution into a
       commercial/proprietary project) permitted under the license found?
```

**N2 — Algorithm inventory (Explore):**
```
Audit the public GitHub repo Dan-Patterson/Tools_for_ArcGIS_Pro (and, if
relevant, Dan-Patterson/numpy_geometry) to inventory numpy-first geometric
algorithms with no arcpy geometry object dependency.

Answer these claims:
CLAIM: Is there a coordinate rotation or affine transform function that
       operates on numpy arrays (not arcpy.Point objects)?
       Evidence: module name, function name, file:line.
CLAIM: Is there a convex hull or bounding-box function over a numpy point
       array (not requiring arcpy geometry)?
       Evidence: module name, function name, file:line.
CLAIM: Is there a nearest-neighbor or spatial-join equivalent using only numpy?
       Evidence: module name, function name, file:line.
CLAIM: Is there a contour smoothing, Bezier fitting, or polyline generalization
       function operating on numpy arrays?
       Evidence: module name, function name, file:line.
CLAIM: For each function found: does it ever create an arcpy.Point,
       arcpy.Polyline, or arcpy.Polygon object (Standard-licensed), or does it
       stay in pure numpy / arcpy.da cursors only?
```

- [x] **Step 2: Verify both returned in format**

  Confirm 2 reports received, each with `CLAIM/VERDICT/EVIDENCE/DELTA/RISK`
  blocks. If either returned thin or off-format output, re-dispatch ONLY that
  agent — not the whole wave.

---

### Task 2: Consolidate into the deltas doc

**Files:**
- Create: `docs/superpowers/specs/2026-06-23-numpy-geo-deltas.md`

**Interfaces:**
- Consumes: 2 validated agent reports from Task 1
- Produces: committed deltas doc with license verdict + algorithm shortlist

- [x] **Step 1: Write the deltas doc**

  ```markdown
  # numpy-geometry Recon Deltas

  **Date:** 2026-06-23
  **Source plan:** docs/superpowers/plans/2026-06-23-numpy-geo-recon.md

  ## Verdict table
  | Agent | Claim | Verdict | Delta |
  ...

  ## License classification
  <SPDX identifier + vendor-permitted: yes / no / needs-human>

  ## Algorithm shortlist (if license permits)
  <3–5 functions with module:line references and AutoGIS use case mapping>

  ## Draft attribution block
  <ready to paste into any vendored file header>

  ## needs-human queue
  <any ambiguous license interpretation requiring user decision>
  ```

- [x] **Step 2: Verify no empty sections**

  Every section must be populated or explicitly say "none." Covered.

---

### Task 3: Surface needs-human queue and gate vendor work

**Files:**
- Modify: `docs/superpowers/specs/2026-06-23-numpy-geo-deltas.md`

**Interfaces:**
- Consumes: deltas doc from Task 2
- Produces: user acknowledgment recorded in doc; vendor work unblocked or parked

- [x] **Step 1: Present needs-human queue to user**

  **Decision recorded 2026-06-24:** Neither repo has a LICENSE file — default
  copyright applies. User will contact Dan Patterson directly
  (`dan_patterson@carleton.ca`) to request an explicit license grant.
  Implementation is **PARKED** pending response. Algorithm shortlist and
  attribution block are ready in the deltas doc for when the license is confirmed.

  User note: "I think Dan Patterson intends free use — I'll reach out and put it
  on the back burner until I hear back."

- [x] **Step 2: Commit the deltas doc**

  Committed in `0890026` alongside arcgis consolidation and AGOL publish-layer.

---

## Self-Review

**Spec coverage:** All 4 spec goals covered — license (N1), algorithm inventory
(N2), attribution draft (Task 2 Step 1), needs-human queue (Task 3). Non-goal
(no vendor code) enforced by Global Constraint. Covered.

**Placeholder scan:** Both agent briefs are written in full with explicit claims.
Deltas doc sections are enumerated. No "TBD" or "similar to prior" shortcuts.

**Type consistency:** `CLAIM/VERDICT/EVIDENCE/DELTA/RISK` format is identical
in spec, plan, and agent prompts — mirrors `2026-06-19-parallel-recon-dispatch.md`.
