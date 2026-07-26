"""survey_schema.py — XLSForm reader, validator, and schema-drift classifier.

Survey123 add-on roadmap Phase 1 (ADR-0112; decision record ADR-0114).
openpyxl + stdlib only — no arcpy, no arcgis. The form-vs-layer leg reuses
autogis.core.agol.audit_schema.diff_schema (itself arcgis-free).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
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
        if self.base.startswith("select_") and len(parts) > 1:
            return parts[1]
        return ""


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
    wb = openpyxl.load_workbook(str(path), data_only=True)
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
    """Static XLSForm validation (ADR-0114 checks 1-13). Appends QARecords."""
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
        unknown = sorted({a for names in groups.values()
                          if isinstance(names, list) for a in names} - known)
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
