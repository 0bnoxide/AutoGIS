# Survey123 Phase 1 Form Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `envmon validate-survey-form` (static XLSForm validation incl. the ADR-0113 SampleID contract and config cross-refs) and `envmon diff-survey-schema` (safe / review-required / destructive change classification vs a baseline form and/or a saved feature-layer spec).

**Architecture:** One new core module `autogis/core/envmon/survey_schema.py` (openpyxl + stdlib): the repo's first XLSForm reader, a QACollector-appending validator, a form-vs-form differ with a fixed taxonomy, and a form-vs-layer leg that maps questions into the fetched-schema shape `audit_schema.diff_schema` already consumes. CLI rides `qa_report_options`/`_render_qa` for validate and semantic exit codes (0/2/3) for diff.

**Tech Stack:** Python stdlib, openpyxl, click, existing `QACollector` / `audit_schema` / `sample_id` seams.

**Spec:** `docs/superpowers/specs/2026-07-25-survey123-phase1-form-validation-design.md` (approved).

## Global Constraints

- `core/` imports with neither `arcpy` nor `arcgis`; new module is openpyxl + stdlib only.
- `main` is READ-ONLY — all work on `worktree-survey123-phase1-form-validation`.
- Two new CLI commands + tool-batch scope → ADR required; number chosen at write time vs origin/main + all open PRs (0114 expected).
- SampleID-contract divergence is an **ERROR** (owner decision); the validator must NOT flag backward `${ref}`s or SampleID-after-QAFlags ordering.
- Saved feature-layer definition = the existing `audit_schema` local-spec YAML; no new format.
- diff exits: 0 none/safe, 2 review-required, 3 destructive, 1 usage/IO. Validate exits: `_render_qa` 0/1.
- Run tests from worktree root: `PYTHONPATH="$PWD" python -m pytest -q ...`.
- Do not self-merge the PR.

---

### Task 1: Reader + dataclasses

**Files:**
- Create: `autogis/core/envmon/survey_schema.py`
- Test: `tests/envmon/test_survey_schema.py` (new)

**Interfaces (produced for later tasks):**
- `SurveyQuestion(type, name, label, hint, required, calculation, relevant, constraint, appearance, default, row)` — all `str` (row `int`)
- `FormSchema(questions: list[SurveyQuestion], choices: dict[str, list[tuple[str, str]]], settings: dict[str, str])`
- `read_xlsform(path) -> FormSchema` — header-driven, tolerant of missing optional columns/sheets
- Constants: `CLASS_SAFE = "safe"`, `CLASS_REVIEW = "review-required"`, `CLASS_DESTRUCTIVE = "destructive"`, `_FIELD_BASES`, `_STRUCT_BASES`

- [ ] **Step 1: failing reader tests** (helpers reused by every later task):

```python
"""Tests for survey_schema — XLSForm reader, validator, differ. Arcpy-free."""
import openpyxl
import pytest

from autogis.core.envmon.survey_schema import (
    CLASS_DESTRUCTIVE, CLASS_REVIEW, CLASS_SAFE,
    FormSchema, SurveyQuestion, read_xlsform,
)


def make_form(tmp_path, survey_rows, choices_rows=None, settings=None,
              survey_headers=("type", "name", "label", "hint", "required",
                              "calculation", "appearance", "default"),
              name="form.xlsx"):
    """Write a minimal XLSForm workbook and return its path."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("survey")
    ws.append(list(survey_headers))
    for r in survey_rows:
        ws.append(list(r))
    cs = wb.create_sheet("choices")
    cs.append(["list_name", "name", "label"])
    for r in (choices_rows or []):
        cs.append(list(r))
    if settings is not None:
        st = wb.create_sheet("settings")
        st.append(list(settings.keys()))
        st.append(list(settings.values()))
    p = tmp_path / name
    wb.save(p)
    return p


def test_reader_maps_columns_by_header_not_position(tmp_path):
    p = make_form(
        tmp_path,
        [("text", "Notes", "Notes label")],
        survey_headers=("name", "type", "label"),   # shuffled order
    )
    schema = read_xlsform(p)
    q = schema.questions[0]
    assert (q.type, q.name, q.label) == ("text", "Notes", "Notes label")
    assert q.calculation == ""   # absent column -> ""


def test_reader_choices_and_settings(tmp_path):
    p = make_form(
        tmp_path,
        [("select_one yn", "Q1", "Q")],
        choices_rows=[("yn", "yes", "Yes"), ("yn", "no", "No")],
        settings={"form_title": "T", "form_id": "t_form", "version": "1"},
    )
    s = read_xlsform(p)
    assert s.choices["yn"] == [("yes", "Yes"), ("no", "No")]
    assert s.settings["form_id"] == "t_form"


def test_reader_missing_sheets_yield_empty_structures(tmp_path):
    wb = openpyxl.Workbook()
    wb.active.title = "survey"
    wb.active.append(["type", "name"])
    p = tmp_path / "bare.xlsx"
    wb.save(p)
    s = read_xlsform(p)
    assert s.questions == [] and s.choices == {} and s.settings == {}


def test_reader_keeps_structural_rows_in_order(tmp_path):
    p = make_form(tmp_path, [
        ("begin_group", "g1", "G"),
        ("decimal", "d1", "D"),
        ("end_group", "", ""),
    ])
    s = read_xlsform(p)
    assert [q.type for q in s.questions] == ["begin_group", "decimal",
                                             "end_group"]
```

- [ ] **Step 2:** `PYTHONPATH="$PWD" python -m pytest tests/envmon/test_survey_schema.py -q` → FAIL (module missing)

- [ ] **Step 3: implement** module head + reader:

```python
"""survey_schema.py — XLSForm reader, validator, and schema-drift classifier.

Survey123 add-on roadmap Phase 1 (ADR-0112; decision record ADR-0114).
openpyxl + stdlib only — no arcpy, no arcgis. The form-vs-layer leg reuses
autogis.core.agol.audit_schema.diff_schema (itself arcgis-free).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import openpyxl

from ..common.qa import QACollector, QARecord, SEV_ERROR, SEV_WARNING, SEV_INFO
from .sample_id import xform_sample_id_calc

CLASS_SAFE = "safe"
CLASS_REVIEW = "review-required"
CLASS_DESTRUCTIVE = "destructive"
_CLASS_RANK = {CLASS_SAFE: 1, CLASS_REVIEW: 2, CLASS_DESTRUCTIVE: 3}

_FIELD_BASES = {"text", "integer", "decimal", "date", "datetime", "time",
                "calculate", "geopoint", "barcode",
                "select_one", "select_multiple"}
_STRUCT_BASES = {"begin_group", "end_group", "begin_repeat", "end_repeat",
                 "note"}
_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_REF_RE = re.compile(r"\$\{([^}]+)\}")
_TRUTHY_REQUIRED = {"yes", "true", "true()"}
_REQUIRED_VALUES = {"", "yes", "no", "true", "false", "true()", "false()"}


@dataclass
class SurveyQuestion:
    type: str = ""
    name: str = ""
    label: str = ""
    hint: str = ""
    required: str = ""
    calculation: str = ""
    relevant: str = ""
    constraint: str = ""
    appearance: str = ""
    default: str = ""
    row: int = 0

    @property
    def base(self) -> str:
        return self.type.split()[0].lower() if self.type.strip() else ""

    @property
    def list_name(self) -> str:
        parts = self.type.split()
        return parts[1] if self.base.startswith("select_") and len(parts) > 1 else ""


@dataclass
class FormSchema:
    questions: list = field(default_factory=list)
    choices: dict = field(default_factory=dict)
    settings: dict = field(default_factory=dict)


def _header_map(ws) -> dict:
    return {str(c.value).strip().lower(): i
            for i, c in enumerate(ws[1], start=1) if c.value}


def _cell(ws, r, col: Optional[int]) -> str:
    if not col:
        return ""
    v = ws.cell(r, col).value
    return str(v).strip() if v is not None else ""


def read_xlsform(path) -> FormSchema:
    """Read an XLSForm .xlsx. Columns map by header row, not position;
    absent optional columns/sheets yield empty values — validation, not the
    reader, decides what is an error."""
    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    schema = FormSchema()
    if "survey" in wb.sheetnames:
        ws = wb["survey"]
        h = _header_map(ws)
        for r in range(2, ws.max_row + 1):
            q = SurveyQuestion(
                type=_cell(ws, r, h.get("type")),
                name=_cell(ws, r, h.get("name")),
                label=_cell(ws, r, h.get("label")),
                hint=_cell(ws, r, h.get("hint")),
                required=_cell(ws, r, h.get("required")),
                calculation=_cell(ws, r, h.get("calculation")),
                relevant=_cell(ws, r, h.get("relevant")),
                constraint=_cell(ws, r, h.get("constraint")),
                appearance=_cell(ws, r, h.get("appearance")),
                default=_cell(ws, r, h.get("default")),
                row=r,
            )
            if q.type or q.name or q.label or q.calculation:
                schema.questions.append(q)
    if "choices" in wb.sheetnames:
        cs = wb["choices"]
        h = _header_map(cs)
        for r in range(2, cs.max_row + 1):
            ln = _cell(cs, r, h.get("list_name"))
            nm = _cell(cs, r, h.get("name"))
            lb = _cell(cs, r, h.get("label"))
            if ln or nm:
                schema.choices.setdefault(ln, []).append((nm, lb))
    if "settings" in wb.sheetnames:
        st = wb["settings"]
        h = _header_map(st)
        for key, col in h.items():
            schema.settings[key] = _cell(st, 2, col)
    wb.close()
    return schema
```

