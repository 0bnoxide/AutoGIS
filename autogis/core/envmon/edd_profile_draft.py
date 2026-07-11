# autogis/core/envmon/edd_profile_draft.py
"""Heuristic LabEDDProfile drafting (Tool 2.3a).

Headless, arcpy-free counterpart to ``excel_workbook_inspector`` /
``propose_parser_profile`` (Tool 2.1), but for the *other* profile type:
flat lab EDD exports mapped by ``LabEDDProfile``. Inspects a sample EDD
file's header row(s), matches each canonical field against an explicit
synonym list, and proposes a profile dict ready for ``yaml.dump()``.

Design: docs/superpowers/specs/2026-07-08-lab-profile-drafting-tooling-design.md
(Slice 1). Confidence is deliberately coarse — a field is either CONFIRMED
(exactly one distinct header matched) or NEEDS_REVIEW (zero or ambiguous);
NEEDS_REVIEW fields are left out of ``columns`` so ``validate_edd_profile()``
flags missing required mappings loudly instead of passing an empty string.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

# Synonym lists are the load-bearing content. Keys are the canonical field
# names ``LabEDDProfile.resolve_column`` is asked for by the EDD importer;
# values are known header spellings, compared after ``_norm()`` (lowercase,
# alphanumerics only). Grown organically from real exports (TestAmerica is
# the one verified format); thin coverage for unseen labs is expected — see
# the spec's Known Limitation. A fully-CONFIRMED draft is still a DRAFT.
REQUIRED_FIELDS = (
    "sample_id", "location_id", "event_date", "matrix",
    "analyte", "result", "units", "qualifier", "reporting_limit",
)
OPTIONAL_FIELDS = (
    "method", "lab_sample_id", "depth_top_ft", "depth_bot_ft",
    "result_fraction", "qc_type", "dilution_factor", "method_name",
    "analysis_date", "limit_type", "lab_name", "prep_method", "prep_date",
    "result_basis", "method_speciation",
)

_SYNONYMS: dict[str, tuple[str, ...]] = {
    "sample_id": ("sampleid", "fieldsampleid", "syssamplecode", "samplename",
                  "sampleno", "samplenumber", "clientsampleid", "sysloccode"),
    "location_id": ("locationid", "location", "locid", "sysloccode",
                    "stationid", "station", "wellid", "monitoringpoint",
                    "pointid"),
    "event_date": ("eventdate", "colldate", "collectiondate", "sampledate",
                   "datecollected", "datesampled", "collectdate",
                   "sampleddate"),
    "matrix": ("matrix", "medium", "media", "samplematrix", "matrixcode"),
    "analyte": ("analyte", "analytename", "chemical", "chemicalname",
                "parameter", "compound", "constituent", "characteristicname"),
    "result": ("result", "resultvalue", "finalresult", "concentration",
               "resultmeasurevalue"),
    "units": ("units", "unit", "resultunit", "resultunits", "unitcode",
              "uom"),
    "qualifier": ("qualifier", "qualifiers", "qual", "labqualifier", "flag",
                  "flags", "validationqualifier"),
    "reporting_limit": ("reportinglimit", "rl", "pql", "quantitationlimit",
                        "loq", "reportingdetectionlimit"),
    "method": ("method", "analytmeth", "analysismethod", "methodcode",
               "analyticalmethod", "labmeth"),
    "lab_sample_id": ("labsampleid", "labid", "labsampid", "labsamplenumber",
                      "laboratorysampleid"),
    "depth_top_ft": ("topdepth", "depthtop", "depthtopft", "topdepthft",
                     "begindepth", "startdepth", "uppersampledepth"),
    "depth_bot_ft": ("botdepth", "bottomdepth", "depthbottom", "depthbotft",
                     "botdepthft", "enddepth", "lowersampledepth"),
    "result_fraction": ("resultfraction", "fraction", "samplefraction",
                        "totalordissolved", "resultsamplefraction"),
    "qc_type": ("qctype", "qccode", "sampletypecode", "qcsampletype"),
    "dilution_factor": ("dilutionfactor", "dilution", "dilfactor"),
    "method_name": ("methodname", "methoddescription", "methoddesc"),
    "analysis_date": ("analysisdate", "analyzeddate", "dateanalyzed",
                      "analysisdatetime"),
    "limit_type": ("limittype", "detectionlimittype"),
    "lab_name": ("labname", "laboratory", "laboratoryname"),
    "prep_method": ("prepmethod", "prepmeth", "preparationmethod",
                    "prepmethodcode"),
    "prep_date": ("prepdate", "preparationdate", "dateprepped",
                  "prepdatetime"),
    "result_basis": ("resultbasis", "basis", "weightbasis"),
    "method_speciation": ("methodspeciation", "speciation"),
}
assert set(_SYNONYMS) == set(REQUIRED_FIELDS) | set(OPTIONAL_FIELDS)


def _norm(header: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(header).lower())


@dataclass(frozen=True)
class DraftedField:
    canonical_name: str
    status: Literal["CONFIRMED", "NEEDS_REVIEW"]
    matched_column: Optional[str]        # set iff CONFIRMED
    candidates: tuple[str, ...]          # >1 iff ambiguous; empty iff zero-match


@dataclass(frozen=True)
class DraftedProfile:
    format: Literal["flat_csv", "two_tab_xlsx"]
    fields: tuple[DraftedField, ...]
    encoding: str = "utf-8"
    sample_sheet: Optional[str] = None   # two_tab_xlsx only
    result_sheet: Optional[str] = None   # two_tab_xlsx only
    notes: tuple[str, ...] = field(default=())   # profile-level review flags


def _match_fields(header_sets: list[list[str]]) -> tuple[DraftedField, ...]:
    """Match every canonical field against each header row independently.

    Candidates are deduplicated by exact header name across sheets, so a
    column appearing on both sheets of a two_tab file (as the importer's
    merge-then-lookup model expects) still counts as one unambiguous match.
    """
    out: list[DraftedField] = []
    for canonical in REQUIRED_FIELDS + OPTIONAL_FIELDS:
        synonyms = _SYNONYMS[canonical]
        matched: list[str] = []
        for headers in header_sets:
            for h in headers:
                if _norm(h) in synonyms and h not in matched:
                    matched.append(h)
        if len(matched) == 1:
            out.append(DraftedField(canonical, "CONFIRMED",
                                    matched[0], tuple(matched)))
        else:
            out.append(DraftedField(canonical, "NEEDS_REVIEW",
                                    None, tuple(matched)))
    return tuple(out)


def _csv_headers(path: Path) -> tuple[list[str], str]:
    """(header row, detected encoding). utf-8-sig iff the file has a BOM."""
    encoding = ("utf-8-sig"
                if path.read_bytes()[:3] == b"\xef\xbb\xbf" else "utf-8")
    with path.open(newline="", encoding=encoding) as fh:
        header = next(csv.reader(fh), None)
    if not header or not any(str(h).strip() for h in header):
        raise ValueError(f"No header row found in {path}")
    return [str(h) for h in header], encoding


def _xlsx_sheet_headers(path: Path) -> dict[str, list[str]]:
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        out: dict[str, list[str]] = {}
        for ws in wb.worksheets:
            row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True),
                       None) or ()
            out[ws.title] = [str(h) for h in row if h is not None
                             and str(h).strip()]
        return out
    finally:
        wb.close()


def draft_edd_profile(sample_path: Path) -> DraftedProfile:
    """Inspect a sample EDD file and propose a column mapping.

    Detects flat_csv vs two_tab_xlsx from the file extension and (for xlsx)
    sheet layout. Raises ValueError on an empty/headerless file.
    """
    path = Path(sample_path)
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        sheets = _xlsx_sheet_headers(path)
        populated = {n: h for n, h in sheets.items() if h}
        if not populated:
            raise ValueError(f"No header row found on any sheet of {path}")
        notes: list[str] = []
        by_norm = {_norm(n): n for n in populated}
        sample_sheet = by_norm.get("samples") or by_norm.get("sample")
        result_sheet = by_norm.get("results") or by_norm.get("result")
        if sample_sheet is None or result_sheet is None:
            names = list(populated)
            if len(names) >= 2:
                sample_sheet, result_sheet = names[0], names[1]
                notes.append(
                    f"Default Samples/Results sheet names not found; guessed "
                    f"sample_sheet={sample_sheet!r}, "
                    f"result_sheet={result_sheet!r} from sheet order — VERIFY")
            else:
                # ponytail: single-sheet xlsx has no dedicated flat format;
                # two_tab_xlsx with both sheets set to the same name is an
                # identity merge in _read_two_tab_xlsx, so it reads correctly.
                sample_sheet = result_sheet = names[0]
                notes.append(
                    f"Single-sheet workbook: sample_sheet and result_sheet "
                    f"both set to {sample_sheet!r} (identity merge)")
        return DraftedProfile(
            format="two_tab_xlsx",
            fields=_match_fields([populated[sample_sheet],
                                  populated[result_sheet]]),
            sample_sheet=sample_sheet,
            result_sheet=result_sheet,
            notes=tuple(notes),
        )
    headers, encoding = _csv_headers(path)
    return DraftedProfile(format="flat_csv",
                          fields=_match_fields([headers]),
                          encoding=encoding)


def drafted_profile_to_yaml_dict(drafted: DraftedProfile, profile_id: str,
                                 lab_name: str) -> dict:
    """Assemble a LabEDDProfile-shaped dict from a DraftedProfile, ready for
    yaml.dump(). NEEDS_REVIEW fields are omitted from ``columns`` (so
    ``validate_edd_profile`` flags missing required mappings) and listed as
    ``_TODO`` entries with their candidates, same convention as
    ``propose_parser_profile``."""
    columns = {f.canonical_name: f.matched_column
               for f in drafted.fields if f.status == "CONFIRMED"}
    todos = list(drafted.notes)
    for f in drafted.fields:
        if f.status == "CONFIRMED":
            continue
        required = f.canonical_name in REQUIRED_FIELDS
        if f.candidates:
            todos.append(
                f"{f.canonical_name}"
                f"{' (REQUIRED)' if required else ''}: ambiguous — "
                f"candidates: {', '.join(f.candidates)}")
        elif required:
            todos.append(f"{f.canonical_name} (REQUIRED): no match found — "
                         f"map manually")
    out: dict = {
        "profile_id": profile_id,
        "profile_description": ("DRAFT auto-proposed from sample EDD "
                                "headers — review before use"),
        "lab_name": lab_name,
        "format": drafted.format,
        "date_format": "%m/%d/%Y",
        "encoding": drafted.encoding,
        "columns": columns,
        "matrix_map": {},
        "nondetect_qualifiers": ["U", "UJ"],
    }
    if drafted.format == "two_tab_xlsx":
        out["sample_sheet"] = drafted.sample_sheet
        out["result_sheet"] = drafted.result_sheet
    out["_TODO"] = todos or ["REVIEW EVERY MAPPING — heuristic draft; "
                             "populate matrix_map from real data"]
    return out
