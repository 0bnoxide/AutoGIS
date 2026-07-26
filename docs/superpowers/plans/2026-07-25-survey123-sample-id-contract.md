# Survey123 SampleID Contract (Phase 0 Slice A) Implementation Plan

> **SUPERSEDED IN PART — this is the plan as approved, kept as a record; it is
> not a description of what shipped.** Code review during PR #359 rejected the
> `IsFieldDup` `select_one yes_no` question this plan specifies (Task 3, and its
> references in Tasks 2/4 and the `dup_field` parameter). It duplicated the
> `QAFlags` choice `field_dup` that ADR-0021 already provided, and two
> affordances for one fact let a crew tick the labelled one and silently emit a
> SampleID identical to the primary. What shipped: no new question, no `yes_no`
> list, and the duplicate leg reads `selected(${QAFlags}, "field_dup")`. The
> shipped design also adds `strip_qc` / `qc_class`, populates the duplicate
> metadata RPD pairing reads, and extends the reconcile guard to profile
> duplicate markers. **ADR-0113 is authoritative.**

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One owner module for the lifecycle SampleID (`{location}-{YYYYMMDD}-{matrix}[-{qc}]`), consumed by all five call sites, fixing the unproducible field-duplicate defect and the fuzzy-match duplicate-consumes-primary defect.

**Architecture:** New stdlib-only `autogis/core/envmon/sample_id.py` exposes `build_sample_id` / `parse_sample_id` / `xform_sample_id_calc` / `QC_SUFFIXES`. The three lifecycle producers (planner, form builder, normalizer) switch to it; reconciliation gains a structural QC guard ahead of `difflib`; `qc_sample_summary` imports the suffix map instead of defining it. `sampling_plan` and `legacy_migrator` are documented as non-lifecycle and unchanged.

**Tech Stack:** Python stdlib only in the new module; pytest; openpyxl already present in form-builder tests.

**Spec:** `docs/superpowers/specs/2026-07-25-survey123-sample-id-contract-design.md` (approved 2026-07-25).

## Global Constraints

- `core/` imports with neither `arcpy` nor `arcgis` present; `sample_id.py` is stdlib only.
- `main` is READ-ONLY — all work on branch `worktree-survey123-sampleid-impl` in this worktree.
- Data contract change on shipped commands → ADR required. Number chosen at write time against `origin/main` + all open PRs; reserve via `python .claude/coordination/coord_cli.py reserve-adr` (0113 free as of plan time).
- No new dependencies.
- NODATE behavior (`{loc}-NODATE-{uuid6}-{matrix}`) relocates unchanged — pinned by existing `test_missing_or_invalid_date_emits_error_and_unique_nodate_sample_id`.
- The fuzzy threshold `0.85` is NOT changed.
- Run tests from the worktree root: `PYTHONPATH="$PWD" python -m pytest -q tests/...` (editable-install trap: without PYTHONPATH the installed copy, not this worktree, is imported).
- Do not self-merge the PR (user sign-off rule).

---

### Task 1: `sample_id.py` module + contract tests

**Files:**
- Create: `autogis/core/envmon/sample_id.py`
- Test: `tests/envmon/test_sample_id.py` (new)

**Interfaces:**
- Produces (later tasks import these — exact signatures):
  - `LIFECYCLE_FORMAT: str`
  - `QC_SUFFIXES: dict[str, str]` — lowercase dash-prefixed keys, same content as today's `qc_sample_summary._SUFFIX_MAP`
  - `@dataclass(frozen=True) SampleIdParts(location_id: str, date_compact: str, matrix: str, qc: str)`
  - `build_sample_id(location_id: str, date: datetime | str | None, matrix: str, qc: str | None = None) -> str`
  - `parse_sample_id(sample_id: str) -> SampleIdParts | None`
  - `xform_sample_id_calc(well_field="WellID", date_field="SamplingDate", matrix_field="Matrix", dup_field="IsFieldDup") -> str`

