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
