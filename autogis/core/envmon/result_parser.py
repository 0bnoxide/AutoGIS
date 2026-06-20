"""Result-value, date and analyte-name parsing.

This is the heart of the import pipeline. Raw Excel text is preserved on every
parsed record; numeric coercion never replaces the raw value (spec: "Keep raw
values separate from parsed values").
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import List, Optional

# ---------------------------------------------------------------------------
# Status / qualifier vocabularies. Site-specific additions belong in config,
# not here (see parser profile key `extra_status_codes`).
# ---------------------------------------------------------------------------
FORMULA_ERRORS = {"#VALUE!", "#DIV/0!", "#N/A", "#REF!", "#NAME?", "#NUM!", "#NULL!"}

STATUS_CODES = {
    "NA": "NOT_ANALYZED",      # ambiguous: may mean not applicable; QA note added
    "NS": "NOT_SAMPLED",
    "NM": "NOT_MEASURED",
    "DRY": "DRY",
    "ND": "NONDETECT",         # nondetect without a stated reporting limit
    "-": "BLANK",
    "--": "BLANK",
}

# Common lab qualifiers and the flags they imply.
QUALIFIER_FLAGS = {
    "U": {"is_nondetect": True},
    "J": {"is_estimated": True},
    "D": {"is_diluted": True},
    "R": {"is_rejected": True},
    "UJ": {"is_nondetect": True, "is_estimated": True},
    "DJ": {"is_diluted": True, "is_estimated": True},
    "B": {},   # blank contamination: recorded, no flag change
    "E": {"is_estimated": True},
}

_NUM = r"\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d*\.\d+|\d+"
_RE_NONDETECT = re.compile(rf"^<\s*({_NUM})\s*([A-Za-z][A-Za-z\s]*)?$")
_RE_NUMERIC = re.compile(rf"^({_NUM})(?:[eE]([+-]?\d+))?\s*([A-Za-z][A-Za-z\s]*)?$")
_RE_FOOTNOTE = re.compile(rf"^({_NUM})\s+(\d{{1,2}})$")
_RE_WS = re.compile(r"[\s\u00a0\r\n]+")


@dataclass
class ParsedResult:
    raw_text: str
    normalized_text: str = ""
    result_numeric: Optional[float] = None
    reporting_limit: Optional[float] = None
    detection_limit: Optional[float] = None
    qualifier: str = ""
    qualifier_list: List[str] = field(default_factory=list)
    is_numeric: bool = False
    is_nondetect: bool = False
    is_detected: bool = False
    is_estimated: bool = False
    is_diluted: bool = False
    is_rejected: bool = False
    is_not_analyzed: bool = False
    is_not_sampled: bool = False
    is_not_measured: bool = False
    is_dry: bool = False
    is_blank: bool = False
    status_code: str = ""
    display_text: str = ""
    parse_warning: str = ""


def _clean(value) -> str:
    if value is None:
        return ""
    text = str(value)
    return _RE_WS.sub(" ", text).strip()


def _to_float(num_text: str) -> float:
    return float(num_text.replace(",", ""))


def _apply_qualifiers(parsed: ParsedResult, qual_text: str) -> None:
    quals = [q for q in re.split(r"[\s,/]+", qual_text.strip().upper()) if q]
    parsed.qualifier_list = quals
    parsed.qualifier = " ".join(quals)
    for q in quals:
        flags = QUALIFIER_FLAGS.get(q)
        if flags is None:
            # Try splitting compound qualifiers like "DJ" character-wise.
            sub = [c for c in q if c in QUALIFIER_FLAGS]
            if len(sub) == len(q):
                for c in sub:
                    for k, v in QUALIFIER_FLAGS[c].items():
                        setattr(parsed, k, v)
            else:
                parsed.parse_warning = (parsed.parse_warning + "; " if parsed.parse_warning
                                        else "") + f"unknown qualifier '{q}'"
            continue
        for k, v in flags.items():
            setattr(parsed, k, v)


def parse_result_value(raw_value, screening_context: bool = False) -> ParsedResult:
    """Parse one analytical-result cell.

    `screening_context=True` enables footnote stripping ("1,000 3" -> 1000)
    which is only legitimate on screening-level rows.
    """
    raw_text = "" if raw_value is None else str(raw_value)
    text = _clean(raw_value)
    p = ParsedResult(raw_text=raw_text, normalized_text=text, display_text=text)

    if text == "":
        p.is_blank = True
        p.status_code = "BLANK"
        return p

    upper = text.upper()

    if upper in FORMULA_ERRORS:
        p.status_code = "INVALID"
        p.parse_warning = f"formula error in source: {text}"
        return p

    if upper in STATUS_CODES:
        code = STATUS_CODES[upper]
        p.status_code = code
        p.is_not_analyzed = code == "NOT_ANALYZED"
        p.is_not_sampled = code == "NOT_SAMPLED"
        p.is_not_measured = code == "NOT_MEASURED"
        p.is_dry = code == "DRY"
        p.is_blank = code == "BLANK"
        if code == "NONDETECT":
            p.is_nondetect = True
            p.parse_warning = "nondetect 'nd' without reporting limit"
        if upper == "NA":
            p.parse_warning = "'NA' interpreted as NOT_ANALYZED; verify meaning"
        return p

    m = _RE_NONDETECT.match(text)
    if m:
        p.is_nondetect = True
        p.reporting_limit = _to_float(m.group(1))
        p.status_code = "NONDETECT"
        if m.group(2):
            _apply_qualifiers(p, m.group(2))
            p.is_nondetect = True  # "<x D" stays a nondetect
        p.normalized_text = f"<{m.group(1)}" + (f" {p.qualifier}" if p.qualifier else "")
        p.display_text = p.normalized_text
        return p

    m = _RE_FOOTNOTE.match(text)
    if m:
        if screening_context:
            p.is_numeric = True
            p.result_numeric = _to_float(m.group(1))
            p.status_code = "NUMERIC"
            p.parse_warning = f"footnote marker '{m.group(2)}' stripped from screening level"
            p.display_text = m.group(1)
            return p
        p.status_code = "UNPARSED"
        p.parse_warning = (f"value '{text}' looks like a number with a footnote "
                           f"marker outside a screening-level row; not coerced")
        return p

    m = _RE_NUMERIC.match(text)
    if m:
        num = _to_float(m.group(1))
        if m.group(2):
            num *= 10 ** int(m.group(2))
        p.is_numeric = True
        p.result_numeric = num
        p.status_code = "NUMERIC"
        if m.group(3):
            _apply_qualifiers(p, m.group(3))
        if p.is_nondetect:
            # e.g. "0.5 U": numeric with U qualifier is a nondetect at RL.
            p.reporting_limit = num
            p.result_numeric = None
            p.is_numeric = False
            p.status_code = "NONDETECT"
        else:
            p.is_detected = not p.is_rejected
        return p

    p.status_code = "UNPARSED"
    p.parse_warning = f"could not parse result value '{text}'"
    return p


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------
_DATE_FORMATS = ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%d-%b-%Y", "%d-%b-%y",
                 "%b %d, %Y", "%B %d, %Y", "%m-%d-%Y", "%Y/%m/%d")


def parse_excel_date(value, workbook_date_system: str = "1900") -> Optional[date]:
    """Convert datetimes, Excel serial numbers or common date strings to date.

    Returns None when the value is blank or cannot be interpreted; the caller
    is responsible for raising a QA record on None.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        serial = float(value)
        if serial <= 0:
            return None
        if workbook_date_system == "1904":
            base = datetime(1904, 1, 1)
        else:
            # 1899-12-30 base absorbs the fictitious 1900 leap day for
            # serials >= 61, matching openpyxl/Excel behaviour.
            base = datetime(1899, 12, 30)
        try:
            return (base + timedelta(days=serial)).date()
        except OverflowError:
            return None
    text = _clean(value)
    if not text or text.upper() in STATUS_CODES:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Analyte names
