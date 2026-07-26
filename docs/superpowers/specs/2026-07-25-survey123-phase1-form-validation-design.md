# Survey123 Phase 1 — form validation and schema drift

**Status:** Approved design (user-approved 2026-07-25; adjusted post-#359-merge
to the QAFlags-based SampleID contract)

**Track:** [Survey123 optional add-on roadmap](../../survey123-add-on-roadmap.md)
(ADR-0112), Phase 1 — Form validation and schema drift

## Problem

Nothing in the repository reads an XLSForm back in: `build_xlsform` writes the
workbook, the user opens it in Survey123 Connect, and every downstream tool
consumes submissions, never the form. A hand-edited or regenerated form can
therefore drift — from the configs it was built from, from the SampleID
contract (ADR-0113), or from the feature layer it will one day publish to —
with no detection until field data arrives wrong.

Roadmap Phase 1 wants two headless, base-install commands, before any
publication feature exists:

```text
autogis envmon validate-survey-form
autogis envmon diff-survey-schema
```

**Exit gate:** known-breaking question, repeat, choice, type, and feature-layer
changes are detected from saved artifacts; the commands make no portal changes
and run in the base install.

## Scope

**In:** an XLSForm reader; static validation (structure, names, choice
references, `${ref}` resolution, group/repeat balance, SampleID contract,
config cross-references); form-vs-form drift classification
(safe / review-required / destructive); form-vs-saved-feature-layer-definition
compatibility reusing the `audit_schema` diff engine; two CLI commands.

**Out (deferred):** executing XForm expressions (structural checks only — the
ADR-0113 `ponytail:` ceiling stands); validating `appearance`/`relevant`/
`constraint` semantics (references inside them are resolved when the columns
exist, nothing more); the Phase 0 client-compatibility matrix; anything
touching a portal (Phase 4 owns publishing); form-pack refactors (Phase 6).

## Design

### New module — `autogis/core/envmon/survey_schema.py`

openpyxl + stdlib only (openpyxl is already the headless-tool dependency,
ADR-0021). Imports neither `arcpy` nor `arcgis`.

```python
@dataclass
class SurveyQuestion:
    type: str          # raw, e.g. "select_one well_list", "decimal"
    name: str
    label: str = ""
    hint: str = ""
    required: str = ""
    calculation: str = ""
    appearance: str = ""
    default: str = ""
    row: int = 0       # 1-based sheet row, for findings

@dataclass
class FormSchema:
    questions: list[SurveyQuestion]      # survey sheet, in order
    choices: dict[str, list[tuple[str, str]]]   # list_name -> [(name, label)]
    settings: dict[str, str]

def read_xlsform(path: Path) -> FormSchema
def validate_form(schema, qa, *, event_config=None, site_config=None,
                  analyte_dict=None) -> None      # appends QARecords
def diff_forms(old: FormSchema, new: FormSchema) -> list[SchemaChange]
def form_layer_fields(schema: FormSchema) -> list[dict]   # esri-shaped
def diff_form_vs_layer(schema, layer_spec: dict) -> list[SchemaChange]

@dataclass
class SchemaChange:
    kind: str            # e.g. "question_removed", "type_changed"
    classification: str  # "safe" | "review-required" | "destructive"
    name: str            # question / choice-list / field name
    detail: str          # human sentence with old -> new values

def worst_classification(changes) -> str | None
```

`read_xlsform` maps columns by header row (not position), so the 7- and
8-column header variants both parse; missing optional columns yield `""`.
Structural rows (`begin_group`/`end_group`/`begin_repeat`/`end_repeat`/`note`)
are kept in `questions` (they matter for balance and diff) but excluded from
name-collision and field mapping.

### `validate_form` checks

Severities follow the house QA contract (`_render_qa`, exit 0/1 via
`--fail-on`). ERROR unless noted:

1. Workbook must contain `survey` and `choices` sheets (`settings` optional →
   WARNING if absent).
