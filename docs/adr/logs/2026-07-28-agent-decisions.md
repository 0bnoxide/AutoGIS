# Agent decisions — 2026-07-28

## CRS axes, not caller labels, own horizontal units

- **Decision:** `transform-landxml` infers horizontal units from the source and
  target CRS. The old unit parameters remain optional assertions for backward
  compatibility, but are hidden from the Click-generated GUI.
- **Reasoning:** EPSG:2256 is defined in international feet. Letting a caller
  request `USSurveyFoot` for that CRS makes coordinates and LandXML metadata
  disagree; rejecting the label without projecting also prevents the legitimate
  ESRI:102700-to-EPSG:2256 conversion.
- **Revisit if:** the LandXML writer gains a non-EPSG machine-readable output
  CRS contract.

## Geographic transformation selection follows the surface extent

- **Decision:** Parse the selected TIN first, derive a geographic area of
  interest, and use pyproj's ranked non-ballpark operations. Accept an exact
  operation name or authority-code override and fail if it is unavailable.
- **Reasoning:** ArcGIS Project exposes a geographic transformation choice, and
  a global default can rank a less accurate operation ahead of the relevant
  local one. For the Montana example, the extent selects ESRI:108190 at
  0.1-metre stated accuracy ahead of the generic 4-metre EPSG fallback.
- **Revisit if:** users need a configurable accuracy ceiling or controlled grid
  acquisition policy.

## A custom Z multiplier replaces unit conversion

- **Decision:** A positive finite `z_scale` is the complete elevation
  multiplier and cannot be combined with `source_z_unit`. Without it, exact
  meter/international-foot/US-survey-foot ratios apply automatically.
- **Reasoning:** Values such as `3.28` and `0.03` are intentional project
  corrections, not reliably inferable units. Replacement semantics prevent
  accidental double scaling and keep the reported factor auditable.
- **Revisit if:** a later vertical-CRS slice introduces datum/geoid operations;
  linear scaling must remain a distinct step.