- [ ] **Step 1: Write the failing tests** — `tests/envmon/test_sample_id.py`:

```python
"""Contract tests for the lifecycle SampleID single owner (sample_id.py)."""
import re
from datetime import datetime

import pytest

from autogis.core.envmon.sample_id import (
    QC_SUFFIXES, SampleIdParts, build_sample_id, parse_sample_id,
    xform_sample_id_calc,
)


def test_build_primary_from_datetime_and_compact_string_agree():
    dt = datetime(2026, 7, 15)
    assert build_sample_id("MW-1", dt, "GW") == "MW-1-20260715-GW"
    assert build_sample_id("MW-1", "20260715", "GW") == "MW-1-20260715-GW"


def test_build_rejects_non_compact_date_string():
    with pytest.raises(ValueError):
        build_sample_id("MW-1", "2026-07-15", "GW")


def test_build_parse_round_trip_across_matrices_and_qc():
    for matrix in ("GW", "SOIL", "SW", "SEDIMENT"):
        for suffix in QC_SUFFIXES:
            qc = suffix[1:].upper()
            sid = build_sample_id("MW-1", "20260715", matrix, qc=qc)
            assert parse_sample_id(sid) == SampleIdParts(
                "MW-1", "20260715", matrix, qc)


def test_every_qc_suffix_parses_to_its_declared_type():
    from autogis.core.envmon.qc_sample_summary import _infer_qc_type
    for suffix, qtype in QC_SUFFIXES.items():
        sid = build_sample_id("MW-1", "20260715", "GW", qc=suffix[1:].upper())
        assert _infer_qc_type(sid, "") == qtype


def test_nodate_form_shape_and_uniqueness():
    a = build_sample_id("MW-01", None, "GW")
    b = build_sample_id("MW-01", None, "GW")
    assert re.fullmatch(r"MW-01-NODATE-[0-9A-F]{6}-GW", a)
    assert a != b


def test_nodate_parses_with_empty_date_and_qc_populated():
    sid = build_sample_id("MW-01", None, "GW", qc="FD")
    parts = parse_sample_id(sid)
    assert parts is not None
    assert parts.date_compact == ""
    assert parts.matrix == "GW"
    assert parts.qc == "FD"


def test_primary_parse_has_empty_qc():
    assert parse_sample_id("MW-1-20260715-GW").qc == ""


def test_non_lifecycle_identities_return_none():
    # sampling_plan form: {site}-{loc}-{event}-{group}
    assert parse_sample_id("H281-MW-1-2026Q3-VOCs") is None
    # legacy_migrator form: {loc}_{date_raw}_{row_idx}
    assert parse_sample_id("MW-1_2026-07-15_3") is None
    assert parse_sample_id("") is None


def test_xform_calc_matches_lifecycle_field_order():
    calc = xform_sample_id_calc()
    assert calc == (
        'concat(${WellID}, "-", '
        'format-date(${SamplingDate}, "%Y%m%d"), '
        '"-", ${Matrix}, '
        'if(selected(${IsFieldDup}, "yes"), "-FD", ""))'
    )
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH="$PWD" python -m pytest tests/envmon/test_sample_id.py -q`
Expected: FAIL — `ModuleNotFoundError: autogis.core.envmon.sample_id`

- [ ] **Step 3: Implement `autogis/core/envmon/sample_id.py`**

