"""reconcile_event.py — Tool: five-source monitoring-event reconciliation.

Presence matrix over plan -> field -> COC -> lab -> GDB (approved design:
docs/superpowers/specs/2026-07-30-survey123-phase3-event-reconciliation-design.md).
arcpy-free: consumes plain rows/records loaded by the CLI adapter.
Exact-only matching (D7); one ID policy (D9): sample_id module + uppercase.
"""
from __future__ import annotations

import csv as _csv
import difflib
from dataclasses import dataclass, field
from pathlib import Path
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
           "lab": REQUIRED, "gdb": OPTIONAL},      # field blank
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
    normalized = normalize_key(sample_id)
    # Non-lifecycle IDs (even with duplicate markers) get all-optional.
    if parse_sample_id(normalized) is None:
        return dict(UNKNOWN_QC_MASK)
    cls = qc_class(normalized)
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


def build_grid(legs: Dict[str, List[SourceRow]], *,
               overrides: Optional[dict] = None) -> Dict[str, GridRow]:
    overrides = overrides or {}
    provided = set(legs)
    grid: Dict[str, GridRow] = {}
    for source in SOURCES:
        for obs in legs.get(source, []):
            key = normalize_key(obs.sample_id)
            if not key:
                continue    # CLI routes id-less sample-form rows separately (§4.4)
            row = grid.get(key)
            if row is None:
                row = GridRow(key=key,
                              present={s: False for s in SOURCES},
                              mask=default_mask(key))
                grid[key] = row
            if row.present[source]:
                if source == "coc":
                    if (obs.attrs.get("coc_number")
                            and obs.attrs["coc_number"] != row.attrs["coc"].get("coc_number")
                            and "multi_coc" not in row.codes):
                        row.codes.append("multi_coc")
                elif dict(obs.attrs) != row.attrs[source]:
                    # Same sample seen again in the same source with different
                    # attributes: a conflicting duplicate, never silently
                    # dropped (§1 contract). An identical repeat (sync retry)
                    # stays ignored.
                    code = f"duplicate_in_{source}"
                    if code not in row.codes:
                        row.codes.append(code)
                continue    # first observation's attrs win
            row.present[source] = True
            row.raw_ids[source] = obs.sample_id
            row.attrs[source] = dict(obs.attrs)
    for row in grid.values():
        for s in SOURCES:
            if s not in provided:
                row.mask[s] = OPTIONAL          # omitted leg is never judged
        for s, v in overrides.get(row.key, {}).items():
            if s in provided:
                row.mask[s] = v
    return grid


_DATE_KEYS = ("event_date", "SampleDate", "sample_date", "SamplingDate")
_LOC_KEYS = ("location_id", "LocationID")
_MATRIX_KEYS = ("matrix", "Matrix")


def _norm(v) -> str:
    return str(v or "").strip().upper()


def _get(attrs: dict, keys) -> str:
    for k in keys:
        if attrs.get(k) not in (None, ""):
            return str(attrs[k])
    return ""


def _dates_match(a: str, b: str) -> bool:
    def datepart(s: str) -> str:
        s = s.strip()[:10].replace("-", "").replace("/", "")
        return s[:8]
    if not a or not b:
        return True                       # absent attribute is never a conflict
    return datepart(a) == datepart(b)


