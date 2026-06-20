"""Callout templates — build the cell grid for a table-style callout.

Pure Python: a template turns one location's current-event results into a
list of CellSpec objects (row/col grid with text + style classes). Geometry
and placement live in callout_geometry / callout_collision; arcpy feature
writing lives in build_figure_dataset.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

STYLE_TITLE = "TITLE"
STYLE_GROUP = "GROUP_HEADER"
STYLE_LABEL = "LABEL"
STYLE_RESULT = "RESULT"


@dataclass
class CellSpec:
    row: int
    col: int
    text: str
    raw: str = ""
    style_class: str = STYLE_RESULT
    display_color_class: str = ""
    row_span: int = 1
    col_span: int = 1
    is_header: bool = False
    is_group_header: bool = False
    is_analyte_name: bool = False
    is_result_value: bool = False
    is_exceedance: bool = False
    is_detected: bool = False
    is_nondetect: bool = False
    is_not_sampled: bool = False
    h_align: str = "LEFT"
    source_analyte: str = ""


@dataclass
class CalloutTable:
    location_id: str
    sample_id: str
    cells: List[CellSpec] = field(default_factory=list)
    n_rows: int = 0
    n_cols: int = 0

    def column_char_widths(self, pad: int = 2) -> List[int]:
        widths = [0] * self.n_cols
        for c in self.cells:
            if c.col_span == 1:
                widths[c.col - 1] = max(widths[c.col - 1], len(c.text) + pad)
        # spanning cells may still force a minimum total width
        for c in self.cells:
            if c.col_span > 1:
                total = sum(widths[c.col - 1:c.col - 1 + c.col_span])
                need = len(c.text) + pad
                if need > total and widths:
                    widths[c.col - 1] += need - total
        return [max(w, 3) for w in widths]


def _result_cell(row: int, col: int, res: Optional[dict],
                 analyte: str) -> CellSpec:
    """res: result dict from the current-event dataset (keys DisplayText,
    DisplayColorClass, flag ints). None means the analyte is missing for this
    location — shown explicitly as '--', never silently dropped."""
    if res is None:
        return CellSpec(row=row, col=col, text="--", raw="",
                        style_class=STYLE_RESULT,
                        display_color_class="NOT_ANALYZED",
                        is_result_value=True, source_analyte=analyte,
                        h_align="RIGHT")
    return CellSpec(
        row=row, col=col, text=str(res.get("DisplayText", "")),
        raw=str(res.get("ResultRawText", "")),
        style_class=STYLE_RESULT,
        display_color_class=res.get("DisplayColorClass", ""),
        is_result_value=True,
        is_exceedance=bool(res.get("ExceedsScreeningLevel")),
        is_detected=bool(res.get("IsDetected")),
        is_nondetect=bool(res.get("IsNonDetect")),
        is_not_sampled=bool(res.get("IsNotSampled")),
        source_analyte=analyte, h_align="RIGHT")


def build_callout_rows(record: dict, figure_spec, analyte_dictionary: dict,
                       analytes: Optional[List[str]] = None) -> CalloutTable:
    """Build the cell grid for one location.

    record: {
      "LocationID", "SampleID", "SampleDate" (str), "DepthIntervalText",
      "results": {canonical_analyte: result-dict}
    }
    figure_spec: FigureSpec (or dict-like) whose callout_template defines
      template_id, optional row plan and group structure.
    """
    spec = figure_spec.get("callout_template") if hasattr(figure_spec, "get") \
        else figure_spec["callout_template"]
    template_id = spec.get("template_id", "COMPACT_KV")
    if analytes is None:
        analytes = list(record.get("results", {}).keys())
    abbrev = {a: analyte_dictionary.get(a, {}).get("abbreviation", a)
              for a in analytes}
    results: Dict[str, dict] = record.get("results", {})
    t = CalloutTable(location_id=record.get("LocationID", ""),
                     sample_id=record.get("SampleID", ""))
    row = 1

    def title(text: str, span: int = 2):
        nonlocal row
        t.cells.append(CellSpec(row=row, col=1, text=text,
                                style_class=STYLE_TITLE, col_span=span,
                                is_header=True, h_align="CENTER"))
        row += 1

    def label_value(label: str, value: str):
        nonlocal row
        t.cells.append(CellSpec(row=row, col=1, text=label,
                                style_class=STYLE_LABEL, is_header=True))
        t.cells.append(CellSpec(row=row, col=2, text=value,
                                style_class=STYLE_RESULT, h_align="RIGHT"))
        row += 1

    def group(text: str, span: int = 2):
        nonlocal row
        t.cells.append(CellSpec(row=row, col=1, text=text,
                                style_class=STYLE_GROUP, col_span=span,
                                is_group_header=True, h_align="CENTER"))
        row += 1

    def analyte_row(a: str):
        nonlocal row
        t.cells.append(CellSpec(row=row, col=1, text=abbrev[a],
                                style_class=STYLE_LABEL, is_analyte_name=True,
                                source_analyte=a))
        t.cells.append(_result_cell(row, 2, results.get(a), a))
        row += 1

    groups = spec.get("groups")  # [{header, analytes:[...]}]

    if template_id in ("CKG_GW", "COMPACT_KV", "METALS", "IBI",
                       "CUSTOM_ANALYTICAL"):
        title(record.get("LocationID", ""))
        for a in analytes:
            analyte_row(a)
    elif template_id == "ZT42_GW":
        label_value("WELL ID", record.get("LocationID", ""))
        label_value("DATE", record.get("SampleDate", ""))
        for g in groups or [{"header": "", "analytes": analytes}]:
            if g.get("header"):
                group(g["header"])
            for a in g.get("analytes", []):
                if a in abbrev:
                    analyte_row(a)
    elif template_id == "ZT42_SOIL":
        label_value("SAMPLE ID", record.get("SampleID", ""))
        label_value("DEPTH", record.get("DepthIntervalText", ""))
        label_value("DATE", record.get("SampleDate", ""))
        for g in groups or [{"header": "", "analytes": analytes}]:
            if g.get("header"):
                group(g["header"])
            for a in g.get("analytes", []):
                if a in abbrev:
                    analyte_row(a)
    else:
        raise ValueError(f"unknown callout template_id '{template_id}'")

    t.n_rows = row - 1
    t.n_cols = max((c.col + c.col_span - 1 for c in t.cells), default=0)
    return t
