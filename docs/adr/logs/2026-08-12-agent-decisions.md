# Agent decisions — 2026-08-12

Session: Claude (handoff-packaging design, ADR-0128). The owner picked the
CLI surface (`autogis handoff`, single top-level command) and delegated the
remaining design decisions: "use your best judgement … logged for
retrospective audit if needed." Each call below records what was chosen,
what was rejected, and why. The architectural decision itself is
[ADR-0128](../0128-civil3d-handoff-package-emitter.md); this log is the
per-decision audit, not a substitute (see `logs/README.md`).

## 1. Core placement: flat `autogis/core/handoff.py`

- **Decision:** one flat module under `core/`, not a `core/handoff/`
  subpackage and not a module inside `core/common/`.
- **Reasoning:** `core/qualify.py` (ADR-0091) is the precedent for a flat
  single-module domain. `core/common/` is shared substrate, and handoff
  packaging is a feature, not substrate. A subpackage for one module is
  structure bought before it's needed.
- **Revisit if:** the producer grows a second module (e.g. a package
  inspector or a second contract version) — promote to a subpackage then.

## 2. `producer.version` from a new `autogis.__version__` constant

- **Decision:** add `__version__` to the (currently empty)
  `autogis/__init__.py`, read it in the command, and pin it to the
  `pyproject.toml` version with a test.
- **Reasoning:** `importlib.metadata` raises `PackageNotFoundError` in the
  uninstalled `PYTHONPATH`/`propy.bat` mode this repo explicitly supports
  (`__main__.py` exists for exactly that mode); a constant works in every
  mode. Nothing in the codebase reads a version at runtime today, so there
  is no existing convention to follow. The drift risk of two locations is
  closed by the test.
- **Revisit if:** packaging moves to a dynamic-version backend
  (`setuptools-scm` or `[tool.setuptools.dynamic]`) — then invert: pyproject
  reads the constant.

## 3. `--vertical-unit` is always required

- **Decision:** the caller always states the manifest vertical unit
  explicitly; the command cross-checks it against the source's declared
  `elevationUnit` family when one is present (mismatch = error) rather than
  deriving it.
- **Reasoning:** LandXML `elevationUnit="feet"` cannot distinguish
  international foot from US survey foot, so at least the imperial case
  must be explicit. Deriving the foot flavor from the horizontal
  `linearUnit` would be inference, which the contract forbids. Making the
  flag conditional (required only for imperial sources) is a more
  complicated rule for the caller than "always say it"; and always-explicit
  also covers sources that omit `elevationUnit` without adding a special
  case.
- **Revisit if:** callers report the metric-case flag as pure friction and
  the owner prefers a metric-only default — that would be a deliberate
  relaxation, recorded as an ADR amendment.

## 4. Vertical-datum flags: all-or-none trio, note only with unknown

- **Decision:** `--vertical-datum-authority/-code/-name` must appear as a
  complete trio (→ `status: known`) or not at all (→ `status: unknown`);
  `--vertical-datum-note` is rejected alongside the trio.
- **Reasoning:** mirrors the contract's `oneOf` exactly — the known shape
  requires all three fields and has no `note` property
  (`additionalProperties: false`), so any other flag combination could only
  produce an invalid manifest. Failing at the CLI with a usage error is the
  never-infer behavior: no filling in a missing datum name, no dropping a
  stray note silently.
- **Revisit if:** contract v2 changes the datum shape.

## 5. `--source-commit` is explicit input, never auto-detected

- **Decision:** optional flag validated against the contract pattern
  `^[0-9a-f]{7,64}$`; omitted → field omitted. No `git rev-parse`
  fallback.
- **Reasoning:** deployed installs (ArcGIS Pro machines) have no `.git`;
  auto-detection would make the same command emit different manifests
  depending on where it runs — environment sniffing where the contract
  wants explicit provenance. The consumer repo's compat harness knows its
  pinned commit and passes it.
- **Revisit if:** never likely; a build pipeline that stamps versions could
  pass the flag itself.

## 6. Promote `landxml_transform._source_metadata` to a public helper

- **Decision:** move the source-CRS/unit extraction into
  `core/common/landxml.py` as a public function; `landxml_transform` and
  `core/handoff.py` both call it.
- **Reasoning:** the handoff command needs exactly this extraction
  (declared `CoordinateSystem`/`Units` of a LandXML file). Importing a
  private `_`-function across modules or duplicating ~30 lines are both
  worse; the shared-seam fix is the smallest diff that leaves one owner for
  the logic (the ADR-0124 batch recorded the same principle: fix at the
  shared seam, not per caller).
- **Revisit if:** the two consumers' needs diverge (e.g. transform starts
  needing pyproj-resolved metadata the packer must not depend on).

## 7. Output handling: explicit `--output`, refuse overwrite by default

- **Decision:** no default output filename; existing output fails without
  `--overwrite`.
- **Reasoning:** matches `transform-landxml`'s explicit `--input`/`--output`
  + `overwrite=False` convention; a derived default name is a small
  convenience that buys surprise in scripts.
- **Revisit if:** interactive use dominates and the owner wants a derived
  default.

## 8. `producer.name` is the constant `"AutoGIS"`

- **Decision:** hardcode `"AutoGIS"`, not the distribution name
  (`autogis`) and not a flag.
- **Reasoning:** the field identifies the producing system, not the
  invocation; the consumer repo's own fixtures use `"AutoGIS"`. A flag
  would let callers misattribute packages.
- **Revisit if:** the project is renamed.

## 9. Checksum via the existing `compute_sha256`

- **Decision:** write the re-emitted surface to a temp file, hash it with
  `core/envmon/source_registry.compute_sha256`, then add it to the ZIP.
- **Reasoning:** the repo already has four copies of the same sha256 loop;
  adding a fifth is exactly the drift the canonical helper exists to stop.
  Hashing the file (not an in-memory copy) keeps memory flat for large
  surfaces (contract allows up to 2 GiB).
- **Revisit if:** `compute_sha256`'s home module grows envmon-only imports
  that break the base-install path — then lift the helper into
  `core/common/`, don't copy it.

## 10. ZIP written with `zipfile` + Deflate, entries only

- **Decision:** stdlib `zipfile.ZipFile(..., "w", ZIP_DEFLATED)` writing
  exactly `handoff.json` and `surface.landxml`; no directory entries, no
  extra metadata files.
- **Reasoning:** the contract enumerates the two entries and rejects
  everything else (unexpected entries, directories, encryption,
  non-Stored/Deflated methods are all validator errors). `shutil.
  make_archive` (the existing snapshot pattern) zips directory trees and
  would add directory entries — wrong tool here.
- **Revisit if:** contract v2 changes the package shape.

## Process notes (same session)

- ADR number **0128** was reserved via `coord reserve-adr` from the
  up-to-date worktree after a first reservation (0124) made from a stale
  `main` checkout proved already-taken on `origin/main`; the stale
  reservation is moot (0124 exists on main) and was left to expire.
- The `docs/adr/README.md` index on `main` currently stops at 0125 while
  files exist through 0127 — pre-existing drift, noted in the PR rather
  than fixed in an unrelated branch.
