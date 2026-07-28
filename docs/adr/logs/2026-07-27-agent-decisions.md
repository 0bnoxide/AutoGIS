# Agent decisions — 2026-07-27

## LandXML transformation scope: selected TIN surface, not opaque XML rewrite

- **Decision:** The LandXML-to-LandXML tool writes one normalized, explicitly
  selected TIN surface and preserves its point IDs, face topology, and name. It
  does not copy unrelated alignments, parcels, breaklines, styles, or vendor
  extensions.
- **Reasoning:** Coordinates inside those objects have different schemas and
  transformation rules; copying them unchanged would produce a document whose
  metadata says it was transformed while some geometry was not. The requested
  CAD workflow is the surface handoff, and a selected-surface contract is the
  smallest safe complete operation.
- **Revisit if:** a concrete CAD exchange requires additional named LandXML
  object types and supplies representative files plus preservation acceptance
  tests.

## Mixed-unit elevations are explicit; vertical datum changes are separate

- **Decision:** Added optional `source_z_unit` so a feet-based projected
  surface with meter elevations (or the reverse) can be normalized into the
  target LandXML unit. The tool does not perform vertical datum/geoid
  transformations.
- **Reasoning:** Existing DEM and Pro-TIN workflows distinguish horizontal CRS
  projection from cell/elevation-value scaling. Reusing that explicit direction
  prevents guessing, while vertical datum conversion needs separate CRS,
  transformation-grid, accuracy, and provenance decisions.
- **Revisit if:** users need NAVD88/NGVD29/ellipsoidal-height conversion rather
  than only meter/foot scaling.

## Fail closed on source metadata and low-confidence transforms

- **Decision:** Declared source CRS/unit mismatches block conversion unless the
  caller opts into an override, CRS axis units must match the selected
  LandXML units, malformed TIN topology is rejected, and pyproj ballpark
  transformations are disabled.
- **Reasoning:** The CAD output can look plausible despite a wrong foot or
  assumed datum. Explicit overrides preserve a recovery path for bad legacy
  metadata without silently accepting it.
- **Revisit if:** an audited workflow needs a configurable transform-accuracy
  policy or a named coordinate operation rather than the best available
  non-ballpark PROJ operation.
