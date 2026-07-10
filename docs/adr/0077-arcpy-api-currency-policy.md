# ADR-0077: arcpy API-currency policy — verify every arcpy call against current docs, target Pro ≥3.5

**Status:** Accepted

**Date:** 2026-07-10

## Context

arcpy code in this repo is structurally untestable: `core/` and `adapters/`
import arcpy-free, arcpy seams are `# pragma: no cover`, and the suite runs
headless. A plausible-looking arcpy call therefore ships unverified and fails
only when a user opens it in ArcGIS Pro. This has now bitten three times:

- PR #174 review round 1 "fixed" a mosaic call with `extent="INTERSECTION"` —
  not a valid keyword (`"MINOF"` is); round 2 caught the fix being wrong.
- Issue #214: `ConditionDEM.getParameterInfo` used `domain=("", "median")`;
  arcpy's ValueList `FilterObject` rejects `""`, so the tool dialog could not
  even open (PR #216).
- The #214 audit found `arcpy.conversion.TableToTable` /
  `FeatureClassToFeatureClass` still in use — formally deprecated since
  Pro 3.2, replaced by `ExportTable` / `ExportFeatures`.

ArcGIS Pro releases frequently and deprecates/renames geoprocessing tools and
parameters as it goes. Training-data recall of arcpy signatures is not
evidence.

## Decision

Any change that **bridges to arcpy** — a new arcpy call, an edited arcpy call,
a `.pyt` parameter definition, or a "fix" to either — MUST be verified against
the current Esri documentation (pro.arcgis.com / doc.esri.com tool-reference
pages) **before** it ships, in the same session that writes it:

1. **Verify the exact call**: tool name, module (`management`/`conversion`/
   `sa`/`ddd`/`mp`), positional signature, and every keyword/enum value used.
   Quote-check enum keywords (the `INTERSECTION` class of bug) — do not infer
   them.
2. **Check deprecation status** on the tool's doc page. A "deprecated tool"
   banner means use the named replacement. A "newer alternative recommended"
   note (e.g. `SurfaceParameters` vs `Slope`) is not deprecation — switching
   is optional and needs its own justification.
3. **Compliance floor is ArcGIS Pro 3.5; prefer 3.6/3.7.** No call may be
   used that is deprecated as of 3.5. When 3.6/3.7 docs name a replacement,
   use the replacement unless it does not exist at 3.5.
4. **Reviews of arcpy code follow the same rule**: a reviewer proposing an
   arcpy fix must doc-verify the fix itself (PR #174's lesson — a fix that
   satisfies a review is not thereby correct).
5. `.pyt` parameter/filter objects count as arcpy calls (issue #214's lesson —
   `getParameterInfo` can crash the tool dialog before `execute` ever runs).

Cite the doc page(s) consulted in the PR description.

## Consequences

- Slower to write arcpy seams; that is the point — the suite cannot catch
  these, so verification moves to authoring time.
- Existing calls were audited clean as of 2026-07-10 (PR #216): all cursors
  are `arcpy.da.*`, layout code is `arcpy.mp`, no deprecated conversion calls
  remain. Future audits only need to cover new/changed code.
- Manual ArcGIS Pro verification (open the tool, run it) remains the final
  gate for `.pyt` changes; doc verification does not replace it.
