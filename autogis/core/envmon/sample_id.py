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

#: qc_class() value for an ID that parses as a lifecycle identity with no QC
#: suffix. Distinct from None, which means "carries no QC signal at all".
PRIMARY = "primary"

#: Fallback duplicate markers, used only when a parser profile declares no
#: ``duplicate_markers`` of its own (the shipped profiles declare
#: ``["DUP", "-D", "FD"]``, which is deliberately not this list — a bare "FD"
#: matches too much without a delimiter). table_normalizer.
#: detect_duplicate_sample reads it from here so the fallback lives in one
#: place.
DEFAULT_DUPLICATE_MARKERS = ("DUP", "-D", " FD", "FD-")


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
    dateless submission (produces the NODATE form with a uuid6
    disambiguator). qc: bare code without separator ("FD", not "-fd").
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
    if m:
        parts = _split_rest(m.group("loc"), m.group("date"), m.group("rest"))
        if parts is not None:
            return parts
        # fall through: a NODATE ID whose location ends in a dash-delimited
        # 8-digit run matches the dated regex first with an invalid rest
    m = _NODATE_RE.match(sample_id)
    if m:
        return _split_rest(m.group("loc"), "", m.group("rest"))
    return None


def _split_rest(loc: str, date_compact: str,
                rest: str) -> Optional[SampleIdParts]:
    qc = ""
    rest_lower = rest.lower()
    for suffix in sorted(QC_SUFFIXES, key=len, reverse=True):
        if rest_lower.endswith(suffix) and len(rest) > len(suffix):
            qc = rest[-len(suffix) + 1:].upper()
            rest = rest[:-len(suffix)]
            break
    if not rest or "-" in rest:
        return None
    return SampleIdParts(location_id=loc, date_compact=date_compact,
                         matrix=rest, qc=qc)


def strip_qc(sample_id: str) -> str:
    """The primary identity a QC SampleID derives from.

    Returns *sample_id* unchanged when it is not a lifecycle identity or
    carries no QC suffix. For the NODATE form the result is well-formed but
    will not resolve to a real primary — the uuid disambiguator differs per
    submission — so callers get a visible rpd_parent_not_found rather than a
    silent mispair.
    """
    parts = parse_sample_id(sample_id)
    if parts is None or not parts.qc:
        return sample_id
    return sample_id[: -(len(parts.qc) + 1)]


def qc_class(sample_id: str,
             duplicate_markers: Optional[list] = None) -> Optional[str]:
    """Classify a SampleID as a QC type, PRIMARY, or None.

    A lifecycle identity answers from its own suffix (so ``-FD``, ``-FD-A``
    and ``-FD-B`` all class as ``field_duplicate``). Otherwise the parser
    profile's ``duplicate_markers`` decide — this repo's own labs ship
    ``-DUP``/``-D`` identities, which are duplicates but not lifecycle IDs.
    A marker is honoured inside the *location* segment too (``MW-1-DUP-…``
    parses as a lifecycle ID whose location happens to carry the marker);
    ``table_normalizer.detect_duplicate_sample`` matches markers the same way,
    so that spelling is one this repo already expects from labs.

    Markers can only say "duplicate", not which kind, so a marked ID classes
    as ``field_duplicate``: a lab's ``-DUP`` is the reported half of a field
    duplicate. A lifecycle ``-LD`` stays ``lab_duplicate`` — a lab split is a
    different sample from a field duplicate, so the two must not pair.

    None means "no recognizable QC signal", never "primary". Callers must not
    treat it as primary; the reconciliation guard lets None through only
    because an unclassifiable ID carries no evidence either way.
    """
    markers = duplicate_markers or DEFAULT_DUPLICATE_MARKERS

    def marked(text: str) -> bool:
        upper = (text or "").upper()
        return any(str(m).upper() in upper for m in markers)

    parts = parse_sample_id(sample_id)
    if parts is not None:
        if parts.qc:
            return QC_SUFFIXES[f"-{parts.qc.lower()}"]
        # suffix wins over markers; only a bare lifecycle ID consults them
        return "field_duplicate" if marked(parts.location_id) else PRIMARY
    return "field_duplicate" if marked(sample_id) else None


def xform_sample_id_calc(well_field: str = "WellID",
                         date_field: str = "SamplingDate",
                         matrix_field: str = "Matrix",
                         qa_flags_field: str = "QAFlags",
                         dup_flag: str = "field_dup") -> str:
    """XForm calculate for the SampleID question — the device-side rendering
    of LIFECYCLE_FORMAT. Defaults are the survey field names the form
    builder emits today; the duplicate leg reads the QAFlags choice the form
    has offered since ADR-0021 rather than a second question.

    ponytail: no test can execute a real XForm, so the two renderings are
    coupled by a test that evaluates this one expression shape against
    build_sample_id; upgrade path is a real XForm evaluator if the expression
    ever grows past concat/if/selected.
    """
    return (
        f'concat(${{{well_field}}}, "-", '
        f'format-date(${{{date_field}}}, "%Y%m%d"), '
        f'"-", ${{{matrix_field}}}, '
        f'if(selected(${{{qa_flags_field}}}, "{dup_flag}"), "-FD", ""))'
    )
