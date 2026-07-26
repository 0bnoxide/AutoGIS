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