- [ ] **Step 4:** rerun → PASS
- [ ] **Step 5:** `git add autogis/core/envmon/survey_schema.py tests/envmon/test_survey_schema.py && git commit -m "feat(envmon): XLSForm reader for survey_schema (Phase 1)"`

---

### Task 2: `validate_form` — structural checks (spec checks 1–10)

**Files:**
- Modify: `autogis/core/envmon/survey_schema.py` (append)
- Test: `tests/envmon/test_survey_schema.py` (append)

**Interfaces:**
- Produces: `validate_form(schema, qa, *, event_config=None, site_config=None, analyte_dict=None) -> None` (appends `QARecord`s; ends with INFO `validation_complete`)
- QA categories (structural): `missing_sheet, missing_name, invalid_name, duplicate_name, unknown_type, unknown_choice_list, empty_choice_list, duplicate_choice, invalid_choice_name, unresolved_reference, unbalanced_group, odd_required_value, sample_id_missing, sample_id_contract_mismatch, sample_id_dup_leg, settings_incomplete, validation_complete`

- [ ] **Step 1: failing tests** (one per check; representative bodies — all go in the test file):

```python
from autogis.core.common.qa import QACollector
from autogis.core.envmon.survey_schema import validate_form
from autogis.core.envmon.sample_id import xform_sample_id_calc


def _validate(tmp_path, survey_rows, choices_rows=None, settings=None, **kw):
    p = make_form(tmp_path, survey_rows, choices_rows, settings)
    qa = QACollector()
    validate_form(read_xlsform(p), qa, **kw)
    return qa


def _cats(qa):
    return {r.category for r in qa.records}


def test_missing_choices_sheet_is_error(tmp_path):
    wb = openpyxl.Workbook(); wb.active.title = "survey"
    wb.active.append(["type", "name"]); wb.active.append(["text", "A"])
    p = tmp_path / "f.xlsx"; wb.save(p)
    qa = QACollector(); validate_form(read_xlsform(p), qa)
    assert "missing_sheet" in _cats(qa)          # choices missing -> ERROR
    assert any(r.category == "settings_incomplete" and r.severity == "WARNING"
               for r in qa.records)              # settings missing -> WARNING


def test_duplicate_and_invalid_names(tmp_path):
    qa = _validate(tmp_path, [("text", "A", ""), ("text", "a", ""),
                              ("text", "9bad", "")])
    assert "duplicate_name" in _cats(qa)
    assert "invalid_name" in _cats(qa)


def test_missing_name_and_unknown_type(tmp_path):
    qa = _validate(tmp_path, [("text", "", ""), ("wat", "W", "")])
    assert "missing_name" in _cats(qa)
    assert "unknown_type" in _cats(qa)


def test_select_list_checks(tmp_path):
    qa = _validate(
        tmp_path,
        [("select_one nolist", "Q1", ""), ("select_one empty", "Q2", ""),
         ("select_one", "Q3", "")],
        choices_rows=[("empty", "", ""),               # invalid choice name
                      ("dup", "x", "X"), ("dup", "x", "X2")],
    )
    for cat in ("unknown_choice_list", "empty_choice_list", "unknown_type",
                "duplicate_choice", "invalid_choice_name"):
        assert cat in _cats(qa), cat


def test_unresolved_reference_and_backward_ref_ok(tmp_path):
    qa = _validate(tmp_path, [
        ("text", "A", ""),
        ("calculate", "C1", "", "", "", "concat(${A}, ${Missing})"),
        ("calculate", "C2", "", "", "", "${Later}"),
        ("text", "Later", ""),
    ])
    recs = [r for r in qa.records if r.category == "unresolved_reference"]
    assert len(recs) == 1 and "Missing" in recs[0].message


def test_unbalanced_group_detected(tmp_path):
    qa = _validate(tmp_path, [("begin_group", "g", ""), ("text", "A", ""),
                              ("end_repeat", "", "")])
    assert "unbalanced_group" in _cats(qa)


def test_odd_required_value_warns(tmp_path):
    qa = _validate(tmp_path, [("text", "A", "", "", "maybe")])
    rec = next(r for r in qa.records if r.category == "odd_required_value")
    assert rec.severity == "WARNING"


def test_sample_id_missing_is_error(tmp_path):
    qa = _validate(tmp_path, [("text", "A", "")])
    assert "sample_id_missing" in _cats(qa)


def test_sample_id_contract_match_and_mismatch(tmp_path):
    good = [("select_one well_list", "WellID", "", "", "yes"),
            ("date", "SamplingDate", "", "", "yes"),
            ("select_one matrix_list", "Matrix", "", "", "yes"),
            ("select_multiple qa_flags", "QAFlags", ""),
            ("calculate", "SampleID", "", "", "", xform_sample_id_calc())]
    choices = [("well_list", "MW-1", "MW-1"), ("matrix_list", "GW", "GW"),
               ("qa_flags", "field_dup", "Field Duplicate")]
    qa = _validate(tmp_path, good, choices)
    assert "sample_id_contract_mismatch" not in _cats(qa)

    bad = list(good); bad[4] = ("calculate", "SampleID", "", "", "", "${WellID}")
    qa2 = _validate(tmp_path, bad, choices)
    rec = next(r for r in qa2.records
               if r.category == "sample_id_contract_mismatch")
    assert rec.severity == "ERROR"


def test_sample_id_dup_leg_requires_flag_choice(tmp_path):
    rows = [("select_one well_list", "WellID", "", "", "yes"),
            ("date", "SamplingDate", "", "", "yes"),
            ("select_one matrix_list", "Matrix", "", "", "yes"),
            ("select_multiple qa_flags", "QAFlags", ""),
            ("calculate", "SampleID", "", "", "", xform_sample_id_calc())]
    choices = [("well_list", "MW-1", "MW-1"), ("matrix_list", "GW", "GW"),
               ("qa_flags", "resampled", "Resampled")]   # no field_dup
    qa = _validate(tmp_path, rows, choices)
    assert "sample_id_dup_leg" in _cats(qa)


def test_validation_complete_summary_present(tmp_path):
    qa = _validate(tmp_path, [("text", "A", "")])
    assert any(r.category == "validation_complete" and r.severity == "INFO"
               for r in qa.records)
```