2. Every non-structural row has a `name`; names match
   `^[A-Za-z_][A-Za-z0-9_]*$`; duplicates (case-insensitive) are errors.
3. `type` is recognized: `text, integer, decimal, date, dateTime, time, note,
   calculate, geopoint, barcode, select_one <list>, select_multiple <list>,
   begin_group, end_group, begin_repeat, end_repeat`. Unknown → ERROR.
4. Every `select_one`/`select_multiple` references a choice list that exists
   and is non-empty; choice rows have valid names; duplicate
   `(list_name, name)` pairs are errors.
5. Every `${ref}` in `calculation` (and in `relevant`/`constraint` when those
   columns exist) resolves to a question name. Order does not matter —
   XLSForm resolves calculates by dependency, and #359 deliberately emits
   SampleID after QAFlags; the validator must not flag backward references.
6. `begin_group`/`end_group` and `begin_repeat`/`end_repeat` balance and nest
   properly.
7. `required` values outside `{"", "yes", "no", "true", "false", "true()",
   "false()"}` (case-insensitive) → WARNING.
8. **SampleID contract (ADR-0113):** a `calculate` named `SampleID` exists
   (ERROR if missing) and its calculation equals
   `sample_id.xform_sample_id_calc()` after whitespace normalization —
   divergence is an **ERROR** (owner decision 2026-07-25; `--fail-on` is the
   escape hatch, not a WARNING severity).
9. **Duplicate-leg dependency:** the choice list read by the SampleID
   calculate's `selected(...)` leg (default `qa_flags`) must contain the
   `field_dup` choice → ERROR if absent, since ADR-0113 routes field
   duplicates through it.
10. `settings`: `form_id` present and slug-shaped, `version` present →
    WARNING otherwise.

Config cross-references, each only when its option is supplied:

11. `--event-config`: form `well_list` choice names vs `location_ids` — a
    planned location missing from the form is an ERROR; an extra form choice
    is a WARNING. Same pattern for `matrix_list` vs `matrices` and
    `crew_list` vs `_slug(member)` of `crew_list`.
12. `--event-config` + `--analyte-dict`: every analyte in `analyte_groups`
    has its `decimal` question (names recomputed via the form builder's
    `_field_name` on the same inputs) → missing is an ERROR; group `decimal`
    questions with no analyte behind them → WARNING.
13. `--site-config` is accepted and currently only feeds identity context in
    messages (`site_id`); site-level checks stay in `validate-config`.

### `diff_forms` taxonomy

Questions match by exact `name` (no rename detection — a rename is a removal
plus an addition, and the removal leg drives the classification). One row per
change kind; `worst_classification` orders destructive > review-required >
safe.

| Change | Classification |
|---|---|
| Question added, not required | safe |
| Question added, required | review-required |
| Question removed (incl. rename) | destructive |
| Question `type` changed | destructive |
| Question moved into/out of a `begin_repeat` scope | destructive |
| `begin_repeat` added or removed | destructive |
| Required: optional → required | review-required |
| Required: required → optional | safe |
| `calculation` changed — question named `SampleID` | destructive |
| `calculation` changed — any other question | review-required |
| `select_*` question re-pointed at a different list | review-required |
| Choice removed from a list | review-required |
| Choice `name` (code) changed | destructive |
| Choice added | safe |
| Choice `label` changed | safe |
| `label` / `hint` / `appearance` / `default` changed | safe |
| Group (non-repeat) membership / group rename | review-required |
| `settings.form_id` changed | destructive |
| `settings.version` / `form_title` / `instance_name` changed | safe |

### `diff_form_vs_layer`

The "saved feature-layer definition" is the existing `audit_schema` local-spec
format (`layer_name` + `fields: [{name, type, nullable, domain:{name,
coded_values}}]`) — the artifact `agol audit-schema` already maintains. No new
format.

`form_layer_fields` maps questions to esri-shaped field dicts:

| XLSForm type | esriFieldType |
|---|---|
| text, calculate, barcode, time | esriFieldTypeString |
| select_one (choices → coded values) | esriFieldTypeString + domain |
| select_multiple | esriFieldTypeString (comma-joined; no domain check) |
| integer | esriFieldTypeInteger |
| decimal | esriFieldTypeDouble |
| date, dateTime | esriFieldTypeDate |
| note, geopoint, begin_/end_ rows | no attribute field |

The form plays the "fetched" side of `audit_schema.diff_schema` against the
saved spec, and the resulting `DriftItem`s classify as:

| DriftItem | Classification |
|---|---|
| TYPE_MISMATCH | destructive |
| EXTRA_FIELD (form question with no layer field) | review-required |
| DOMAIN_DRIFT (choices vs coded values) | review-required |
| NULLABLE_MISMATCH | review-required |
| MISSING_FIELD (layer field the form doesn't collect) | safe |

### CLI

```text
autogis envmon validate-survey-form FORM.xlsx
    [--site-config PATH] [--event-config PATH] [--analyte-dict PATH]
    [--report PATH] [--fail-on error|warning]
```

Standard headless QA idiom (`qa_report_options` + `_render_qa`): exit 0 PASS /
1 FAIL. Lazy core import inside the command body.

```text
autogis envmon diff-survey-schema FORM.xlsx
    [--baseline-form OLD.xlsx] [--layer-spec SPEC.yaml] [--report PATH]
```

At least one of `--baseline-form` / `--layer-spec` is required (both allowed;
findings concatenate). Echoes a classified change table; `--report` writes
`.json` or `.md` by extension. Exit codes follow the semantic-code precedent
(`coc reconcile` 2, `event-status` graded): **0** no changes or safe only,
**2** worst is review-required, **3** worst is destructive, **1** usage/IO
error. A nonzero semantic exit is not a run-history failure.

Registration: both commands in `capabilities.TOOLS` as `Runtime.CLOUD` and in
`_REGISTRY_SEED` (`runtime="CLOUD"`, `status="stable"`, `domain="field"`,
roadmap ids `S123-1.1` / `S123-1.2`). No `--site`/`--event` ADR-0076 stamps:
neither command produces event artifacts that `event-status` tracks (same as
`validate-config`).

## Testing

New `tests/envmon/test_survey_schema.py`, in-memory workbooks via openpyxl:

- reader: header-driven column mapping (7- and 8-column variants), missing
  sheets, structural rows retained.
- one focused test per validate check above, plus the **round-trip
  integration test**: `build_xlsform(SITE, EVENT, ADICT)` output validates
  with **zero findings** against the same configs — this pins the builder and
  validator in lockstep, the Phase 1 analogue of the slice-A agreement test.
- `diff_forms`: one case per taxonomy row (table-driven), plus
  `worst_classification` ordering.
- `diff_form_vs_layer`: small spec dict covering all five DriftItem
  classifications; generated form vs a spec derived from it → no
  destructive/review findings.
- CLI: help registration, PASS/FAIL exits for validate, semantic exits
  0/2/3 for diff (CliRunner + tmp files), `--report` json/md written.

## Migration, rollback, security

Read-only commands over local files; no data written besides reports, no
schema or identity changes, no credentials, no network. Rollback = revert.
Not applicable: migration, PII, audit trail beyond standard run-history.

## Gate mapping

Question/repeat/choice/type changes → `diff_forms` taxonomy rows;
feature-layer changes → `diff_form_vs_layer`; all from saved artifacts
(.xlsx, .yaml), no portal access, base install (openpyxl only). Meeting the
gate closes Phase 1; Phase 2 (live sync) remains separately user-gated.

## Decision record

Two new CLI commands and a tool-batch scope addition → ADR required. Number
chosen at authoring time vs `origin/main` + all open PRs (0114 expected free
after ADR-0113 merged in #359; re-verify then).