```python
"""sample_id.py — single owner of the lifecycle SampleID contract.

The lifecycle identity {location}-{YYYYMMDD}-{matrix}[-{qc}] is shared by
event planning (create_sampling_event), XLSForm generation
(survey123_form_builder), submission normalization (normalize_survey123),
reconciliation (reconcile_survey123_lab), and QC classification
(qc_sample_summary). Stdlib only — no arcpy, no arcgis, no openpyxl.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Union

#: The one lifecycle format. build_sample_id (Python) and
#: xform_sample_id_calc (XForm) are its two renderings; the structure test
#: in tests/envmon/test_sample_id.py pins them in lockstep.
LIFECYCLE_FORMAT = "{location}-{YYYYMMDD}-{matrix}[-{qc}]"

#: suffix -> qc_type. Keys stay lowercase and dash-prefixed because
#: qc_sample_summary._infer_qc_type matches them against lowercased IDs.
QC_SUFFIXES = {
    "-mb": "method_blank", "-fb": "field_blank", "-tb": "trip_blank",
    "-ms": "matrix_spike", "-msd": "matrix_spike_duplicate",
    "-ld": "lab_duplicate", "-fd": "field_duplicate",
    "-ld-a": "lab_duplicate", "-ld-b": "lab_duplicate",
    "-fd-a": "field_duplicate", "-fd-b": "field_duplicate",
}


@dataclass(frozen=True)
class SampleIdParts:
    location_id: str
    date_compact: str   # "YYYYMMDD", or "" when the NODATE form was used
    matrix: str
    qc: str             # "" for a primary sample, e.g. "FD" otherwise


def build_sample_id(location_id: str, date: Union[datetime, str, None],
                    matrix: str, qc: Optional[str] = None) -> str:
    """Render the lifecycle SampleID.

    date: a datetime/date, a compact "YYYYMMDD" string, or None for a
    dateless submission (produces the NODATE form with a uuid6 disambiguator).
    qc: bare code without separator ("FD", not "-fd").
    """
    if date is None:
        base = f"{location_id}-NODATE-{uuid.uuid4().hex[:6].upper()}-{matrix}"
    else:
        if hasattr(date, "strftime"):
            date_compact = date.strftime("%Y%m%d")
        else:
            date_compact = str(date).strip()
            if not re.fullmatch(r"\d{8}", date_compact):
                raise ValueError(
                    f"date must be a datetime or YYYYMMDD string, got {date!r}")
        base = f"{location_id}-{date_compact}-{matrix}"
    return f"{base}-{qc.upper()}" if qc else base


_DATED_RE = re.compile(r"^(?P<loc>.+)-(?P<date>\d{8})-(?P<rest>.+)$")
_NODATE_RE = re.compile(
    r"^(?P<loc>.+)-NODATE-[0-9A-Fa-f]{6}-(?P<rest>.+)$", re.IGNORECASE)


def parse_sample_id(sample_id: str) -> Optional[SampleIdParts]:
    """Parse a lifecycle SampleID; None when the input is not one.

    sampling_plan ({site}-{loc}-{event}-{group}) and legacy_migrator
    ({loc}_{date}_{idx}) identities share the SampleID column but are not
    lifecycle identities — they return None, and every caller reads
    "unparseable" as "not a lifecycle identity", never as an error.
    """
    if not sample_id:
        return None
    m = _DATED_RE.match(sample_id)
    date_compact = m.group("date") if m else ""
    if not m:
        m = _NODATE_RE.match(sample_id)
    if not m:
        return None
    rest = m.group("rest")
    qc = ""
    rest_lower = rest.lower()
    for suffix in sorted(QC_SUFFIXES, key=len, reverse=True):
        if rest_lower.endswith(suffix) and len(rest) > len(suffix):
            qc = rest[-len(suffix) + 1:].upper()
            rest = rest[:-len(suffix)]
            break
    if not rest or "-" in rest:
        return None
    return SampleIdParts(location_id=m.group("loc"),
                         date_compact=date_compact, matrix=rest, qc=qc)


def xform_sample_id_calc(well_field: str = "WellID",
                         date_field: str = "SamplingDate",
                         matrix_field: str = "Matrix",
                         dup_field: str = "IsFieldDup") -> str:
    """XForm calculate for the SampleID question — the device-side rendering
    of LIFECYCLE_FORMAT. Defaults are the survey field names the form
    builder emits today.

    ponytail: no test can execute the XForm side, so the two renderings are
    pinned in lockstep only by the structure test; upgrade path is a real
    XForm expression evaluator if a second divergence ever appears.
    """
    return (
        f'concat(${{{well_field}}}, "-", '
        f'format-date(${{{date_field}}}, "%Y%m%d"), '
        f'"-", ${{{matrix_field}}}, '
        f'if(selected(${{{dup_field}}}, "yes"), "-FD", ""))'
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONPATH="$PWD" python -m pytest tests/envmon/test_sample_id.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add autogis/core/envmon/sample_id.py tests/envmon/test_sample_id.py
git commit -m "feat(envmon): single-owner lifecycle SampleID contract module"
```