- [ ] **Step 2:** run → FAIL (`validate_form` undefined)

- [ ] **Step 3: implement** (append to module):

```python
_SELECTED_RE = re.compile(r'selected\(\s*\$\{(\w+)\}\s*,\s*"([^"]*)"\s*\)')
_SLUG_RE = re.compile(r"^[a-z0-9_]+$")


def _err(qa, cat, msg):
    qa.add(QARecord(SEV_ERROR, cat, msg))


def _warn(qa, cat, msg):
    qa.add(QARecord(SEV_WARNING, cat, msg))


def validate_form(schema: FormSchema, qa: QACollector, *,
                  event_config: Optional[dict] = None,
                  site_config: Optional[dict] = None,
                  analyte_dict: Optional[dict] = None) -> None:
    """Static XLSForm validation (spec checks 1-13). Appends QARecords."""
    site_id = (site_config or {}).get("site_id", "")
    ctx = f"[{site_id}] " if site_id else ""

    # 1. sheets
    if not schema.questions:
        _err(qa, "missing_sheet", ctx + "survey sheet missing or empty")
    if not schema.choices:
        _err(qa, "missing_sheet", ctx + "choices sheet missing or empty")
    if not schema.settings:
        _warn(qa, "settings_incomplete", ctx + "settings sheet missing")

    names: dict = {}
    fields = [q for q in schema.questions if q.base in _FIELD_BASES]

    for q in schema.questions:
        base = q.base
        # 3. type recognized
        if base and base not in _FIELD_BASES and base not in _STRUCT_BASES:
            _err(qa, "unknown_type",
                 f"row {q.row}: unknown question type {q.type!r}")
        if base.startswith("select_") and not q.list_name:
            _err(qa, "unknown_type",
                 f"row {q.row}: {base} without a choice list name")
        # 2. names
        if base in _FIELD_BASES:
            if not q.name:
                _err(qa, "missing_name", f"row {q.row}: {base} without a name")
            else:
                if not _NAME_RE.match(q.name):
                    _err(qa, "invalid_name",
                         f"row {q.row}: invalid name {q.name!r}")
                key = q.name.lower()
                if key in names:
                    _err(qa, "duplicate_name",
                         f"row {q.row}: duplicate name {q.name!r} "
                         f"(first at row {names[key]})")
                else:
                    names[key] = q.row
        # 7. required sanity
        if q.required and q.required.lower() not in _REQUIRED_VALUES:
            _warn(qa, "odd_required_value",
                  f"row {q.row}: required={q.required!r} on {q.name!r}")

    # 4. select_* list resolution + choices hygiene
    for q in fields:
        if q.base.startswith("select_") and q.list_name:
            if q.list_name not in schema.choices:
                _err(qa, "unknown_choice_list",
                     f"row {q.row}: {q.name!r} references missing choice "
                     f"list {q.list_name!r}")
            elif not [c for c, _ in schema.choices[q.list_name] if c]:
                _err(qa, "empty_choice_list",
                     f"row {q.row}: choice list {q.list_name!r} is empty")
    for ln, pairs in schema.choices.items():
        seen = set()
        for cname, _lbl in pairs:
            if not cname or not _NAME_RE.match(cname.replace("-", "_")):
                _err(qa, "invalid_choice_name",
                     f"list {ln!r}: invalid choice name {cname!r}")
                continue
            if (ln, cname) in seen:
                _err(qa, "duplicate_choice",
                     f"list {ln!r}: duplicate choice {cname!r}")
            seen.add((ln, cname))

    # 5. ${ref} resolution (order-independent by design — ADR-0113 emits
    # SampleID after QAFlags; XLSForm resolves calculates by dependency)
    all_names = {q.name for q in fields if q.name}
    for q in schema.questions:
        for expr in (q.calculation, q.relevant, q.constraint):
            for ref in _REF_RE.findall(expr or ""):
                if ref not in all_names:
                    _err(qa, "unresolved_reference",
                         f"row {q.row}: ${{{ref}}} does not resolve to a "
                         f"question name")

    # 6. group/repeat balance
    stack = []
    for q in schema.questions:
        if q.base in ("begin_group", "begin_repeat"):
            stack.append((q.base, q.row))
        elif q.base in ("end_group", "end_repeat"):
            want = "begin_" + q.base.split("_")[1]
            if not stack or stack[-1][0] != want:
                _err(qa, "unbalanced_group",
                     f"row {q.row}: {q.base} without matching {want}")
            else:
                stack.pop()
    for base, row in stack:
        _err(qa, "unbalanced_group", f"row {row}: {base} never closed")

    # 8-9. SampleID contract (ADR-0113) + duplicate-leg dependency
    sid = next((q for q in fields if q.name == "SampleID"), None)
    if sid is None:
        _err(qa, "sample_id_missing",
             ctx + "no calculate question named 'SampleID'")
    else:
        if sid.base != "calculate":
            _err(qa, "sample_id_contract_mismatch",
                 f"row {sid.row}: SampleID must be a calculate, got "
                 f"{sid.type!r}")
        expected = " ".join(xform_sample_id_calc().split())
        actual = " ".join((sid.calculation or "").split())
        if actual != expected:
            _err(qa, "sample_id_contract_mismatch",
                 f"row {sid.row}: SampleID calculation diverges from the "
                 f"ADR-0113 contract; expected {expected!r}")
        m = _SELECTED_RE.search(sid.calculation or "")
        if m:
            flag_q, flag_val = m.group(1), m.group(2)
            src = next((q for q in fields if q.name == flag_q), None)
            if src is not None and src.list_name:
                have = {c for c, _ in schema.choices.get(src.list_name, [])}
                if flag_val not in have:
                    _err(qa, "sample_id_dup_leg",
                         f"choice list {src.list_name!r} lacks the "
                         f"{flag_val!r} choice the SampleID duplicate leg "
                         f"reads")

    # 10. settings
    if schema.settings:
        fid = schema.settings.get("form_id", "")
        if not fid or not _SLUG_RE.match(fid):
            _warn(qa, "settings_incomplete",
                  f"settings: form_id {fid!r} missing or not slug-shaped")
        if not schema.settings.get("version"):
            _warn(qa, "settings_incomplete", "settings: version missing")

    _cross_reference_checks(schema, qa, event_config, analyte_dict, ctx)

    qa.add(QARecord(SEV_INFO, "validation_complete",
                    f"{ctx}validated {len(fields)} questions, "
                    f"{len(schema.choices)} choice lists"))
```

Add a stub so Task 2 is runnable before Task 3:

```python
def _cross_reference_checks(schema, qa, event_config, analyte_dict, ctx):
    if not event_config:
        return
```

- [ ] **Step 4:** rerun → PASS
- [ ] **Step 5:** `git add -u tests autogis && git commit -m "feat(envmon): structural XLSForm validation incl. ADR-0113 SampleID contract"`

---

### Task 3: config cross-refs + round-trip integration test

**Files:**
- Modify: `autogis/core/envmon/survey_schema.py` (`_cross_reference_checks` body)
- Test: `tests/envmon/test_survey_schema.py` (append)

**Interfaces:**
- Consumes: `survey123_form_builder._slug`, `._field_name`, `.build_xlsform`
- Categories: `missing_location_choice, extra_location_choice, missing_matrix_choice, extra_matrix_choice, missing_crew_choice, extra_crew_choice, missing_analyte_question, unexpected_analyte_question, unknown_analyte` (one aggregated record per category)

