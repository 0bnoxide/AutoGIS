"""reconcile_event.py — Tool: five-source monitoring-event reconciliation.

Presence matrix over plan -> field -> COC -> lab -> GDB (approved design:
docs/superpowers/specs/2026-07-30-survey123-phase3-event-reconciliation-design.md).
arcpy-free: consumes plain rows/records loaded by the CLI adapter.
Exact-only matching (D7); one ID policy (D9): sample_id module + uppercase.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .sample_id import PRIMARY, QC_SUFFIXES, parse_sample_id, qc_class

SOURCES = ("plan", "field", "coc", "lab", "gdb")
REQUIRED = "required"
OPTIONAL = "optional"
FORBIDDEN = "forbidden"

OUTCOME_RECONCILED = "reconciled"
OUTCOME_STALLED = "stalled"
OUTCOME_NOT_COLLECTED = "not_collected"
OUTCOME_ORPHAN = "orphan"
OUTCOME_DETAIL_CONFLICT = "detail_conflict"
OUTCOME_NEEDS_REVIEW = "needs_review"
# Precedence: earlier wins the headline (spec §4.2).
OUTCOME_ORDER = (OUTCOME_NEEDS_REVIEW, OUTCOME_ORPHAN, OUTCOME_NOT_COLLECTED,
                 OUTCOME_STALLED, OUTCOME_DETAIL_CONFLICT, OUTCOME_RECONCILED)

_ALL_REQUIRED_DOWNSTREAM = {"plan": OPTIONAL, "field": REQUIRED, "coc": REQUIRED,
                            "lab": REQUIRED, "gdb": REQUIRED}
# Expected presence by QC class (D5). Plan is never REQUIRED (D3 cascade).
# ponytail: table covers the classes sample_id knows; anything else falls to
# UNKNOWN_QC_MASK (all OPTIONAL) so a new suffix can never break balance.
QC_MASKS: Dict[str, Dict[str, str]] = {
    PRIMARY: dict(_ALL_REQUIRED_DOWNSTREAM),
    "field_duplicate": dict(_ALL_REQUIRED_DOWNSTREAM),          # field duplicate travels the full chain
    "trip_blank": {"plan": OPTIONAL, "field": FORBIDDEN, "coc": REQUIRED,
           "lab": REQUIRED, "gdb": OPTIONAL},      # trip blank: never a field entry
    "field_blank": {"plan": OPTIONAL, "field": OPTIONAL, "coc": REQUIRED,
           "lab": REQUIRED, "gdb": OPTIONAL},      # equipment blank
    "method_blank": {"plan": FORBIDDEN, "field": FORBIDDEN, "coc": FORBIDDEN,
           "lab": REQUIRED, "gdb": OPTIONAL},      # lab method blank
    "matrix_spike": {"plan": FORBIDDEN, "field": FORBIDDEN, "coc": FORBIDDEN,
           "lab": REQUIRED, "gdb": OPTIONAL},
    "matrix_spike_duplicate": {"plan": FORBIDDEN, "field": FORBIDDEN, "coc": FORBIDDEN,
            "lab": REQUIRED, "gdb": OPTIONAL},
    "lab_duplicate": {"plan": FORBIDDEN, "field": FORBIDDEN, "coc": FORBIDDEN,
            "lab": REQUIRED, "gdb": OPTIONAL},
}
UNKNOWN_QC_MASK: Dict[str, str] = {s: OPTIONAL for s in SOURCES}


def normalize_key(sample_id: str) -> str:
    """One ID policy (D9): trim + uppercase. Structure comes from sample_id."""
    return (sample_id or "").strip().upper()


def default_mask(sample_id: str) -> Dict[str, str]:
    cls = qc_class(normalize_key(sample_id))
    if cls is None and parse_sample_id(normalize_key(sample_id)) is None:
        return dict(UNKNOWN_QC_MASK)   # not a lifecycle identity at all
    return dict(QC_MASKS.get(cls or PRIMARY, UNKNOWN_QC_MASK))


@dataclass
class SourceRow:
    """One observation of a sample in one source."""
    sample_id: str
    attrs: dict


@dataclass
class GridRow:
    key: str
    raw_ids: Dict[str, str] = field(default_factory=dict)      # source -> raw id seen
    present: Dict[str, bool] = field(default_factory=dict)
    attrs: Dict[str, dict] = field(default_factory=dict)       # source -> attrs
    mask: Dict[str, str] = field(default_factory=dict)
    origin: str = ""
    outcome: str = ""
    codes: List[str] = field(default_factory=list)
    last_stage: str = ""