---

### Task 2: Planner switches to the shared builder

**Files:**
- Modify: `autogis/core/envmon/create_sampling_event.py:81-84` (delete `_sample_id`), `:200`, `:219` (call sites)
- Test: existing `tests/envmon/test_create_sampling_event.py` (no edits — `test_sample_id_format_primary` / `test_sample_id_format_field_dup` already pin `MW-1-20260715-GW[-FD]`)

**Interfaces:**
- Consumes: `build_sample_id(location_id, date_compact_str, matrix, qc=None)` from Task 1.

- [ ] **Step 1: Replace the private helper.** Delete `_sample_id` (lines 81-84) and add to the imports at the top of the file:

```python
from .sample_id import build_sample_id
```

Change line 200 area:

```python
                sample_id=build_sample_id(location_id, date_compact,
                                          primary_matrix),
```

Change line 219 area (field duplicate):

```python
                    sample_id=build_sample_id(location_id, date_compact,
                                              primary_matrix, qc="FD"),
```

- [ ] **Step 2: Run the planner tests**

Run: `PYTHONPATH="$PWD" python -m pytest tests/envmon/test_create_sampling_event.py -q`
Expected: all PASS (IDs byte-identical to before)

- [ ] **Step 3: Commit**

```bash
git add autogis/core/envmon/create_sampling_event.py
git commit -m "refactor(envmon): planner uses shared build_sample_id"
```

---

### Task 3: Form builder — shared calculate + IsFieldDup question

**Files:**
- Modify: `autogis/core/envmon/survey123_form_builder.py` (`_SURVEY_HEADERS` line 30, calc literal lines 98-101, question rows ~103-108, choices section ~129+)
- Test: `tests/envmon/test_survey123_form_builder.py` (update `test_sample_id_has_calculate_type`, add two tests)

**Interfaces:**
- Consumes: `xform_sample_id_calc()` from Task 1.
- Produces: survey question `IsFieldDup` (`select_one yes_no`, default `no`); choices list `yes_no` with `yes`/`no`. Task 4's normalizer reads the `IsFieldDup` answer by this exact name.

- [ ] **Step 1: Write the failing tests.** In `tests/envmon/test_survey123_form_builder.py`, extend the existing calc test's assertions and add:

```python
def test_sample_id_calc_comes_from_shared_contract(wb):
    from autogis.core.envmon.sample_id import xform_sample_id_calc
    ws = wb["survey"]
    for r in range(2, ws.max_row + 1):
        if ws.cell(r, 2).value == "SampleID":
            assert ws.cell(r, 6).value == xform_sample_id_calc()
            return
    pytest.fail("SampleID row not found")


def test_is_field_dup_question_and_choices(wb):
    ws = wb["survey"]
    rows = {ws.cell(r, 2).value: ws.cell(r, 1).value
            for r in range(2, ws.max_row + 1)}
    assert rows.get("IsFieldDup") == "select_one yes_no"
    choices = wb["choices"]
    pairs = {(choices.cell(r, 1).value, choices.cell(r, 2).value)
             for r in range(2, choices.max_row + 1)}
    assert ("yes_no", "yes") in pairs
    assert ("yes_no", "no") in pairs
```