- [ ] **Step 1: failing tests:**

```python
SITE = {"site_id": "H281", "site_name": "H281 Glasgow"}
EVENT = {
    "analyte_groups": {"VOCs": ["Benzene", "Toluene"], "Metals": ["Arsenic"]},
    "crew_list": ["Alice Smith", "Bob Jones"],
    "coc_prefix": "H281-COC", "matrices": ["GW"],
    "location_ids": ["MW-1", "MW-2", "MW-3"],
}
ADICT = {"analytes": {
    "Benzene": {"abbreviation": "B",
                "default_units_by_matrix": {"GW": "ug/L"}},
    "Toluene": {"abbreviation": "T",
                "default_units_by_matrix": {"GW": "ug/L"}},
    "Arsenic": {"abbreviation": "As",
                "default_units_by_matrix": {"GW": "ug/L"}},
}}


def test_generated_form_validates_clean_against_its_configs(tmp_path):
    """Round-trip lockstep: builder output + same configs -> zero findings."""
    from autogis.core.envmon.survey123_form_builder import build_xlsform
    wb = build_xlsform(SITE, EVENT, ADICT)
    p = tmp_path / "gen.xlsx"
    wb.save(p)
    qa = QACollector()
    validate_form(read_xlsform(p), qa, event_config=EVENT,
                  site_config=SITE, analyte_dict=ADICT)
    bad = [r for r in qa.records if r.severity in ("ERROR", "WARNING")]
    assert bad == [], [f"{r.category}: {r.message}" for r in bad]


def test_missing_location_and_extra_crew_flagged(tmp_path):
    from autogis.core.envmon.survey123_form_builder import build_xlsform
    smaller = {**EVENT, "location_ids": ["MW-1"],
               "crew_list": ["Alice Smith", "Bob Jones", "Cara Doe"]}
    wb = build_xlsform(SITE, smaller, ADICT)
    p = tmp_path / "gen2.xlsx"
    wb.save(p)
    qa = QACollector()
    validate_form(read_xlsform(p), qa, event_config=EVENT,
                  analyte_dict=ADICT)   # validate against the BIGGER event
    cats = _cats(qa)
    assert "missing_location_choice" in cats     # MW-2/MW-3 not in form
    assert "extra_crew_choice" in cats           # cara_doe extra


def test_missing_analyte_question_flagged(tmp_path):
    from autogis.core.envmon.survey123_form_builder import build_xlsform
    fewer = {**EVENT, "analyte_groups": {"VOCs": ["Benzene"]}}
    wb = build_xlsform(SITE, fewer, ADICT)
    p = tmp_path / "gen3.xlsx"
    wb.save(p)
    qa = QACollector()
    validate_form(read_xlsform(p), qa, event_config=EVENT,
                  analyte_dict=ADICT)
    assert "missing_analyte_question" in _cats(qa)   # Toluene, Arsenic


def test_unknown_analyte_warns_with_dict(tmp_path):
    from autogis.core.envmon.survey123_form_builder import build_xlsform
    wb = build_xlsform(SITE, EVENT, ADICT)
    p = tmp_path / "gen4.xlsx"
    wb.save(p)
    event = {**EVENT,
             "analyte_groups": {**EVENT["analyte_groups"],
                                "VOCs": ["Benzene", "Toluene", "Xylene"]}}
    qa = QACollector()
    validate_form(read_xlsform(p), qa, event_config=event,
                  analyte_dict=ADICT)
    assert "unknown_analyte" in _cats(qa)
```

- [ ] **Step 2:** run → FAIL
- [ ] **Step 3: implement** (replace the stub):

```python
def _list_for(schema: FormSchema, qname: str) -> Optional[str]:
    q = next((q for q in schema.questions
              if q.name == qname and q.base.startswith("select_")), None)
    return q.list_name if q else None


def _set_check(schema, qa, qname, expected, miss_cat, extra_cat, what, ctx):
    ln = _list_for(schema, qname)
    if ln is None:
        return
    have = {c for c, _ in schema.choices.get(ln, [])}
    missing = sorted(set(expected) - have)
    extra = sorted(have - set(expected))
    if missing:
        _err(qa, miss_cat, f"{ctx}{what} missing from form list {ln!r}: "
                           f"{', '.join(missing)}")
    if extra:
        _warn(qa, extra_cat, f"{ctx}extra {what} in form list {ln!r}: "
                             f"{', '.join(extra)}")


def _cross_reference_checks(schema, qa, event_config, analyte_dict, ctx):
    """Spec checks 11-13 — each only when its config is supplied."""
    if not event_config:
        return
    from .survey123_form_builder import _field_name, _slug

    _set_check(schema, qa, "WellID", event_config.get("location_ids", []),
               "missing_location_choice", "extra_location_choice",
               "planned locations", ctx)
    _set_check(schema, qa, "Matrix", event_config.get("matrices", []),
               "missing_matrix_choice", "extra_matrix_choice",
               "matrices", ctx)
    _set_check(schema, qa, "SampledBy",
               [_slug(m) for m in event_config.get("crew_list", [])],
               "missing_crew_choice", "extra_crew_choice", "crew", ctx)

    groups = event_config.get("analyte_groups", {})
    if analyte_dict is not None:
        known = set((analyte_dict.get("analytes") or {}))
        unknown = sorted({a for names in groups.values() if isinstance(names, list)
                          for a in names} - known)
        if unknown:
            _warn(qa, "unknown_analyte",
                  f"{ctx}analyte_groups name(s) not in the analyte "
                  f"dictionary: {', '.join(unknown)}")

    used: set = set()
    expected = {}
    for names in groups.values():
        if not isinstance(names, list):
            continue
        for analyte in names:
            expected[_field_name(analyte, used)] = analyte
    have = {q.name for q in schema.questions
            if q.base == "decimal" and q.name}
    missing = sorted(expected[n] for n in expected if n not in have)
    if missing:
        _err(qa, "missing_analyte_question",
             f"{ctx}no decimal question for analyte(s): "
             f"{', '.join(missing)}")

    # decimals inside grp_* groups that no analyte accounts for
    gstack, unexpected = [], []
    for q in schema.questions:
        if q.base == "begin_group":
            gstack.append(q.name)
        elif q.base == "end_group":
            gstack and gstack.pop()
        elif (q.base == "decimal" and q.name and q.name not in expected
              and any(g.startswith("grp_") for g in gstack)):
            unexpected.append(q.name)
    if unexpected:
        _warn(qa, "unexpected_analyte_question",
              f"{ctx}decimal question(s) in analyte groups with no "
              f"analyte behind them: {', '.join(sorted(unexpected))}")
```

- [ ] **Step 4:** rerun → PASS (the round-trip test is the lockstep pin)
- [ ] **Step 5:** `git add -u && git commit -m "feat(envmon): config cross-reference checks + builder/validator round-trip pin"`

---

### Task 4: `diff_forms` + taxonomy

**Files:**
- Modify: `autogis/core/envmon/survey_schema.py` (append)
- Test: `tests/envmon/test_survey_schema.py` (append)

**Interfaces:**
- Produces: `SchemaChange(kind, classification, name, detail)`; `diff_forms(old, new) -> list[SchemaChange]`; `worst_classification(changes) -> Optional[str]`

- [ ] **Step 1: failing table-driven test:**

