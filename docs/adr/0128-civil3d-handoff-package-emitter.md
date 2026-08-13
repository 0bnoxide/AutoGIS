# ADR-0128: `autogis handoff` — contract-v1 Civil 3D handoff package emitter

**Status:** Proposed

**Date:** 2026-08-12

## Context

AutoGIS-Civil3D roadmap Phase 3 ("producer adoption") requires AutoGIS to
emit handoff packages conforming to that repository's contract v1 and to
pass a live cross-repository compatibility check. The consumer repository's
spec (`docs/superpowers/specs/2026-08-11-phase-3-producer-adoption-design.md`
in `0bnoxide/AutoGIS-Civil3D`) states four producer obligations:

1. a headless CLI command (name and flags are this repository's choice,
   recorded here);
2. the packaged `surface.landxml` is produced by the production writer
   (`write_landxml_surface`), not passed through from the input;
3. **never infer** — units and horizontal EPSG resolve from the source or
   the command fails loudly; vertical datum comes only from explicit caller
   input and is otherwise declared `unknown`;
4. no contract knowledge is duplicated — no vendored schema, no
   emission-time self-validation; conformance is proven exclusively by the
   consumer repository's validator.

Contract v1 facts the design rests on (verified against the consumer
repository's validator source and schema):

- The package is a ZIP containing exactly `handoff.json` and
  `surface.landxml` at the root (Stored or Deflated, no extra entries).
- `handoff.json` requires `contract_version "1.0"`, a UUID `package_id`,
  `created_utc` (UTC, trailing `Z`), `producer {name, version,
  source_commit?}`, `surface {filename, sha256 (lowercase hex of the entry
  bytes), landxml_version "1.2", name, point_count, face_count}`, and
  `coordinate_reference` with `horizontal {kind "projected", authority
  "EPSG", code, unit}` and `vertical {unit, direction "positive_up",
  datum}`. Units are exactly `metre` | `international_foot` |
  `us_survey_foot`. The datum is either
  `{"status":"known", authority, code, name}` or
  `{"status":"unknown", note?}`.
- The validator's only warning is `WRN001` (unknown vertical datum); the
  Phase 3 gate requires exit 0 with zero warnings, so gate evidence needs a
  caller-supplied known datum. The unknown-datum path stays legal for real
  use but is never gate evidence.
- Our existing writer output already satisfies the validator's LandXML
  envelope: LandXML-1.2 namespace and `version="1.2"`, a `Units` block with
  `linearUnit` `meter`/`foot`/`USSurveyFoot` and `elevationUnit`
  `meter`/`feet`, and `CoordinateSystem/@epsgCode`.

The owner chose the CLI surface; the remaining design decisions were
delegated to agent judgment and are individually logged with reasoning in
[`logs/2026-08-12-agent-decisions.md`](logs/2026-08-12-agent-decisions.md)
(the ADR-0030/0031 pattern).

## Decision

**CLI.** One new top-level command, `autogis handoff` (owner decision —
single command like `harvest`, not a group). It is a thin adapter in
`autogis/adapters/cli.py` (ADR-0029) and gets run-history recording for
free via `RecordingCommand` (ADR-0054).

**Core.** One new arcpy-free flat module `autogis/core/handoff.py`
(precedent: `core/qualify.py`, ADR-0091) exposing
`build_handoff_package(...)`. Stdlib (`zipfile`, `json`, `uuid`,
`hashlib` via the existing helper, `datetime`) plus existing core only:
`parse_landxml_surface`, `write_landxml_surface`, `parse_epsg` from
`core/common/landxml.py` and `compute_sha256` from
`core/envmon/source_registry.py`. No pyproj, no new dependencies, no new
extras — the command works in the base install.

**Flags** (exact surface):

- `--input` (required, existing file): source LandXML containing the TIN
  surface.
- `--output` (required): package ZIP path; refuses to overwrite unless
  `--overwrite`, and always rejects an output that resolves to the same
  file as `--input` (the `transform-landxml` guard,
  `landxml_transform.py`) — `--overwrite` must never destroy the source.
- `--surface-name` (optional): selects among multiple surfaces in the
  source; default is the first surface.
- `--vertical-unit` (required; choice `metre` | `international_foot` |
  `us_survey_foot`): always explicit, cross-checked against the source's
  declared `elevationUnit` family when present (`meter` → `metre`;
  `feet` → either foot flavor; mismatch is an error).
- `--vertical-datum-authority`, `--vertical-datum-code` (integer ≥ 1),
  `--vertical-datum-name`: all three or none. All three present → datum
  `{"status":"known", ...}`. None → `{"status":"unknown"}`. A partial set
  is a usage error.
- `--vertical-datum-note` (optional): only valid without the known-datum
  trio (the contract's known shape has no note field).
- `--source-commit` (optional): recorded verbatim in
  `producer.source_commit`; must match `^[0-9a-f]{7,64}$`.

**Data flow.** Parse the source with `parse_landxml_surface`; re-emit the
selected surface with `write_landxml_surface` into a temp file (writer-path
re-emission: the packaged bytes are production writer output); hash the
re-emitted file with `compute_sha256`; assemble the manifest as a plain
dict and `json.dumps` it; write both entries into the ZIP (Deflated).
Manifest `surface.name` and the point/face counts come from the parsed
surface verbatim.

**Never infer.** The horizontal EPSG code and linear unit are read only
from the source LandXML's declared `CoordinateSystem/@epsgCode` and
`Units/@linearUnit` — missing, unparseable, or unsupported declarations
fail the command with a clear message; there are no override flags. The
LandXML→manifest unit mapping is the contract's fixed table (`meter` →
`metre`, `foot` → `international_foot`, `USSurveyFoot` →
`us_survey_foot`), not a heuristic. The source-metadata extraction is
shared with `landxml_transform` by promoting its private
`_source_metadata` to a public helper in `core/common/landxml.py` — one
extraction path, two consumers, no duplication.

**Producer identity.** `producer.name` is the constant `"AutoGIS"`.
`producer.version` reads a new `__version__` constant in
`autogis/__init__.py` (currently-empty file), pinned to the `pyproject.toml`
version by a test so the two cannot drift silently. `source_commit` appears
only when the caller passes it.

**No self-validation.** The module builds the manifest as plain data. There
is no schema file in this repository and no validation pass over the
emitted package. The consumer repository's CI compat harness checks out
AutoGIS at a pinned commit, runs this command on a fixture-derived LandXML
with explicit metadata, and requires validator exit 0 with zero warnings,
plus a negative control.

**Tests.** Pytest, arcpy-free, base-install: unit tests on
`build_handoff_package` (manifest field values, sha256 matches the entry
bytes, exact ZIP entry set, never-infer failure cases, datum trio rules,
identical input/output rejection even with `--overwrite`)
and a `CliRunner` test over `autogis handoff`. No validator dependency in
this repository's tests.

## Consequences

### Positive consequences

- Base-install, headless, arcpy-free command with zero new dependencies.
- The packaged surface bytes are exactly what the production writer emits
  — conformance evidence covers the real writer path, not a bypass.
- Conformance is falsifiable and continuously proven by the consumer
  repository's harness; this repository never chases the contract schema.
- Explicit-only metadata means a package can never silently carry guessed
  units, CRS, or datum.

### Negative consequences

- Producer changes reach the compatibility gate only when the consumer
  repository bumps its pinned AutoGIS commit (deliberate, bounded
  staleness).
- `__version__` duplicates the `pyproject.toml` version (drift is
  test-pinned, but it is still two locations).
- Authoring mistakes surface only in the consumer's validator, not at
  emission time — the cost of the no-self-validation rule.
- When a caller genuinely lacks a vertical datum, a zero-warning package is
  unreachable by design; the fix is upstream data, never fabrication.

## Alternatives considered

- **`autogis handoff pack` (group) / `autogis civil3d pack`** — owner chose
  the flat single command; a one-member group is ceremony, and the
  consumer-named group couples the surface to one consumer.
- **`importlib.metadata` for `producer.version`** — fails under the
  `PYTHONPATH`/`propy.bat` uninstalled mode this repository explicitly
  supports; a constant plus a drift test works everywhere.
- **Auto-detecting `source_commit` from git** — deployed installs have no
  `.git`; provenance should be explicit input, not environment sniffing.
- **pyproj-based CRS resolution** — the contract needs the declared EPSG
  code echoed, not datum mathematics; pyproj would drag the command out of
  the base install for no benefit.
- **Vendored schema or emission-time self-validation** — forbidden by
  producer obligation 4; the validator is the single oracle.
- **Deriving the vertical foot flavor from the horizontal `linearUnit`** —
  inference; LandXML's `elevationUnit="feet"` genuinely does not
  distinguish international from US survey foot, so the caller must.
- **A `core/handoff/` subpackage** — one module suffices
  (`core/qualify.py` precedent); a subpackage adds structure for a future
  that may never come.

## Related decisions

- [ADR-0001: Core-plus-adapters architecture](0001-core-adapters-separation.md)
- [ADR-0002: Arcpy-free core invariant](0002-arcpy-free-core-invariant.md)
- [ADR-0029: validate_*/manage_* are intentionally thin adapters](0029-validation-adapters-are-intentionally-thin.md)
- [ADR-0054: CLI-seam run recording](0054-cli-seam-run-recording-recording-command.md)
- [ADR-0061: read-only LandXML TIN parser](0061-drone-geotech-graphics-tool-batch.md)
- [ADR-0071: LandXML as the CAD point-export format](0071-export-survey-cad-landxml-format.md)
- [ADR-0088](0088-civil3d-cad-export-arcpy-legs.md) / [ADR-0089](0089-cad-layer-properties-and-civil3d-tin-landxml.md): Civil3D/CAD arcpy legs
- [ADR-0118: LandXML surface CRS and unit transformation](0118-landxml-surface-crs-unit-transformation.md)
- [Judgment-call audit log for this ADR](logs/2026-08-12-agent-decisions.md)
- External: `0bnoxide/AutoGIS-Civil3D` Phase 3 spec
  (`docs/superpowers/specs/2026-08-11-phase-3-producer-adoption-design.md`),
  gate issue AutoGIS-Civil3D#78, read-only deploy key AutoGIS-Civil3D#75
