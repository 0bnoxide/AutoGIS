# ADR-0122: Report-package integrity and dashboard JSON bridge

**Status:** Proposed

**Date:** 2026-08-01

## Context

`build-report-package` writes SHA-256 values to `manifest.csv`, but no command
checks those values after archive, transfer, or delivery.  Issue #418 also
showed that two spec entries could normalize to one destination: the later
copy overwrote the earlier file while both manifest rows survived.  Sources
named `manifest.csv` or `README.txt` had the same problem because generated
package metadata overwrote them after copying.

Separately, Tool 6.7 already materializes all ten `Dash_*` row lists before
writing them to a geodatabase, while Tool 6.4 consumes one JSON list per table.
The missing producer meant operators had to recreate those JSON files by hand.

The changes must preserve the arcpy-free core import boundary, keep Tool 6.7
LOCAL, add no dependency, and avoid a second dashboard transformation or a
general packaging framework.

## Decision

1. `assemble_figure_package()` preflights every derived destination before it
   creates the output directory.  Identity uses normalized, case-insensitive
   Windows path semantics because packages are built and exchanged on Windows.
   Duplicate destinations and the generated root names `manifest.csv` and
   `README.txt` are rejected, as are Win32-invalid/device/ADS names, ambiguous
   DOS 8.3 short-name forms, lexical parent segments, source named streams, and
   any symlink, reparse-point, or hard-linked output component that could
   redirect a write.  The CLI renders that rejection as a clean Click error.
2. Add the arcpy-free `verify_report_package()` core function and
   `envmon verify-report-package PACKAGE_DIR`.  The verifier checks manifest
   structure, normalized destination uniqueness, actual portable-path
   collisions, relative-path confinement, symlink/reparse/hard-link aliases,
   NTFS named streams on files and directories, declared status, file presence,
   and SHA-256.  Integrity defects are QA `ERROR`; unmanifested files are QA
   `WARNING`, so the shared
   `--fail-on error|warning` policy controls whether extras block.  A CLI
   `build-report-package` and `verify-report-package` require `--report` paths
   to be outside and file-identity-distinct from the package; alternate-stream
   report paths are rejected so reporting cannot invalidate the artifact after
   an in-memory PASS.
3. Add the pure `export_dashboard_json()` helper and an optional
   `build-dashboard-data-mart --export-dir`.  It serializes the already-built
   tables as deterministic UTF-8 `<TableName>.json` lists, rejects non-finite
   JSON and unexpected pre-existing `Dash_*.json` files before writing, stages
   all payloads, and atomically replaces each destination.  Export runs only
   after the GDB mart update completes.
4. Keep the existing Tool 6.7 command and return type.  Do not add a standalone
   GDB reader/export command, dependency, `.pyt` entry, scheduler, or alternate
   schema.  Use the canonical function-scope `arcpy_env()` provider while
   touching the LOCAL module.

## Consequences

Report packages now have a reusable transfer/acceptance gate, and the dashboard
producer writes the exact artifacts its existing consumer expects.

### Positive consequences

- Duplicate, redirecting, hard-linked, ADS, or metadata-overwriting package
  specs fail before output mutation.
- Missing, modified, extra, unsafe, or externally linked package content is
  visible through the standard QA/report/exit-code contract.
- Tool 6.7 to Tool 6.4 no longer needs hand-authored JSON or duplicate
  transformation logic.
- Existing callers are unchanged unless they opt into verification or
  `--export-dir`.

### Negative consequences

- Case-only destination variants are rejected even on case-sensitive hosts so
  the resulting package remains portable to Windows.
- A source carrying an NTFS named stream must be cleaned or copied to a
  stream-free source before packaging.
- Unexpected `Dash_*.json` files block export rather than being deleted; the
  operator must choose how to preserve or remove them.
- GDB updates and the JSON set are not one cross-storage transaction.  JSON
  files are replaced atomically one at a time after successful serialization.
- JSON production still requires the LOCAL Tool 6.7 run; this change does not
  introduce a headless GDB reader.

## Alternatives considered

1. **Add only a verifier:** rejected because a verifier cannot make #418's
   ambiguous manifest truthful after the producer has overwritten a file.
2. **Add a separate dashboard-export command that rereads the GDB:** rejected;
   Tool 6.7 already owns the rows in memory and a second ArcPy read path adds
   code without adding capability.
3. **Use GDAL or a packaging dependency:** rejected; CSV, SHA-256, path checks,
   and JSON are covered by the standard library.
4. **Delete stale dashboard JSON automatically:** rejected as an unnecessary
   destructive side effect.  Fail closed and let the operator decide.

## Related decisions

- [ADR-0039](0039-cli-first-generation-2-local-tools.md) — Tool 6.7 remains
  CLI-first LOCAL.
- [ADR-0040](0040-canonical-arcpy-access-style.md) — function-scope
  `arcpy_env()` provider.
- [Issue #418](https://github.com/0bnoxide/AutoGIS/issues/418) — duplicate
  report-package destinations.
- [Issue #429](https://github.com/0bnoxide/AutoGIS/issues/429) — redirected
  destination writes and unmanifested NTFS streams.
- [Issues #424](https://github.com/0bnoxide/AutoGIS/issues/424) and
  [#428](https://github.com/0bnoxide/AutoGIS/issues/428) — separate dashboard
  consumer safety defects, not expanded into this batch.
- [Issues #426](https://github.com/0bnoxide/AutoGIS/issues/426) and
  [#427](https://github.com/0bnoxide/AutoGIS/issues/427) — separate producer
  input-shape defects.