In `test_sample_id_has_calculate_type`, add `assert "${IsFieldDup}" in calc` beside the three existing `${...}` asserts.

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH="$PWD" python -m pytest tests/envmon/test_survey123_form_builder.py -q`
Expected: the two new tests + updated one FAIL

- [ ] **Step 3: Implement.** In `survey123_form_builder.py`:

Import: `from .sample_id import xform_sample_id_calc`

`_SURVEY_HEADERS` gains a `default` column:

```python
_SURVEY_HEADERS = ["type", "name", "label", "hint", "required", "calculation",
                   "appearance", "default"]
```

Replace lines 98-101 with:

```python
    sample_id_calc = xform_sample_id_calc()
```

Insert the duplicate question between the `Matrix` row and the `SampleID` calculate row (row signature is `row(type, name, label, hint, required, calculation, appearance, default)`; shorter rows leave trailing columns empty):

```python
    row("select_one matrix_list", "Matrix", "Sample Matrix", "", "yes")
    row("select_one yes_no", "IsFieldDup", "Field duplicate?",
        "", "", "", "", "no")
    row("calculate", "SampleID", "", "", "", sample_id_calc)
```

In the choices section, after the existing loops, add:

```python
    crow("yes_no", "yes", "Yes")
    crow("yes_no", "no", "No")
```

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONPATH="$PWD" python -m pytest tests/envmon/test_survey123_form_builder.py -q`
Expected: all PASS

- [ ] **Step 5: Check user docs for a stale question list**

Run: `grep -rn "COCNumber\|IsFieldDup\|SampleID" docs/ --include="*.md" -l`
If a build-survey-form user doc enumerates the survey questions, add `IsFieldDup` there in the same style. If none does, no doc change.

- [ ] **Step 6: Commit**

```bash
git add autogis/core/envmon/survey123_form_builder.py tests/envmon/test_survey123_form_builder.py docs/
git commit -m "feat(envmon): XLSForm IsFieldDup question + shared SampleID calculate"
```

---

### Task 4: Normalizer — qc passthrough + agreement tests

**Files:**
- Modify: `autogis/core/envmon/normalize_survey123.py` (delete `_build_sample_id` lines 44-47, drop the `uuid` import, extend `Survey123Field`, change line 89)
- Test: `tests/envmon/test_normalize_survey123.py` (3 new tests), `tests/envmon/test_sample_id.py` (cross-module agreement test)

**Interfaces:**
- Consumes: `build_sample_id` from Task 1; `IsFieldDup` field name from Task 3.
- Produces: `Survey123Field.is_field_dup_field: str = "IsFieldDup"` (CSV/JSON key override point, consistent with the other field overrides).