```python
from autogis.core.envmon.survey_schema import (
    diff_forms, worst_classification, SchemaChange,
)


BASE_ROWS = [
    ("text", "A", "Label A", "", "yes"),
    ("select_one lst", "S", "Sel"),
    ("begin_repeat", "rep", "R"),
    ("decimal", "InRep", "d"),
    ("end_repeat", "", ""),
    ("calculate", "C", "", "", "", "${A}"),
    ("calculate", "SampleID", "", "", "", "x"),
]
BASE_CHOICES = [("lst", "one", "One"), ("lst", "two", "Two")]
BASE_SETTINGS = {"form_title": "T", "form_id": "t_id", "version": "1"}


def _diff(tmp_path, new_rows, new_choices=None, new_settings=None):
    old = read_xlsform(make_form(tmp_path, BASE_ROWS, BASE_CHOICES,
                                 dict(BASE_SETTINGS), name="old.xlsx"))
    new = read_xlsform(make_form(tmp_path, new_rows,
                                 BASE_CHOICES if new_choices is None else new_choices,
                                 dict(BASE_SETTINGS) if new_settings is None else new_settings,
                                 name="new.xlsx"))
    return diff_forms(old, new)


def _kinds(changes):
    return {(c.kind, c.classification) for c in changes}


def test_diff_taxonomy_rows(tmp_path):
    rows = list(BASE_ROWS)

    # unchanged -> no changes
    assert _diff(tmp_path, rows) == []

    # added optional / added required
    ch = _kinds(_diff(tmp_path, rows + [("text", "NewOpt", "")]))
    assert ("question_added", CLASS_SAFE) in ch
    ch = _kinds(_diff(tmp_path, rows + [("text", "NewReq", "", "", "yes")]))
    assert ("question_added_required", CLASS_REVIEW) in ch

    # removed -> destructive
    ch = _kinds(_diff(tmp_path, [r for r in rows if r[1] != "A"]))
    assert ("question_removed", CLASS_DESTRUCTIVE) in ch

    # type change -> destructive
    ch = _kinds(_diff(tmp_path,
                      [("integer", *r[1:]) if r[1] == "A" else r for r in rows]))
    assert ("type_changed", CLASS_DESTRUCTIVE) in ch

    # required flips
    ch = _kinds(_diff(tmp_path,
                      [("text", "A", "Label A", "", "") if r[1] == "A" else r
                       for r in rows]))
    assert ("required_relaxed", CLASS_SAFE) in ch
    rows_opt = [("text", "A", "Label A", "", "") if r[1] == "A" else r
                for r in rows]
    old_opt = read_xlsform(make_form(tmp_path, rows_opt, BASE_CHOICES,
                                     dict(BASE_SETTINGS), name="o2.xlsx"))
    new_req = read_xlsform(make_form(tmp_path, rows, BASE_CHOICES,
                                     dict(BASE_SETTINGS), name="n2.xlsx"))
    assert ("required_tightened", CLASS_REVIEW) in _kinds(
        diff_forms(old_opt, new_req))

    # calculation changes
    ch = _kinds(_diff(tmp_path,
                      [("calculate", "C", "", "", "", "${A} + 1")
                       if r[1] == "C" else r for r in rows]))
    assert ("calculation_changed", CLASS_REVIEW) in ch
    ch = _kinds(_diff(tmp_path,
                      [("calculate", "SampleID", "", "", "", "y")
                       if r[1] == "SampleID" else r for r in rows]))
    assert ("sample_id_calculation_changed", CLASS_DESTRUCTIVE) in ch

    # list re-pointed
    ch = _kinds(_diff(tmp_path,
                      [("select_one other", "S", "Sel") if r[1] == "S" else r
                       for r in rows],
                      new_choices=BASE_CHOICES + [("other", "x", "X")]))
    assert ("list_repointed", CLASS_REVIEW) in ch

    # repeat scope move -> destructive
    moved = [("text", "A", "Label A", "", "yes"),
             ("select_one lst", "S", "Sel"),
             ("begin_repeat", "rep", "R"),
             ("end_repeat", "", ""),
             ("decimal", "InRep", "d"),
             ("calculate", "C", "", "", "", "${A}"),
             ("calculate", "SampleID", "", "", "", "x")]
    assert ("repeat_scope_changed", CLASS_DESTRUCTIVE) in _kinds(
        _diff(tmp_path, moved))

    # repeat added / removed -> destructive
    ch = _kinds(_diff(tmp_path, rows + [("begin_repeat", "rep2", "R2"),
                                        ("end_repeat", "", "")]))
    assert ("repeat_added", CLASS_DESTRUCTIVE) in ch
    norep = [r for r in rows if r[1] not in ("rep", "InRep")
             and r[0] != "end_repeat"]
    assert ("repeat_removed", CLASS_DESTRUCTIVE) in _kinds(
        _diff(tmp_path, norep))

    # cosmetic -> safe
    ch = _kinds(_diff(tmp_path,
                      [("text", "A", "Renamed label", "", "yes")
                       if r[1] == "A" else r for r in rows]))
    assert ("cosmetic_changed", CLASS_SAFE) in ch


def test_diff_choice_rows(tmp_path):
    rows = list(BASE_ROWS)
    # choice added / label changed -> safe
    ch = _kinds(_diff(tmp_path, rows,
                      new_choices=BASE_CHOICES + [("lst", "three", "Three")]))
    assert ("choice_added", CLASS_SAFE) in ch
    ch = _kinds(_diff(tmp_path, rows,
                      new_choices=[("lst", "one", "Uno"),
                                   ("lst", "two", "Two")]))
    assert ("choice_label_changed", CLASS_SAFE) in ch
    # choice removed -> review
    ch = _kinds(_diff(tmp_path, rows, new_choices=[("lst", "one", "One")]))
    assert ("choice_removed", CLASS_REVIEW) in ch
    # code change (same label, new code) -> destructive
    ch = _kinds(_diff(tmp_path, rows,
                      new_choices=[("lst", "uno", "One"),
                                   ("lst", "two", "Two")]))
    assert ("choice_code_changed", CLASS_DESTRUCTIVE) in ch


def test_diff_settings_and_worst(tmp_path):
    rows = list(BASE_ROWS)
    ch = _diff(tmp_path, rows,
               new_settings={"form_title": "T", "form_id": "other",
                             "version": "2"})
    kinds = _kinds(ch)
    assert ("form_id_changed", CLASS_DESTRUCTIVE) in kinds
    assert ("settings_changed", CLASS_SAFE) in kinds
    assert worst_classification(ch) == CLASS_DESTRUCTIVE
    assert worst_classification([]) is None
```

- [ ] **Step 2:** run → FAIL
- [ ] **Step 3: implement:**

