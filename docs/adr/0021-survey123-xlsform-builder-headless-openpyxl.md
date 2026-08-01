# ADR-0021: BuildSurvey123XLSFormFromConfig — headless openpyxl tool with event_config.yaml

**Status:** Accepted

**Date:** 2026-06-26

## Context

Tool 7.1a (`BuildSurvey123XLSFormFromConfig`) generates an XLSForm XLSX file for
Survey123 from site and event configuration. XLSForm is the standard three-sheet
format (survey / choices / settings) consumed by ArcGIS Survey123 Connect.

Key questions resolved in design:
1. Does this tool require arcpy / ArcGIS Pro at build time?
2. How should per-event parameters (analyte groups, crew list, COC prefix) be supplied?
3. How should analyte field labels and units be populated?

No Survey123 or XLSForm code existed in the codebase prior to this decision.
`load_config` (in `autogis/core/common/config.py`) returns a raw dict with no schema
enforcement — callers do their own key extraction.

## Decision

### Headless tool (no arcpy at build time)

`BuildSurvey123XLSFormFromConfig` is a headless tool (same category as Tools 1, 9, 10).
It produces a file artifact (`.xlsx`) that is then opened in Survey123 Connect by the
user. No ArcGIS Pro session is required at generation time.

Implementation: `autogis/core/envmon/survey123_form_builder.py` — no arcpy imports.
openpyxl (already a project dependency per ADR-008) writes the output workbook.

### Event config YAML for per-event parameters

Site config (`H281_Glasgow.yaml`) provides: well list (as feature class names), site
metadata, map units. It does not describe per-event sampling specifics.

A new `event_config.yaml` schema captures per-event parameters:
- `analyte_groups: dict[str, list[str]]` — group name → canonical analyte names
- `crew_list: list[str]`
- `coc_prefix: str`
- `matrices: list[str]` — which matrices are sampled this event

One example file is committed at `autogis/config/event_configs/event_config.example.yaml`.
Per-site, per-event configs live alongside site config YAMLs.

### Analyte labels and units from the analyte dictionary

`build_xlsform` accepts the loaded analyte dictionary dict. Field labels in the
`survey` sheet are composed as `"{abbreviation} ({default_units_by_matrix[matrix]})"`.
This keeps labels in sync with the dictionary without hardcoding units per form.

### Survey sheet structure

Questions in order: WellID (select_one), SamplingDate (date), Matrix (select_one),
SampleID (calculate from WellID+date+matrix), SampledBy (select_one), COCNumber
(text), one begin_group per analyte group with one decimal field per analyte,
DepthToWater_ft (decimal, GW hint), QAFlags (select_multiple), Notes (text).

SampleID calculate expression: `concat(${WellID}, "-", format-date(${SamplingDate},
"%Y%m%d"), "-", ${Matrix})`.

> **Amended by ADR-0113 (2026-07-25) and issue #361 (2026-07-30):** the
> calculate appends one of two distinct field-duplicate suffixes:
> `if(selected(${QAFlags}, "field_dup_a"), "-FD-A",
> if(selected(${QAFlags}, "field_dup_b"), "-FD-B", ""))`. It is emitted by
> `core/envmon/sample_id.xform_sample_id_calc()` rather than written inline
> here. The question list above is unchanged: both choices live in the existing
> `QAFlags` question. Selecting both is rejected during normalization. The
> normalizer retains the former `field_dup` → `-FD` mapping only for submissions
> from forms generated before this amendment.

### CLI

```
autogis envmon build-survey-form \
  --site <site.yaml> \
  --analytes <analyte_dictionary.yaml> \
  --event <event_config.yaml> \
  --out <output.xlsx>
```

## Consequences

### Positive consequences

- No ArcGIS Pro license required to generate forms — usable on any machine with Python
- openpyxl is already a dependency (ADR-008); no new package added
- event_config.yaml is version-controllable alongside site config
- Analyte labels derive from the dictionary — single source of truth for abbreviations
  and units
- Fully arcpy-free and unit-testable

### Negative consequences

- event_config.yaml is a new config schema to document and maintain
- The SampleID calculate expression uses Survey123 / XLSForm syntax; if Survey123
  changes its expression language, the generated form must be regenerated
- Well list comes from site config (feature class names), not a live GDB query —
  the form won't reflect wells added after the site config was last updated

## Alternatives considered

1. **arcpy tool that queries the GDB for wells at runtime:** Would require ArcGIS Pro
   to generate the form, defeating the headless use case (field crew laptop without
   Pro). Rejected.

2. **Inline analyte groups in site config:** Mixes per-site permanent config with
   per-event variable config. Different events sample different analyte groups.
   Rejected in favor of a separate event_config.yaml.

3. **Use ArcGIS Survey123 Python API to publish directly:** Requires AGOL credentials
   and network access at generation time. Out of scope for this tool; that is Tool 7.1b
   (`RouteSurvey123Submission`). Rejected.

## Related decisions

- [ADR-002: Arcpy-free core invariant](0002-arcpy-free-core-invariant.md) —
  survey123_form_builder.py upholds this invariant; no arcpy imports
- [ADR-008: Openpyxl as base dependency](0008-openpyxl-base-dependency.md) —
  this tool relies on that decision; no new dependency added
- [ADR-009: Config dataclass style](0009-config-dataclass-style.md) —
  Survey123FormConfig follows the same dataclass pattern