def judge_row(row: GridRow, *, dry_wells: Optional[dict] = None) -> None:
    dry_wells = dry_wells or {}
    anchor = next((s for s in SOURCES if row.present[s]), None)
    if anchor is None:
        row.outcome = OUTCOME_NEEDS_REVIEW
        row.codes.append("no_presence")
        return
    row.origin = {"plan": "planned", "field": "field-added"}.get(
        anchor, f"{anchor}-origin")
    row.last_stage = [s for s in SOURCES if row.present[s]][-1]

    for s in SOURCES:
        if row.present[s] and row.mask[s] == FORBIDDEN:
            row.codes.append(f"unexpected_in_{s}")

    chain = [s for s in SOURCES if SOURCES.index(s) >= SOURCES.index(anchor)
             and row.mask[s] == REQUIRED]
    pattern = [row.present[s] for s in chain]
    stalled = gap = False
    if pattern and not all(pattern):
        seen_absent = False
        for p in pattern:
            if p and seen_absent:
                gap = True
                break
            if not p:
                seen_absent = True
        stalled = not gap
    if gap:
        row.codes.append("presence_gap")

    orphan = (anchor not in ("plan", "field") and row.mask["field"] == REQUIRED)
    not_collected = (anchor == "plan"
                     and not any(row.present[s] for s in SOURCES[1:]))
    if not_collected:
        loc = _get(row.attrs.get("plan", {}), _LOC_KEYS)
        if loc in dry_wells:
            row.codes.append(f"dry:{dry_wells[loc]}")
            # Spec §4.1: a documented dry well is informational, not an
            # error -- relax the (all-absent, since not_collected requires
            # it) downstream REQUIRED masks to OPTIONAL so this row
            # contributes 0 residual instead of counting every required
            # downstream leg as missing. Outcome stays not_collected.
            # ponytail: this runs after build_grid already applied
            # --presence-overrides, so it silently wins over an operator
            # override that forced one of this row's downstream sources
            # REQUIRED. No test exercises that combination and the CLI has
            # no way to express "dry AND still required" today -- if that
            # need shows up, judge_row needs the row's override set passed
            # in so it can skip relaxing an explicitly-overridden source.
            for s in SOURCES[1:]:
                if row.mask[s] == REQUIRED:
                    row.mask[s] = OPTIONAL

    # Attribute checks: anchor vs each downstream present source (D3).
    base = row.attrs.get(anchor, {})
    for s in SOURCES[SOURCES.index(anchor) + 1:]:
        if not row.present[s]:
            continue
        other = row.attrs[s]
        if not _dates_match(_get(base, _DATE_KEYS), _get(other, _DATE_KEYS)):
            row.codes.append(f"date_mismatch:{s}")
        for keys, name in ((_LOC_KEYS, "location"), (_MATRIX_KEYS, "matrix")):
            a, b = _get(base, keys), _get(other, keys)
            if a and b and _norm(a) != _norm(b):
                row.codes.append(f"{name}_mismatch:{s}")
    if row.present["field"] and row.present["coc"]:
        a = _norm(_get(row.attrs["field"], ("COCNumber", "coc_number")))
        b = _norm(_get(row.attrs["coc"], ("coc_number", "COCNumber")))
        if a and b and a != b:
            row.codes.append("coc_number_mismatch")
    # Custody lifecycle state (§7): an `exception` form is a red flag the
    # custody tool already raised -- humans decide. A form still pre-release
    # (draft/generated) while the lab or GDB already has the sample means the
    # sources disagree about the chain -- a detail conflict.
    coc_state = _norm(row.attrs.get("coc", {}).get("state"))
    if coc_state == "EXCEPTION":
        row.codes.append("coc_exception")
    elif (coc_state in ("DRAFT", "GENERATED")
          and (row.present["lab"] or row.present["gdb"])):
        row.codes.append(f"coc_state_mismatch:{coc_state.lower()}")
    plan_analytes = row.attrs.get("plan", {}).get("analytes")
    lab_analytes = row.attrs.get("lab", {}).get("analytes")
    if plan_analytes and row.present["lab"] and lab_analytes is not None:
        missing = sorted(set(plan_analytes) - set(lab_analytes))
        extra = sorted(set(lab_analytes) - set(plan_analytes))
        if missing:
            row.codes.append("analyte_missing:" + ",".join(missing))
        if extra:
            row.codes.append("analyte_unexpected:" + ",".join(extra))

    review = (gap or "multi_coc" in row.codes
              or "unparseable_sample_id" in row.codes
              or "coc_exception" in row.codes)
    conflict = any(c.split(":")[0].endswith("_mismatch")
                   or c.startswith(("analyte_", "unexpected_in_", "duplicate_in_"))
                   for c in row.codes)
    if review:
        row.outcome = OUTCOME_NEEDS_REVIEW
    elif orphan:
        row.outcome = OUTCOME_ORPHAN
    elif not_collected:
        row.outcome = OUTCOME_NOT_COLLECTED
    elif stalled:
        row.outcome = OUTCOME_STALLED
    elif conflict:
        row.outcome = OUTCOME_DETAIL_CONFLICT
    else:
        row.outcome = OUTCOME_RECONCILED


@dataclass
class ReconcileEventResult:
    rows: List[GridRow]
    observations: Dict[str, int]
    excluded: Dict[str, int]
    suggestions: List[dict]
    legs_run: List[str]
    counts: Dict[str, dict]
    residual: int

    @property
    def clean(self) -> bool:
        return self.residual == 0 and not any(
            r.outcome == OUTCOME_NEEDS_REVIEW for r in self.rows)


def _alnum(s: str) -> str:
    return "".join(ch for ch in s if ch.isalnum())


