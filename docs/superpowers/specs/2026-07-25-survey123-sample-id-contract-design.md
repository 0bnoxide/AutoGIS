# Survey123 Phase 0, Slice A — SampleID contract

**Status:** Approved design

**Approved:** 2026-07-25

**Track:** [Survey123 optional add-on roadmap](../../survey123-add-on-roadmap.md),
Phase 0 — Client and submission contract (first slice)

## Problem

The Survey123 add-on roadmap describes Phase 0 as pinning "the existing SampleID
calculation shared by event planning, XLSForm generation, normalization, and
reconciliation."

A survey of the codebase found that premise is inaccurate in two ways, and that
the gap has already produced a live data-correctness defect.

### Nothing is shared

Five sites construct a SampleID, each with its own literal:

| Site | Format |
|---|---|
| `create_sampling_event.py:81-84` | `{loc}-{YYYYMMDD}-{matrix}` / `…-FD` |
| `survey123_form_builder.py:98-101` | XForm `concat(${WellID},"-",…,"-",${Matrix})` |
| `normalize_survey123.py:44-47` | `{well}-{YYYYMMDD}-{matrix}` / `…-NODATE-{uuid6}-{matrix}` |
| `sampling_plan.py:139` | `{site}-{loc}-{event}-{group}` |
| `legacy_migrator.py:146` | `{loc}_{date_raw}_{row_idx}` |

The first three are three renderings of one intended identity. The last two are
different things that happen to land in the same column, and are addressed
separately below.

### Defect 1 — a planned field duplicate can never be produced

`create_sampling_event.py:84` plans duplicates as `MW-1-20260715-GW-FD`, and
`qc_sample_summary.py:24-30` knows how to read a `-fd` suffix. But the generated
XLSForm has no duplicate input and its SampleID calculate cannot emit the
suffix, and `normalize_survey123._build_sample_id` has no `is_dup` parameter.
The planner-to-parser contract is unreachable from the field.

### Defect 2 — a duplicate is silently consumed as its own primary

`reconcile_field_lab` falls back to `difflib.SequenceMatcher` with a `0.85`
default threshold (`cli.py:3843`). For `MW-1-20260715-GW` against
`MW-1-20260715-GW-FD` the ratio is `2*16/(16+19) ≈ 0.914`, above the threshold.
The duplicate is removed from `unmatched_lab` and paired with the primary at
`reconcile_survey123_lab.py:93-97`, emitting only a `sample_id_mismatch` warning.
A field duplicate therefore consumes its own primary's laboratory record.

### Why the test suite does not catch either

- The normalizer's happy-path SampleID string is never asserted. Only the
  `NODATE` branch is pinned (`test_normalize_survey123.py:86-100`). The primary
  format can change without failing the suite.
- The XLSForm calculate is only substring-checked for `${WellID}`,
  `${SamplingDate}`, `${Matrix}` (`test_survey123_form_builder.py:63-73`), never
  compared to the planner's format.
- `_infer_qc_type`'s `-fd` path has no test at all.
- No test asserts any two producers agree with each other.

## Scope

This slice covers the lifecycle sample identity only. It is deliberately
narrower than Phase 0 as written in the roadmap.

**In scope:** one owner for the lifecycle SampleID, its QC suffixes, and its
XLSForm expression; the five call sites that consume it; the two defects above;
the cross-module agreement tests that do not exist today.

**Out of scope, deferred to Phase 2 and Phase 5:** the remaining canonical
envelope fields — survey/item/layer identity, GlobalID, edit time, operation
type, repeat path, attachment metadata, raw-payload hash. None of these has a
consumer until the live synchronization reader (Phase 2) or the webhook
processor (Phase 5) exists. Building them now would be scaffolding for callers
that do not exist.

**Also out of scope:** XLSForm repeat-group support (none exists anywhere in the
repository); the `route-survey123` arcpy coupling in `cli.py:3876-3905`, which is
a real finding but a separate concern from this contract.

## Design

### New module — `autogis/core/envmon/sample_id.py`

Standard library only. Imports neither `arcpy` nor `arcgis`, consistent with the
`core/` invariant.

Public surface:

```python
LIFECYCLE_FORMAT: str          # "{location}-{YYYYMMDD}-{matrix}[-{qc}]"
QC_SUFFIXES: dict[str, str]    # suffix -> qc_type, relocated from qc_sample_summary

@dataclass(frozen=True)
class SampleIdParts:
    location_id: str
    date_compact: str          # "YYYYMMDD", or "" when the NODATE form was used
    matrix: str
    qc: str                    # "" for a primary sample, e.g. "FD" otherwise

def build_sample_id(location_id, date, matrix, qc=None) -> str
def parse_sample_id(sample_id: str) -> SampleIdParts | None
def xform_sample_id_calc(
    well_field="WellID", date_field="SamplingDate",
    matrix_field="Matrix", dup_field="IsFieldDup",
) -> str
```

`date` accepts a `datetime` or a compact `YYYYMMDD` string. When it is `None`,
`build_sample_id` produces the existing `{loc}-NODATE-{uuid6}-{matrix}` form,
relocated unchanged from `normalize_survey123.py:46` — that behavior is pinned by
an existing test and is correct for dateless submissions.

The `qc` argument is a bare code without a separator, in the case the identity
carries — `"FD"`, not `"-fd"`. `QC_SUFFIXES` keeps its existing lowercase
dash-prefixed keys so that `qc_sample_summary._infer_qc_type` continues to work
unchanged against lowercased identities; `build_sample_id` and `parse_sample_id`
own the conversion between the two spellings so no caller does it by hand.

