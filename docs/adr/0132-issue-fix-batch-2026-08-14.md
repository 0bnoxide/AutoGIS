# ADR-0132: Issue fix batch (2026-08-14) — manifest decode seam, ADR remote floor, catalog dedupe, QA-warning precision, atomic appendix publish

**Status:** Proposed

**Date:** 2026-08-14

> Filed as an `XXXX-` placeholder while PRs #494/#497 were open with their own
> placeholder ADRs; renumbered to **0132** at merge (0131 was the origin/main
> max; #497's placeholder was the only other open-PR ADR file).

## Context

Five open defects, independently reported, shared one session: two silent- or
wrong-signal failures (#496, #499), one destructive-window failure (#500), one
tooling failure that mints colliding ADR numbers (#495), and one ambiguous
spec authority (#476). Per the ADR-0124/0125 precedent, small independent
fixes verified together ship as one reviewed batch.

## Decision

Fixes, each at its root-cause seam (one implementing agent per fix, assembled
and re-verified together):

- **#496 — malformed manifest.** `load_manifest`
  (`core/envmon/index_field_attachments.py`) now catches
  `json.JSONDecodeError`/`UnicodeDecodeError`/`csv.Error` and re-raises
  `ValueError` naming the file (the ADR-0124 #439 idiom). The three consuming
  CLI commands surface it as `click.ClickException` — clean message, exit 1.
  Residual: PR #497's photo consumers must add `ValueError` to their catch
  once both merge (noted on that PR).
- **#499 — over-reporting QA warning.** `defquery_key_collision` in
  `apply_figure_definition_queries` now names only coerced key names with
  count > 1 (`collections.Counter`), not every non-string key.
- **#495 — stale ADR numbers.** `next_adr_number.py` gains `_remote_max`:
  best-effort `git fetch` + `git ls-tree origin/main docs/adr/` as a third
  floor input inside `_scan_max`, inherited by both `next_adr_number()` and
  `coord_cli.py reserve-adr`. Any git failure warns on stderr (modeled on
  `_NO_GH_WARNING`) and degrades to local floors; a failed fetch still reads
  the stale local `origin/main` ref — a stale floor beats none.
- **#476 — duplicate catalog numbers.** The second occurrence of each
  duplicated §8 heading in `docs/envmon-feature-roadmap.md` (the
  later-appended Civil3D/survey batch) renumbered into the free range —
  8.2→8.10 (Create Civil 3D Contour/Surface Support Files), 8.3→8.11 (Survey
  Import Validator), 8.4→8.12 (Drone Orthomosaic/DSM Registrar), and the
  sub-tool 8.2a→8.10a — first headings keep their numbers, matching the
  README's `Roadmap #` column (owner decision). Registry ids, `.pyt` labels,
  CLI docstring, README follow. The `rid != "8.2"` test exemption is deleted
  and a mechanical no-duplicate-heading guard test added. Historical
  ADRs/logs/snapshots deliberately untouched.
- **#500 — destroyed deliverable under `--overwrite`.** Both PDF combine
  seams (`gen-map-series` in `adapters/cli.py`, `export_layouts` in
  `core/envmon/export_figures.py`) now build into a `.tmp.pdf` and publish
  via `os.replace` (the `dashboard_data_mart` pattern); the previous combined
  appendix survives a mid-append arcpy failure. Deviation from the issue
  sketch: no pre-`unlink` of the destination — `os.replace` overwrites
  atomically and a pre-unlink would reopen the exact window being closed.

## Consequences

Easier: manifest corruption is diagnosable from the CLI message; QA collision
warnings are trustworthy; `reserve-adr` cannot mint an upstream-used number
while warning when unverifiable; `Tool N.N` resolves to exactly one catalog
section (guard test prevents recurrence); `--overwrite` can no longer destroy
the only copy of a client appendix.

Harder / residual: `envmon photos` (PR #497) needs the `ValueError` catch
after merge; #501 (Pillow `ImportError` leaking raw in
`well-inspection-report`) was found during this work and filed separately.

## Alternatives considered

- Five separate PRs — rejected: five reviews for ~150 changed lines;
  ADR-0124/0125 precedent favors one verified batch.
- #500 as a PR stacked on #494 — planned, then #494 merged mid-session, so
  the fix folded into this batch.
- #495 hard-failing when the remote is unreachable — rejected: offline
  reservation must keep working; warn-and-degrade matches the existing
  `_NO_GH_WARNING` path.

## Related decisions

ADR-0124/0125 (fix-batch precedent), ADR-0110 (coord/ADR tooling), ADR-0077
(arcpy doc-verification — applied to the #500 seams), ADR-0012 (manifest
provenance columns).