# ---------------------------------------------------------------------------
def _norm_key(name: str) -> str:
    text = _clean(name).casefold()
    text = text.replace("\u2013", "-").replace("\u2014", "-")  # en/em dashes
    text = re.sub(r"\s*\(\s*", " (", text)
    text = re.sub(r"\s{2,}", " ", text)
    # strip trailing footnote markers such as "benzene 1"
    text = re.sub(r"\s+\d{1,2}$", "", text)
    return text


def build_analyte_lookup(analyte_dictionary: dict) -> dict:
    """analyte_dictionary: {canonical_name: {aliases: [...], ...}} from config."""
    lookup = {}
    for canonical, entry in analyte_dictionary.items():
        keys = {canonical} | set(entry.get("aliases", []) or [])
        abbrev = entry.get("abbreviation")
        if abbrev:
            keys.add(abbrev)
        for k in keys:
            lookup[_norm_key(k)] = canonical
    return lookup


def normalize_analyte_name(raw_name: str, analyte_dictionary: dict) -> Optional[str]:
    """Return the canonical analyte name, or None when unknown (caller QAs)."""
    if not raw_name:
        return None
    lookup = analyte_dictionary.get("_lookup")
    if lookup is None:
        lookup = build_analyte_lookup(
            {k: v for k, v in analyte_dictionary.items() if not k.startswith("_")})
        analyte_dictionary["_lookup"] = lookup
    return lookup.get(_norm_key(raw_name))


# ---------------------------------------------------------------------------
# Display classification
# ---------------------------------------------------------------------------
def classify_display(parsed: ParsedResult, exceeds: Optional[bool]) -> str:
    if parsed.status_code in ("INVALID", "UNPARSED"):
        return "INVALID"
    if parsed.is_nondetect:
        return "NONDETECT"
    if parsed.is_not_sampled:
        return "NOT_SAMPLED"
    if parsed.is_not_measured or parsed.is_dry:
        return "NOT_MEASURED"
    if parsed.is_not_analyzed or parsed.is_blank:
        return "NOT_ANALYZED"
    if parsed.is_detected and exceeds:
        return "EXCEEDANCE"
    if parsed.is_detected:
        return "DETECTED"
    return "INVALID"


def evaluate_screening(parsed: ParsedResult,
                       screening_level: Optional[float]) -> Optional[bool]:
    """True/False for valid detected results vs a numeric screening level,
    None when the comparison is not legitimate (ND, status, missing SL)."""
    if not parsed.is_detected or parsed.result_numeric is None:
        return None
    if screening_level is None:
        return None
    return parsed.result_numeric > screening_level