```python
@dataclass
class SchemaChange:
    kind: str
    classification: str
    name: str
    detail: str


def worst_classification(changes) -> Optional[str]:
    worst = None
    for c in changes:
        if worst is None or _CLASS_RANK[c.classification] > _CLASS_RANK[worst]:
            worst = c.classification
    return worst


def _is_required(v: str) -> bool:
    return (v or "").strip().lower() in _TRUTHY_REQUIRED


def _scopes(questions) -> dict:
    """name -> (repeat_path, group_path) for field-type questions."""
    out, rstack, gstack = {}, [], []
    for q in questions:
        b = q.base
        if b == "begin_repeat":
            rstack.append(q.name)
        elif b == "end_repeat":
            rstack and rstack.pop()
        elif b == "begin_group":
            gstack.append(q.name)
        elif b == "end_group":
            gstack and gstack.pop()
        elif b in _FIELD_BASES and q.name:
            out[q.name] = (tuple(rstack), tuple(gstack))
    return out


def diff_forms(old: FormSchema, new: FormSchema) -> list:
    """Classify every change between two forms (spec taxonomy table)."""
    changes: list = []

    def add(kind, cls, name, detail):
        changes.append(SchemaChange(kind, cls, name, detail))

    oldq = {q.name: q for q in old.questions if q.base in _FIELD_BASES and q.name}
    newq = {q.name: q for q in new.questions if q.base in _FIELD_BASES and q.name}
    oscope, nscope = _scopes(old.questions), _scopes(new.questions)

    orep = {q.name for q in old.questions if q.base == "begin_repeat"}
    nrep = {q.name for q in new.questions if q.base == "begin_repeat"}
    for name in sorted(orep - nrep):
        add("repeat_removed", CLASS_DESTRUCTIVE, name,
            f"repeat {name!r} removed — submission data shape changes")
    for name in sorted(nrep - orep):
        add("repeat_added", CLASS_DESTRUCTIVE, name,
            f"repeat {name!r} added — submission data shape changes")

    for name in sorted(oldq.keys() - newq.keys()):
        add("question_removed", CLASS_DESTRUCTIVE, name,
            f"question {name!r} removed (a rename is a removal)")
    for name in sorted(newq.keys() - oldq.keys()):
        q = newq[name]
        if _is_required(q.required):
            add("question_added_required", CLASS_REVIEW, name,
                f"new required question {name!r}")
        else:
            add("question_added", CLASS_SAFE, name,
                f"new optional question {name!r}")

    for name in sorted(oldq.keys() & newq.keys()):
        o, n = oldq[name], newq[name]
        if o.base != n.base:
            add("type_changed", CLASS_DESTRUCTIVE, name,
                f"type {o.base!r} -> {n.base!r}")
        elif o.base.startswith("select_") and o.list_name != n.list_name:
            add("list_repointed", CLASS_REVIEW, name,
                f"choice list {o.list_name!r} -> {n.list_name!r}")
        if oscope.get(name, ((), ()))[0] != nscope.get(name, ((), ()))[0]:
            add("repeat_scope_changed", CLASS_DESTRUCTIVE, name,
                f"repeat scope {oscope.get(name)!r} -> {nscope.get(name)!r}")
        elif oscope.get(name, ((), ()))[1] != nscope.get(name, ((), ()))[1]:
            add("group_changed", CLASS_REVIEW, name,
                f"group {oscope.get(name)!r} -> {nscope.get(name)!r}")
        if _is_required(o.required) != _is_required(n.required):
            if _is_required(n.required):
                add("required_tightened", CLASS_REVIEW, name,
                    "optional -> required")
            else:
                add("required_relaxed", CLASS_SAFE, name,
                    "required -> optional")
        oc = " ".join((o.calculation or "").split())
        nc = " ".join((n.calculation or "").split())
        if oc != nc:
            if name == "SampleID":
                add("sample_id_calculation_changed", CLASS_DESTRUCTIVE, name,
                    "the ADR-0113 identity calculation changed")
            else:
                add("calculation_changed", CLASS_REVIEW, name,
                    f"calculation {oc!r} -> {nc!r}")
        cosmetic = [c for c in ("label", "hint", "appearance", "default")
                    if getattr(o, c) != getattr(n, c)]
        if cosmetic:
            add("cosmetic_changed", CLASS_SAFE, name,
                f"changed: {', '.join(cosmetic)}")

    # choices, per list
    for ln in sorted(old.choices.keys() | new.choices.keys()):
        omap = dict(old.choices.get(ln, []))
        nmap = dict(new.choices.get(ln, []))
        removed = {c: omap[c] for c in omap.keys() - nmap.keys()}
        added = {c: nmap[c] for c in nmap.keys() - omap.keys()}
        # same label on a removed+added pair = a code change
        for rc, rl in sorted(removed.items()):
            match = next((ac for ac, al in sorted(added.items())
                          if al == rl and rl != ""), None)
            if match is not None:
                add("choice_code_changed", CLASS_DESTRUCTIVE, ln,
                    f"list {ln!r}: code {rc!r} -> {match!r} (label {rl!r})")
                del added[match]
            else:
                add("choice_removed", CLASS_REVIEW, ln,
                    f"list {ln!r}: choice {rc!r} removed")
        for ac in sorted(added):
            add("choice_added", CLASS_SAFE, ln,
                f"list {ln!r}: choice {ac!r} added")
        for c in sorted(omap.keys() & nmap.keys()):
            if omap[c] != nmap[c]:
                add("choice_label_changed", CLASS_SAFE, ln,
                    f"list {ln!r}: {c!r} label {omap[c]!r} -> {nmap[c]!r}")

    # settings
    of, nf = old.settings.get("form_id", ""), new.settings.get("form_id", "")
    if of != nf:
        add("form_id_changed", CLASS_DESTRUCTIVE, "form_id",
            f"form_id {of!r} -> {nf!r} rebinds the portal item")
    for key in ("form_title", "version", "instance_name"):
        if old.settings.get(key, "") != new.settings.get(key, ""):
            add("settings_changed", CLASS_SAFE, key,
                f"{key} {old.settings.get(key, '')!r} -> "
                f"{new.settings.get(key, '')!r}")
    return changes
```

- [ ] **Step 4:** rerun → PASS
- [ ] **Step 5:** `git add -u && git commit -m "feat(envmon): form-vs-form drift classification (safe/review/destructive)"`

---

### Task 5: form-vs-layer leg

**Files:**
- Modify: `autogis/core/envmon/survey_schema.py` (append)
- Test: `tests/envmon/test_survey_schema.py` (append)

**Interfaces:**
- Consumes: `audit_schema.diff_schema(fetched_schema: dict, local_spec: dict)`, drift constants
- Produces: `form_layer_fields(schema) -> list[dict]`, `diff_form_vs_layer(schema, layer_spec: dict) -> list[SchemaChange]`

- [ ] **Step 1: failing tests:**

```python
from autogis.core.envmon.survey_schema import (
    diff_form_vs_layer, form_layer_fields,
)

LAYER_SPEC = {
    "layer_name": "MonitoringWells",
    "fields": [
        {"name": "WellID", "type": "esriFieldTypeString"},
        {"name": "SamplingDate", "type": "esriFieldTypeDate"},
        {"name": "Matrix", "type": "esriFieldTypeString",
         "domain": {"name": "MatrixDom",
                    "coded_values": [{"code": "GW", "name": "Groundwater"}]}},
        {"name": "Sampled", "type": "esriFieldTypeSmallInteger"},
    ],
}

FORM_ROWS = [
    ("select_one well_list", "WellID", "Well"),
    ("date", "SamplingDate", "Date"),
    ("select_one matrix_list", "Matrix", "Matrix"),
    ("decimal", "DepthToWater_ft", "DTW"),
    ("note", "n1", "note rows map to no field"),
]
FORM_CHOICES = [("well_list", "MW-1", "MW-1"), ("matrix_list", "GW", "Groundwater")]


def test_form_layer_fields_mapping(tmp_path):
    s = read_xlsform(make_form(tmp_path, FORM_ROWS, FORM_CHOICES))
    fields = {f["name"]: f for f in form_layer_fields(s)}
    assert fields["WellID"]["type"] == "esriFieldTypeString"
    assert fields["SamplingDate"]["type"] == "esriFieldTypeDate"
    assert fields["DepthToWater_ft"]["type"] == "esriFieldTypeDouble"
    assert "n1" not in fields                       # note -> no field
    assert fields["Matrix"]["domain"]["codedValues"] == [
        {"code": "GW", "name": "Groundwater"}]


def test_diff_form_vs_layer_classifications(tmp_path):
    s = read_xlsform(make_form(tmp_path, FORM_ROWS, FORM_CHOICES))
    changes = diff_form_vs_layer(s, LAYER_SPEC)
    by_kind = {(c.kind, c.classification) for c in changes}
    # form-only field -> review-required
    assert ("extra_field", CLASS_REVIEW) in by_kind          # DepthToWater_ft
    # layer-only field -> safe
    assert ("missing_field", CLASS_SAFE) in by_kind          # Sampled
    # matching domains normalized -> no DOMAIN_DRIFT for Matrix
    assert not any(c.kind == "domain_drift" and c.name == "Matrix"
                   for c in changes)


def test_diff_form_vs_layer_type_mismatch_destructive(tmp_path):
    rows = [("text", "SamplingDate", "now text")]
    s = read_xlsform(make_form(tmp_path, rows))
    changes = diff_form_vs_layer(s, LAYER_SPEC)
    assert any(c.kind == "type_mismatch" and
               c.classification == CLASS_DESTRUCTIVE and
               c.name == "SamplingDate" for c in changes)
```