def suggest(rows: List[GridRow]) -> List[dict]:
    def eligible(row):
        parts = parse_sample_id(row.key)
        return parts is not None and parts.date_compact != ""
    missing = [r for r in rows
               if r.outcome in (OUTCOME_STALLED, OUTCOME_NOT_COLLECTED)
               and eligible(r)]
    extras = [r for r in rows
              if r.outcome in (OUTCOME_ORPHAN, OUTCOME_NEEDS_REVIEW)
              and eligible(r)]
    out = []
    for m in missing:
        for e in extras:
            if qc_class(m.key) != qc_class(e.key):
                continue        # never cross QC classes (#360 guard)
            ratio = difflib.SequenceMatcher(None, m.key, e.key).ratio()
            if ratio >= 0.85:
                # separator_variant: the two IDs are the same alphanumerics
                # (differ only in separators/case) -- an identity-confusable
                # pair, promoted to needs_review by reconcile_event (§4.1).
                # A plain high ratio (e.g. MW-2 vs MW-4, one digit apart)
                # stays an informational suggestion: structured IDs from one
                # event are always near each other by edit distance.
                out.append({"missing": m.key, "candidate": e.key,
                            "ratio": round(ratio, 3),
                            "separator_variant": _alnum(m.key) == _alnum(e.key)})
    return out


def reconcile_event(legs, *, overrides=None, dry_wells=None, garbled=None,
                    observations=None, excluded=None) -> ReconcileEventResult:
    grid = build_grid(legs, overrides=overrides)
    for raw in garbled or []:
        key = f"UNPARSEABLE:{raw}"
        row = GridRow(key=key, present={s: False for s in SOURCES},
                      mask={s: OPTIONAL for s in SOURCES})
        row.present["field"] = True
        row.raw_ids["field"] = raw
        row.attrs["field"] = {}
        row.codes.append("unparseable_sample_id")
        grid[key] = row
    for row in grid.values():
        judge_row(row, dry_wells=dry_wells)
    rows = sorted(grid.values(), key=lambda r: r.key)
    suggestions = suggest(rows)
    by_key = {r.key: r for r in rows}
    for sug in suggestions:
        if not sug["separator_variant"]:
            continue
        # Identity-confusable pair (spec §4.1 "near-miss"): the tool never
        # auto-resolves identity, so both sides go to needs_review.
        for mine, other in ((sug["missing"], sug["candidate"]),
                            (sug["candidate"], sug["missing"])):
            row = by_key[mine]
            code = f"near_miss:{other}"
            if code not in row.codes:
                row.codes.append(code)
            row.outcome = OUTCOME_NEEDS_REVIEW
    counts, residual = {}, 0
    for s in SOURCES:
        present = sum(1 for r in rows if r.present[s])
        req_missing = sum(1 for r in rows
                          if r.mask[s] == REQUIRED and not r.present[s])
        forb_present = sum(1 for r in rows
                           if r.mask[s] == FORBIDDEN and r.present[s])
        counts[s] = {"present": present, "required_missing": req_missing,
                     "forbidden_present": forb_present}
        residual += req_missing + forb_present
    return ReconcileEventResult(
        rows=rows, observations=dict(observations or {}),
        excluded=dict(excluded or {}), suggestions=suggestions,
        legs_run=sorted(legs), counts=counts, residual=residual)


_CSV_COLS = ["SampleID", "Outcome", "Origin", "LastStage",
             "In_Plan", "In_Field", "In_COC", "In_Lab", "In_GDB", "Codes"]


def rows_to_csv(result: ReconcileEventResult, path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = _csv.writer(fh)
        w.writerow(_CSV_COLS)
        for r in result.rows:
            w.writerow([r.key, r.outcome, r.origin, r.last_stage,
                        *(int(r.present[s]) for s in SOURCES),
                        ";".join(r.codes)])


def summary_dict(result: ReconcileEventResult) -> dict:
    totals: Dict[str, int] = {}
    for r in result.rows:
        totals[r.outcome] = totals.get(r.outcome, 0) + 1
    return {"legs_run": result.legs_run, "counts": result.counts,
            "outcome_totals": totals, "observations": result.observations,
            "excluded": result.excluded, "residual": result.residual,
            "clean": result.clean, "suggestions": result.suggestions}


def _demo() -> None:   # pragma: no cover - manual self-check
    a = {"location_id": "MW-1", "event_date": "2026-07-15", "matrix": "GW"}
    legs = {"plan": [SourceRow("MW-1-20260715-GW", a)],
            "field": [SourceRow("MW-1-20260715-GW", a)],
            "coc": [SourceRow("MW-1-20260715-GW", {"coc_number": "C1"})],
            "lab": [SourceRow("MW-1-20260715-GW", a)],
            "gdb": [SourceRow("MW-1-20260715-GW", a)]}
    result = reconcile_event(legs)
    assert result.clean and result.rows[0].outcome == OUTCOME_RECONCILED
    print("reconcile_event demo OK")


if __name__ == "__main__":   # pragma: no cover
    _demo()