`parse_sample_id` returns `None` rather than raising or guessing when the input
does not fit the lifecycle format. This is what makes the function safe to point
at the shared `SampleID` column: `sampling_plan` and `legacy_migrator` identities
simply do not parse, and every caller reads "unparseable" as "not a lifecycle
identity."

The `NODATE` form **does** parse, yielding `date_compact == ""` with
`location_id`, `matrix`, and `qc` populated. Reconciliation's structural guard
therefore still applies to dateless submissions, which is the case where a
similarity score is least trustworthy.

`xform_sample_id_calc` takes the survey field names as parameters so the
expression and the Python builder derive from one format constant. Their
defaults are the literals the form builder uses today. Consolidating the wider
field-name duplication — the form builder's literals against
`normalize_survey123.Survey123Field` and `reconcile_survey123_lab.DEFAULT_HEADER_MAP`
— is **not** in this slice; only the fields the identity itself depends on are
threaded through.

### The XForm boundary and its ceiling

The XLSForm SampleID is an XForm expression string evaluated on the device by
Survey123, not Python. A single shared function cannot literally span that
boundary. Instead, one module emits both renderings from one format constant,
and a test pins that they stay in lockstep by asserting the generated expression
references exactly the expected fields in the expected separator order.

No test can execute the XForm side. This residual gap is marked in the source
with a `ponytail:` comment naming the ceiling and the upgrade path (a real XForm
expression evaluator, warranted only if a second divergence ever appears).

### Call-site changes

| File | Change |
|---|---|
| `create_sampling_event.py:81-84` | delete `_sample_id`; call `build_sample_id(..., qc="FD" if is_dup else None)` |
| `survey123_form_builder.py:98-101` | replace the literal calculate with `xform_sample_id_calc()`; add the `IsFieldDup` question and a `yes_no` choices list |
| `normalize_survey123.py:44-47` | delete `_build_sample_id`; add `Survey123Field.is_field_dup_field`; pass `qc` through |
| `reconcile_survey123_lab.py:88-97` | structural guard ahead of `difflib` |
| `qc_sample_summary.py:24-30` | import `QC_SUFFIXES` instead of defining `_SUFFIX_MAP` |

`sampling_plan.py` and `legacy_migrator.py` are not changed. Each receives a
one-line comment recording that it writes a non-lifecycle identity into the
shared `SampleID` column. Forcing them onto the lifecycle format was considered
and rejected: `sampling_plan` identities are per analyte group, a different
granularity, and `legacy_migrator` only invents an identity when the historical
source has none (`if not sample_id:`), so rewriting it would alter migrated
records.

### Form change

One `select_one yes_no` question, `IsFieldDup`, labelled "Field duplicate?",
defaulting to no, plus a `yes_no` list on the choices sheet. The SampleID
calculate appends `-FD` when the answer is yes.

This matches exactly what `create_sampling_event` plans today and adds nothing
more. A full QC-type picker covering field, trip, and equipment blanks was
considered and rejected: no planner produces those, so three of five choices
would have no upstream producer. The suffix map still parses them if a
laboratory EDD carries them.

### Reconciliation fix

The guard is structural and runs before any similarity scoring: if both
identities parse and their `qc` components differ, they cannot match, and no
score gets a vote. The duplicate falls to `field_only`, which is correct.

The `0.85` threshold is not changed. Raising it would relocate the collision
rather than close it, and would weaken legitimate fuzzy matching elsewhere.

## Testing

New file `tests/envmon/test_sample_id.py`:

- build/parse round-trip across matrices and QC suffixes
- every entry in `QC_SUFFIXES` parses to its declared type
- the `NODATE` branch produces the pinned shape and unique values
- non-lifecycle identities — `sampling_plan` and `legacy_migrator` forms —
  return `None` from `parse_sample_id`
- the generated XForm expression references the expected fields in the expected
  order

Added to existing files:

- **cross-module agreement:** planner output and normalizer output are identical
  for identical inputs, including the `-FD` case. This test does not exist today
  in any form and is the primary regression guard for this contract.
- normalizer happy-path SampleID string asserted, closing the gap that lets the
  primary format change silently.
- `-FD` reconciliation regression: a duplicate and its primary must not match.
- `qc_sample_summary._infer_qc_type("MW-1-20260715-GW-FD", "")` returns
  `field_duplicate`, closing the parser end of the producer/parser contract.

## Migration, rollback, and data implications

- **Data written:** no change to any existing identity for a primary sample. The
  lifecycle format is unchanged; it is only relocated to one owner.
- **New values:** identities ending `-FD` become producible from the field for
  the first time. They are new values in an existing `TEXT(64)` column and
  require no schema change.
- **Existing records:** untouched. No migration is required.
- **Rollback:** reverting the commit restores the previous literals. Any `-FD`
  identity already written remains valid and parseable by `qc_sample_summary`,
  which recognised the suffix before this change.
- **Forms in the field:** a form generated before this change has no
  `IsFieldDup` question. Normalization treats a missing field as "not a
  duplicate", so older submissions normalize exactly as they do today.
- **Security and PII:** not applicable. No credentials, no network access, no new
  personal data.

## Gate mapping

This slice addresses the Phase 0 exit gate's SampleID leg — "the SampleID
contract is identical across all existing producers and consumers" — for the
three lifecycle producers, and documents why the two non-lifecycle producers are
excluded. The envelope leg of the Phase 0 gate is explicitly not met by this
slice and remains open for the Phase 2 work that will consume it.

## Decision record

This changes a data contract on shipped, data-bearing commands and therefore
requires an ADR. The number is chosen at authoring time against `origin/main`
and every open pull request, since 0112 is taken by PR #335 and concurrent
sessions have collided on ADR numbers before.