- [ ] **Step 1: Write the failing tests.** In `tests/envmon/test_normalize_survey123.py` (confirm `_PAYLOAD`'s date is 2026-06-15; adjust pinned strings if not):

```python
def test_happy_path_sample_id_pinned():
    qa = QACollector()
    _, samp = normalize_survey123_submission(_PAYLOAD, "H281", "B1", qa)
    assert samp[0]["SampleID"] == "MW-01-20260615-GW"


def test_field_dup_yes_appends_fd_suffix():
    qa = QACollector()
    _, samp = normalize_survey123_submission(
        {**_PAYLOAD, "IsFieldDup": "yes"}, "H281", "B1", qa)
    assert samp[0]["SampleID"] == "MW-01-20260615-GW-FD"


def test_field_dup_absent_or_no_is_primary():
    qa = QACollector()
    _, s1 = normalize_survey123_submission({**_PAYLOAD, "IsFieldDup": "no"},
                                           "H281", "B1", qa)
    _, s2 = normalize_survey123_submission(_PAYLOAD, "H281", "B1", qa)
    assert s1[0]["SampleID"] == s2[0]["SampleID"] == "MW-01-20260615-GW"
```

In `tests/envmon/test_sample_id.py` add the primary regression guard for the whole contract:

```python
def test_planner_and_normalizer_agree_including_field_duplicate():
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.create_sampling_event import (
        build_sampling_event_plan)
    from autogis.core.envmon.normalize_survey123 import (
        normalize_survey123_submission)

    plan = build_sampling_event_plan(
        {"site_id": "H281", "site_name": "H281"},
        {
            "event_name": "Q3", "event_date": "2026-07-15",
            "coc_prefix": "H281", "lab_name": "Lab",
            "matrices": ["GW"], "location_ids": ["MW-1"],
            "crew_list": ["Alice"], "analyte_groups": {"VOCs": ["Benzene"]},
            "group_sampling": {}, "dup_frequency": 1,
        },
        {"Benzene": {}},
        run_id="RID",
    )
    planned = {r.sample_id for r in plan.expected_samples}

    def norm(payload):
        qa = QACollector()
        _, samp = normalize_survey123_submission(payload, "H281", "B1", qa)
        return samp[0]["SampleID"]

    primary = norm({"WellID": "MW-1", "SamplingDate": "2026-07-15",
                    "Matrix": "GW"})
    dup = norm({"WellID": "MW-1", "SamplingDate": "2026-07-15",
                "Matrix": "GW", "IsFieldDup": "yes"})
    assert planned == {primary, dup}
    assert dup == primary + "-FD"
```

(Confirm the `analyte_dict` shape against an existing fixture in `tests/envmon/test_create_sampling_event.py` — validation is `analyte not in analyte_dict`, so a top-level `{"Benzene": {}}` is expected to work.)

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH="$PWD" python -m pytest tests/envmon/test_normalize_survey123.py tests/envmon/test_sample_id.py -q`
Expected: new tests FAIL (`IsFieldDup` ignored; import of `_build_sample_id` still local)

- [ ] **Step 3: Implement.** In `normalize_survey123.py`:

- Remove `import uuid` and the `_build_sample_id` function (lines 44-47).
- Add import: `from .sample_id import build_sample_id`
- Extend the dataclass:

```python
@dataclass
class Survey123Field:
    well_id_field: str = "WellID"
    sampling_date_field: str = "SamplingDate"
    matrix_field: str = "Matrix"
    sampled_by_field: str = "SampledBy"
    coc_number_field: str = "COCNumber"
    dtw_field: str = "DepthToWater_ft"
    is_field_dup_field: str = "IsFieldDup"
```

- Replace line 89:

```python
    dup_raw = str(payload.get(fm.is_field_dup_field, "") or "").strip().lower()
    qc = "FD" if dup_raw == "yes" else None
    sample_id = build_sample_id(well_id, dt, matrix, qc=qc)
```

(A form generated before this change has no `IsFieldDup` question; a missing field normalizes as "not a duplicate" — the migration contract in the spec.)

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONPATH="$PWD" python -m pytest tests/envmon/test_normalize_survey123.py tests/envmon/test_sample_id.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add autogis/core/envmon/normalize_survey123.py tests/envmon/test_normalize_survey123.py tests/envmon/test_sample_id.py
git commit -m "feat(envmon): normalizer produces field-duplicate SampleIDs; planner/normalizer agreement pinned"
```

---

### Task 5: Reconciliation structural guard

**Files:**
- Modify: `autogis/core/envmon/reconcile_survey123_lab.py:85-92` (fuzzy candidate selection)
- Test: `tests/envmon/test_reconcile_survey123_lab.py` (2 new tests)

**Interfaces:**
- Consumes: `parse_sample_id` from Task 1.

- [ ] **Step 1: Write the failing tests.** In `tests/envmon/test_reconcile_survey123_lab.py`:

```python
def test_field_duplicate_never_fuzzy_matches_its_primary():
    fs = [Survey123Sample("MW-1-20260715-GW-FD", "MW-1", "2026-07-15", "GW")]
    lab = [LabSample("MW-1-20260715-GW", "MW-1", "2026-07-15", "GW")]
    r = reconcile_field_lab(fs, lab)
    assert r.matched == []
    assert [s.sample_id for s in r.field_only] == ["MW-1-20260715-GW-FD"]
    assert [s.sample_id for s in r.lab_only] == ["MW-1-20260715-GW"]


def test_primary_never_consumes_lab_duplicate():
    fs = [Survey123Sample("MW-1-20260715-GW", "MW-1", "2026-07-15", "GW")]
    lab = [LabSample("MW-1-20260715-GW-FD", "MW-1", "2026-07-15", "GW")]
    r = reconcile_field_lab(fs, lab)
    assert r.matched == []
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH="$PWD" python -m pytest tests/envmon/test_reconcile_survey123_lab.py -q`
Expected: both new tests FAIL (0.914 similarity ≥ 0.85 → false pair)

- [ ] **Step 3: Implement.** In `reconcile_survey123_lab.py`, add `from .sample_id import parse_sample_id` and replace the fuzzy block (the dead `best_score = 0.0 / best = None` initializers included):

```python
        # structural guard before any similarity score: two lifecycle IDs
        # whose QC components differ can never match (-FD must not consume
        # its own primary; similarity for that pair is ~0.914, above 0.85)
        fs_parts = parse_sample_id(fs.sample_id)
        candidates = unmatched_lab
        if fs_parts is not None:
            candidates = [
                ls for ls in unmatched_lab
                if (lp := parse_sample_id(ls.sample_id)) is None
                or lp.qc == fs_parts.qc
            ]
        best_score, best = max(
            ((_sim(fs.sample_id, ls.sample_id), ls) for ls in candidates),
            key=lambda x: x[0],
            default=(0.0, None),
        )
```

The `threshold=0.85` default is unchanged.

- [ ] **Step 4: Run to verify pass (including the existing fuzzy tests)**

Run: `PYTHONPATH="$PWD" python -m pytest tests/envmon/test_reconcile_survey123_lab.py -q`
Expected: all PASS — legitimate fuzzy matches (same/absent qc, unparseable IDs) keep working

- [ ] **Step 5: Commit**

```bash
git add autogis/core/envmon/reconcile_survey123_lab.py tests/envmon/test_reconcile_survey123_lab.py
git commit -m "fix(envmon): QC structural guard stops -FD duplicate consuming its primary lab record"
```

---

### Task 6: `qc_sample_summary` imports the suffix map

**Files:**
- Modify: `autogis/core/envmon/qc_sample_summary.py:23-30`
- Test: `tests/envmon/test_qc_sample_summary.py` (1 new test; confirm exact filename with `ls tests/envmon/ | grep qc`)

**Interfaces:**
- Consumes: `QC_SUFFIXES` from Task 1.

- [ ] **Step 1: Write the failing-or-green test** (it may pass already — it pins the previously untested `-fd` path):

```python
def test_infer_qc_type_field_duplicate_suffix():
    from autogis.core.envmon.qc_sample_summary import _infer_qc_type
    assert _infer_qc_type("MW-1-20260715-GW-FD", "") == "field_duplicate"
```

- [ ] **Step 2: Replace the literal.** Delete the `_SUFFIX_MAP = {...}` dict (lines 24-30) and add to the module imports:

```python
from .sample_id import QC_SUFFIXES as _SUFFIX_MAP
```

`_infer_qc_type` body stays unchanged.

- [ ] **Step 3: Run**

Run: `PYTHONPATH="$PWD" python -m pytest tests/envmon/test_qc_sample_summary.py tests/envmon/test_sample_id.py -q`
Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add autogis/core/envmon/qc_sample_summary.py tests/envmon/test_qc_sample_summary.py
git commit -m "refactor(envmon): qc_sample_summary consumes shared QC_SUFFIXES"
```

---

### Task 7: Non-lifecycle markers, ADR, decision log, full verification

**Files:**
- Modify: `autogis/core/envmon/sampling_plan.py:~139`, `autogis/core/envmon/legacy_migrator.py:~146` (one comment each)
- Create: `docs/adr/0113-survey123-lifecycle-sampleid-contract.md` (number re-verified at write time)
- Modify/Create: `docs/adr/logs/2026-07-25-agent-decisions.md` (append section)

- [ ] **Step 1: Mark the two non-lifecycle producers.** Directly above the SampleID construction in each file:

`sampling_plan.py` (~line 139):

```python
        # Non-lifecycle identity ({site}-{loc}-{event}-{group}): per-analyte-
        # group granularity, deliberately NOT the lifecycle SampleID —
        # core/envmon/sample_id.parse_sample_id returns None for it.
```

`legacy_migrator.py` (~line 146):

```python
            # Non-lifecycle identity ({loc}_{date}_{idx}), only invented when
            # the historical source has no SampleID — deliberately NOT the
            # lifecycle format; sample_id.parse_sample_id returns None for it.
```

- [ ] **Step 2: Reserve the ADR number and write the ADR**

```bash
python "$(git rev-parse --git-common-dir)/../.claude/coordination/coord_cli.py" reserve-adr --session 136bf14c-c096-4475-80d5-aa8e58bf72b7
```

Write `docs/adr/<reserved>-survey123-lifecycle-sampleid-contract.md` following `docs/adr/README.md` format. Content: Context = five independent SampleID constructions, two defects (unproducible `-FD`, fuzzy self-consumption at ratio 0.914 vs 0.85 threshold); Decision = single owner module `sample_id.py`, `IsFieldDup` form question, structural QC guard, non-lifecycle producers documented and excluded; Consequences = `-FD` newly producible from the field (new values, existing `TEXT(64)` column, no migration; old forms normalize unchanged), rollback = revert commit, threshold unchanged. Reference the spec and the Survey123 roadmap Phase 0 gate (SampleID leg met; envelope leg remains open for Phase 2). Update the ADR index if `docs/adr/README.md` carries one.

- [ ] **Step 3: Append the decision log** — `docs/adr/logs/2026-07-25-agent-decisions.md` (append if it exists): Decision = resumed orphaned approved spec on a fresh branch (original worktree locked by pid-27576 session, claims expired); Reasoning = no active claim, coordination registry is the locking authority; Revisit if = the older session resumes slice A (supersede via collab channel + PR link).

- [ ] **Step 4: Full suite**

Run: `PYTHONPATH="$PWD" python -m pytest -q`
Expected: green (local count ≈ 2545+new; CI is the arcpy-free authority)

- [ ] **Step 5: Structural compliance check** — dispatch the `envmon-spec-checker` agent on the changed files (it verifies arcpy-free imports, canonical config, DRAFT markers). Fix anything it flags.

- [ ] **Step 6: Commit**

```bash
git add autogis/core/envmon/sampling_plan.py autogis/core/envmon/legacy_migrator.py docs/adr/
git commit -m "docs(adr): ADR for the lifecycle SampleID contract + non-lifecycle markers"
```

---

### Task 8: PR

- [ ] **Step 1: Push and open the PR** (do NOT self-merge):

```bash
git push -u origin worktree-survey123-sampleid-impl
gh pr create -R 0bnoxide/AutoGIS --title "feat(envmon): Survey123 Phase 0 slice A — lifecycle SampleID contract" --body "<summary: spec link, ADR link, both defects + fixes, test evidence, migration notes; footer per session rules>"
```

- [ ] **Step 2: Collab channel status** — `memory_write` to `collab:autogis`: slice A implemented as PR #N on `worktree-survey123-sampleid-impl`; supersedes the spec-only state of `worktree-survey123-sample-id-contract` (that worktree/branch can be retired after merge).

- [ ] **Step 3: Report to user** — PR link, gate leg status (SampleID leg of Phase 0 done pending review; envelope leg deferred to Phase 2 per spec).