- [ ] **Step 2:** run → FAIL
- [ ] **Step 3: implement:**

```python
_FIELD_TYPE_TO_ESRI = {
    "text": "esriFieldTypeString", "calculate": "esriFieldTypeString",
    "barcode": "esriFieldTypeString", "time": "esriFieldTypeString",
    "select_one": "esriFieldTypeString",
    "select_multiple": "esriFieldTypeString",
    "integer": "esriFieldTypeInteger", "decimal": "esriFieldTypeDouble",
    "date": "esriFieldTypeDate", "datetime": "esriFieldTypeDate",
}

_DRIFT_CLASS = {
    "TYPE_MISMATCH": CLASS_DESTRUCTIVE,
    "EXTRA_FIELD": CLASS_REVIEW,        # form question with no layer field
    "DOMAIN_DRIFT": CLASS_REVIEW,
    "NULLABLE_MISMATCH": CLASS_REVIEW,
    "MISSING_FIELD": CLASS_SAFE,        # layer field the form doesn't collect
}


def form_layer_fields(schema: FormSchema) -> list:
    """Map form questions to AGOL-REST-shaped field dicts (the 'fetched'
    side of audit_schema.diff_schema). select_multiple gets no domain —
    Survey123 stores it comma-joined."""
    fields = []
    for q in schema.questions:
        esri = _FIELD_TYPE_TO_ESRI.get(q.base)
        if not esri or not q.name:
            continue
        f = {"name": q.name, "type": esri}
        if q.base == "select_one" and q.list_name:
            pairs = schema.choices.get(q.list_name, [])
            if pairs:
                f["domain"] = {
                    "name": q.list_name,
                    "codedValues": [{"code": c, "name": l} for c, l in pairs],
                }
        fields.append(f)
    return fields


def diff_form_vs_layer(schema: FormSchema, layer_spec: dict) -> list:
    """Compatibility of a form against a saved feature-layer definition
    (audit_schema local-spec format). Reuses audit_schema.diff_schema; the
    form plays the fetched side."""
    from ..agol.audit_schema import diff_schema

    form_fields = form_layer_fields(schema)
    spec_by_name = {f.get("name"): f for f in layer_spec.get("fields", [])}
    for f in form_fields:
        sf = spec_by_name.get(f["name"])
        if sf and "domain" in f and isinstance(sf.get("domain"), dict):
            # the form has no portal domain name — adopt the spec's so only
            # coded-value drift surfaces, not a guaranteed name mismatch
            f["domain"]["name"] = sf["domain"].get("name",
                                                   f["domain"]["name"])
    report = diff_schema({"fields": form_fields}, layer_spec)
    return [
        SchemaChange(
            kind=item.drift_type.lower(),
            classification=_DRIFT_CLASS.get(item.drift_type, CLASS_REVIEW),
            name=item.field_name,
            detail=item.message,
        )
        for item in report.drift_items
    ]
```

- [ ] **Step 4:** rerun → PASS
- [ ] **Step 5:** `git add -u && git commit -m "feat(envmon): form-vs-feature-layer compatibility via audit_schema reuse"`

---

### Task 6: CLI commands + capabilities registration

**Files:**
- Modify: `autogis/adapters/cli.py` (after `build_survey_form_cmd`, ~line 2242)
- Modify: `autogis/runtime/capabilities.py` (`TOOLS` dict + `_REGISTRY_SEED`)
- Test: `tests/envmon/test_survey_schema.py` (append CLI tests)

**Interfaces:**
- Consumes: everything from Tasks 1–5; `qa_report_options` (cli.py:17), `_render_qa` (cli.py:1779)

- [ ] **Step 1: failing CLI tests:**

```python
def _write_yaml(tmp_path, name, data):
    import yaml
    p = tmp_path / name
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


def test_both_commands_in_help():
    from click.testing import CliRunner
    from autogis.adapters.cli import autogis
    out = CliRunner().invoke(autogis, ["envmon", "--help"]).output
    assert "validate-survey-form" in out
    assert "diff-survey-schema" in out


def test_validate_cli_pass_and_fail(tmp_path):
    from click.testing import CliRunner
    from autogis.core.envmon.survey123_form_builder import build_xlsform
    from autogis.adapters.cli import autogis
    good = tmp_path / "good.xlsx"
    build_xlsform(SITE, EVENT, ADICT).save(good)
    r = CliRunner().invoke(autogis, ["envmon", "validate-survey-form",
                                     str(good)])
    assert r.exit_code == 0 and "Status: PASS" in r.output

    bad = make_form(tmp_path, [("text", "A", "")], name="bad.xlsx")
    r = CliRunner().invoke(autogis, ["envmon", "validate-survey-form",
                                     str(bad)])
    assert r.exit_code == 1 and "Status: FAIL" in r.output


def test_diff_cli_requires_a_baseline(tmp_path):
    from click.testing import CliRunner
    from autogis.adapters.cli import autogis
    f = make_form(tmp_path, [("text", "A", "")])
    r = CliRunner().invoke(autogis, ["envmon", "diff-survey-schema", str(f)])
    assert r.exit_code != 0
    assert "baseline" in r.output.lower()


def test_diff_cli_semantic_exit_codes(tmp_path):
    from click.testing import CliRunner
    from autogis.adapters.cli import autogis
    runner = CliRunner()
    old = make_form(tmp_path, [("text", "A", "L")], name="o.xlsx")
    same = make_form(tmp_path, [("text", "A", "L")], name="s.xlsx")
    cosmetic = make_form(tmp_path, [("text", "A", "L2")], name="c.xlsx")
    newreq = make_form(tmp_path, [("text", "A", "L"),
                                  ("text", "B", "", "", "yes")], name="r.xlsx")
    removed = make_form(tmp_path, [("text", "Z", "L")], name="d.xlsx")

    assert runner.invoke(autogis, ["envmon", "diff-survey-schema", str(same),
                                   "--baseline-form", str(old)]).exit_code == 0
    assert runner.invoke(autogis, ["envmon", "diff-survey-schema",
                                   str(cosmetic), "--baseline-form",
                                   str(old)]).exit_code == 0     # safe only
    assert runner.invoke(autogis, ["envmon", "diff-survey-schema", str(newreq),
                                   "--baseline-form", str(old)]).exit_code == 2
    assert runner.invoke(autogis, ["envmon", "diff-survey-schema", str(removed),
                                   "--baseline-form", str(old)]).exit_code == 3


def test_diff_cli_layer_spec_and_json_report(tmp_path):
    import json
    from click.testing import CliRunner
    from autogis.adapters.cli import autogis
    f = make_form(tmp_path, [("text", "OnlyInForm", "")])
    spec = _write_yaml(tmp_path, "spec.yaml", {
        "layer_name": "L",
        "fields": [{"name": "OnlyInForm", "type": "esriFieldTypeString"}],
    })
    rpt = tmp_path / "out.json"
    r = CliRunner().invoke(autogis, ["envmon", "diff-survey-schema", str(f),
                                     "--layer-spec", str(spec),
                                     "--report", str(rpt)])
    assert r.exit_code == 0
    assert json.loads(rpt.read_text(encoding="utf-8")) == []


def test_new_commands_registered_in_capabilities():
    from autogis.runtime.capabilities import TOOLS, Runtime, registry
    assert TOOLS["validate-survey-form"] is Runtime.CLOUD
    assert TOOLS["diff-survey-schema"] is Runtime.CLOUD
    names = {c.command for c in registry()}
    assert {"validate-survey-form", "diff-survey-schema"} <= names
```

(If `registry()` has a different accessor name, use the one `_REGISTRY_SEED` feeds — check `capabilities.py` when editing.)

- [ ] **Step 2:** run → FAIL
- [ ] **Step 3: implement CLI** (insert after `build_survey_form_cmd`):

```python
@envmon.command("validate-survey-form")
@click.argument("form_xlsx", type=click.Path(exists=True))
@click.option("--site-config", "site_path", default=None,
              type=click.Path(exists=True), help="Site config YAML.")
@click.option("--event-config", "event_path", default=None,
              type=click.Path(exists=True), help="Event config YAML.")
@click.option("--analyte-dict", "analytes_path", default=None,
              type=click.Path(exists=True), help="Analyte dictionary YAML.")
@qa_report_options
def validate_survey_form_cmd(form_xlsx, site_path, event_path, analytes_path,
                             report, fail_on):
    """S123-1.1: static XLSForm validation — structure, choices, references,
    the ADR-0113 SampleID contract, and config cross-checks."""
    import yaml
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.survey_schema import read_xlsform, validate_form
    try:
        schema = read_xlsform(form_xlsx)
    except Exception as exc:
        raise click.ClickException(f"cannot read XLSForm: {exc}")

    def _load(p):
        return yaml.safe_load(open(p, encoding="utf-8")) if p else None

    qa = QACollector()
    validate_form(schema, qa,
                  event_config=_load(event_path),
                  site_config=_load(site_path),
                  analyte_dict=_load(analytes_path))
    _render_qa(qa, report, fail_on)


_DIFF_REVIEW_EXIT = 2
_DIFF_DESTRUCTIVE_EXIT = 3


@envmon.command("diff-survey-schema")
@click.argument("form_xlsx", type=click.Path(exists=True))
@click.option("--baseline-form", "baseline_path", default=None,
              type=click.Path(exists=True),
              help="Previous XLSForm .xlsx to diff against.")
@click.option("--layer-spec", "spec_path", default=None,
              type=click.Path(exists=True),
              help="Saved feature-layer spec YAML/JSON (audit-schema format).")
@click.option("--report", default=None, type=click.Path(),
              help="Write the change list to PATH (.json or .md).")
def diff_survey_schema_cmd(form_xlsx, baseline_path, spec_path, report):
    """S123-1.2: classify XLSForm changes as safe / review-required /
    destructive. Exit 0 none-or-safe, 2 review-required, 3 destructive."""
    import dataclasses
    import json
    import yaml
    from autogis.core.envmon.survey_schema import (
        CLASS_DESTRUCTIVE, CLASS_REVIEW, diff_forms, diff_form_vs_layer,
        read_xlsform, worst_classification,
    )
    if not baseline_path and not spec_path:
        raise click.UsageError(
            "provide --baseline-form and/or --layer-spec to diff against")
    try:
        new = read_xlsform(form_xlsx)
        changes = []
        if baseline_path:
            changes += diff_forms(read_xlsform(baseline_path), new)
        if spec_path:
            spec = yaml.safe_load(open(spec_path, encoding="utf-8"))
            changes += diff_form_vs_layer(new, spec)
    except click.ClickException:
        raise
    except Exception as exc:
        raise click.ClickException(f"cannot diff: {exc}")

    for c in changes:
        click.echo(f"[{c.classification.upper():>15}] {c.kind}: {c.name} — "
                   f"{c.detail}")
    worst = worst_classification(changes)
    click.echo(f"Changes: {len(changes)}  Worst: {worst or 'none'}")
    if report:
        p = Path(report)
        rows = [dataclasses.asdict(c) for c in changes]
        if p.suffix == ".json":
            p.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        else:
            lines = ["| class | kind | name | detail |", "|---|---|---|---|"]
            lines += [f"| {c.classification} | {c.kind} | {c.name} | "
                      f"{c.detail} |" for c in changes]
            p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        click.echo(f"Wrote report: {p}")
    if worst == CLASS_DESTRUCTIVE:
        raise SystemExit(_DIFF_DESTRUCTIVE_EXIT)
    if worst == CLASS_REVIEW:
        raise SystemExit(_DIFF_REVIEW_EXIT)
```

**capabilities.py:** add to `TOOLS`:

```python
    "validate-survey-form": Runtime.CLOUD,
    "diff-survey-schema": Runtime.CLOUD,
```

and to `_REGISTRY_SEED` (next to the `build-survey-form` row):

```python
    ("validate-survey-form", "ValidateSurveyForm", "S123-1.1", "CLOUD",
     "stable", "field",
     "Static XLSForm validation: structure, choices, references, the "
     "ADR-0113 SampleID contract, and site/event config cross-checks."),
    ("diff-survey-schema", "DiffSurveySchema", "S123-1.2", "CLOUD",
     "stable", "field",
     "Classify XLSForm changes vs a baseline form and/or a saved "
     "feature-layer spec as safe, review-required, or destructive."),
```

- [ ] **Step 4:** rerun test file → PASS. Also run `PYTHONPATH="$PWD" python -m pytest tests/ -q -k "capabilit or list_tools"` — fix any pinned tool-count expectations the two new rows shift.
- [ ] **Step 5:** `git add -u && git commit -m "feat(cli): validate-survey-form + diff-survey-schema commands (S123 Phase 1)"`

---

### Task 7: ADR, decision log, full suite, spec-checker

- [ ] **Step 1:** verify ADR number free: `ls docs/adr | tail -3` and `gh pr list -R 0bnoxide/AutoGIS --state open --json number,files` → expected next: **0114**. Write `docs/adr/0114-survey123-form-validation-and-schema-drift.md`: Context (no XLSForm reader existed; Phase 1 gate), Decision (survey_schema.py module; validator severities incl. SampleID ERROR; taxonomy table copied from spec; audit_schema reuse + domain-name normalization; exit codes 0/2/3; capabilities rows S123-1.1/1.2), Consequences (read-only commands, base install, no migration; gate met → Phase 2 remains user-gated), Related (ADR-0112, ADR-0113, ADR-0021, spec + plan paths). Add the index row in `docs/adr/README.md` after 0113's.
- [ ] **Step 2:** append to `docs/adr/logs/2026-07-25-agent-decisions.md`: decision = Phase 1 started on user "continue" + design/spec approvals; taxonomy severity choices (choice-removed=review vs code-changed=destructive via label-match heuristic); revisit if = owner wants a stricter taxonomy or rename detection.
- [ ] **Step 3:** full suite: `PYTHONPATH="$PWD" python -m pytest -q` → green (2602 + ~30 new).
- [ ] **Step 4:** dispatch `envmon-spec-checker` agent on changed files (survey_schema.py, cli.py, capabilities.py) — read-only reminder in prompt; fix flags.
- [ ] **Step 5:** `git add docs/adr && git commit -m "docs(adr): ADR-0114 Survey123 form validation and schema drift"`

---

### Task 8: PR

- [ ] **Step 1:** `git push -u origin worktree-survey123-phase1-form-validation`; `gh pr create` — title `feat(envmon): Survey123 Phase 1 — validate-survey-form + diff-survey-schema (ADR-0114)`; body: spec/ADR refs, both commands, taxonomy summary, round-trip lockstep test, exit-code contract, suite evidence, gate mapping (Phase 1 gate met from saved artifacts; no portal; base install), standard footer. Do NOT self-merge.
- [ ] **Step 2:** run `pr-reviewer` agent on the PR; fix findings; comment outcome.
- [ ] **Step 3:** `memory_write` STATUS to `collab:autogis` (Phase 1 open as PR #N, supersedes nothing; Phase 2 user-gated) + update `survey123-addon-track-status` memory.
