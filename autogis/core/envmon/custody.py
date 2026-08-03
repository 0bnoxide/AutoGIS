"""custody.py — electronic chain-of-custody (COC) lifecycle (Phase 6).

Headless, arcpy-free, stdlib-only. Extends the existing COC *draft* (produced
by ``create_sampling_event`` / ``sampling_event_writer``) through a validated
state lifecycle:

    draft → generated → released → laboratory_received → results_received
          → reconciled
                     ↘ exception   (reachable from any active state)

Every state change appends an immutable audit entry capturing timestamp,
responsible party, and free-form details (temperature checks, carrier,
exception reasons, sample counts). Records persist as one JSON file per event,
keyed by COC number, written atomically.

Reconciliation compares the planned sample IDs on a COC against the sample IDs
the laboratory actually received/reported and reports matched / missing / extra
— replacing the manual comparison spreadsheet the phase gate targets.

Out of scope for this first slice (deliberate, per roadmap Phase 6): a signature
platform. The ``actor`` string is the responsible-party record; cryptographic
signing is deferred until a real workflow requires it.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional

# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

DRAFT = "draft"
GENERATED = "generated"
RELEASED = "released"
LAB_RECEIVED = "laboratory_received"
RESULTS_RECEIVED = "results_received"
RECONCILED = "reconciled"
EXCEPTION = "exception"

LIFECYCLE_STATES = (
    DRAFT, GENERATED, RELEASED, LAB_RECEIVED,
    RESULTS_RECEIVED, RECONCILED, EXCEPTION,
)

# Legal forward transitions. EXCEPTION is reachable from any active
# (non-terminal) state; RECONCILED and EXCEPTION are terminal in this slice.
# ponytail: exception is terminal — add an exception→reconciled resolution
# path when a real workflow needs to reopen a flagged COC.
_ALLOWED: Dict[str, set] = {
    DRAFT: {GENERATED, EXCEPTION},
    GENERATED: {RELEASED, EXCEPTION},
    RELEASED: {LAB_RECEIVED, EXCEPTION},
    LAB_RECEIVED: {RESULTS_RECEIVED, RECONCILED, EXCEPTION},
    RESULTS_RECEIVED: {RECONCILED, EXCEPTION},
    RECONCILED: set(),
    EXCEPTION: set(),
}


class CustodyError(Exception):
    """Illegal transition or malformed custody record/store."""


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class AuditEntry:
    at: str                      # ISO-8601 timestamp
    from_state: str
    to_state: str
    actor: str                   # responsible party
    note: str = ""
    details: dict = field(default_factory=dict)


@dataclass
class CustodyRecord:
    coc_number: str
    event_name: str
    site_id: str
    event_date: str              # ISO "YYYY-MM-DD"
    lab_name: str
    sample_ids: List[str]        # planned sample IDs on this COC
    state: str = DRAFT
    audit: List[AuditEntry] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------

def _iso(at: datetime) -> str:
    return at.replace(microsecond=0).isoformat()


def new_record(
    coc_number: str,
    *,
    event_name: str,
    site_id: str,
    event_date: str,
    lab_name: str,
    sample_ids: Iterable[str],
    at: datetime,
    actor: str,
) -> CustodyRecord:
    """Create a COC in the DRAFT state with a creation audit entry."""
    if not actor or not actor.strip():
        raise CustodyError("actor (responsible party) is required")
    rec = CustodyRecord(
        coc_number=coc_number,
        event_name=event_name,
        site_id=site_id,
        event_date=event_date,
        lab_name=lab_name,
        sample_ids=list(sample_ids),
    )
    rec.audit.append(AuditEntry(
        at=_iso(at), from_state="", to_state=DRAFT, actor=actor,
        note="created", details={"sample_count": len(rec.sample_ids)},
    ))
    return rec


def transition(
    record: CustodyRecord,
    to_state: str,
    *,
    actor: str,
    at: datetime,
    note: str = "",
    details: Optional[dict] = None,
) -> CustodyRecord:
    """Advance ``record`` to ``to_state``, appending an audit entry.

    Raises CustodyError on an illegal transition or unknown target state.
    Mutates and returns ``record``.
    """
    if to_state not in LIFECYCLE_STATES:
        raise CustodyError(f"Unknown state: {to_state!r}")
    if not actor or not actor.strip():
        raise CustodyError("actor (responsible party) is required for a transition")
    allowed = _ALLOWED.get(record.state, set())
    if to_state not in allowed:
        raise CustodyError(
            f"Illegal transition {record.state!r} → {to_state!r} for COC "
            f"{record.coc_number!r}. Allowed: {sorted(allowed) or 'none (terminal)'}"
        )
    record.audit.append(AuditEntry(
        at=_iso(at), from_state=record.state, to_state=to_state,
        actor=actor, note=note, details=dict(details or {}),
    ))
    record.state = to_state
    return record


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------

@dataclass
class Reconciliation:
    matched: List[str]
    missing: List[str]     # planned but not received
    extra: List[str]       # received but not planned

    @property
    def clean(self) -> bool:
        return not self.missing and not self.extra


def reconcile(record: CustodyRecord, received_ids: Iterable[str]) -> Reconciliation:
    """Compare a COC's planned sample IDs against the IDs actually received.

    Pure — does not mutate the record. Case-sensitive exact match on sample ID.
    """
    planned = set(record.sample_ids)
    received = set(received_ids)
    return Reconciliation(
        matched=sorted(planned & received),
        missing=sorted(planned - received),
        extra=sorted(received - planned),
    )


# ---------------------------------------------------------------------------
# Bridge from the existing sampling-event plan (the "draft")
# ---------------------------------------------------------------------------

def records_from_plan(plan, *, at: datetime, actor: str) -> List[CustodyRecord]:
    """Group a SamplingEventPlan's expected samples by COC number into DRAFT
    custody records — the bridge from the existing COC draft into the lifecycle.

    ``plan`` is an ``autogis.core.envmon.create_sampling_event.SamplingEventPlan``
    (duck-typed here to keep this module import-light).

    Sample IDs are deduplicated in plan order: the planner emits one row per
    (location x analyte_group) and those rows share a sample ID, so appending
    per row made the audit trail's ``sample_count`` claim more planned samples
    than ``reconcile()`` could ever match (issue #422).
    """
    by_coc: Dict[str, List[str]] = {}
    for row in plan.expected_samples:
        ids = by_coc.setdefault(row.coc_number, [])
        if row.sample_id not in ids:
            ids.append(row.sample_id)
    return [
        new_record(
            coc,
            event_name=plan.event_name,
            site_id=plan.site_id,
            event_date=plan.event_date,
            lab_name=plan.lab_name,
            sample_ids=sample_ids,
            at=at,
            actor=actor,
        )
        for coc, sample_ids in sorted(by_coc.items())
    ]


# ---------------------------------------------------------------------------
# Persistence — one JSON file per event, keyed by COC number
# ---------------------------------------------------------------------------

def _decode_record(d: dict) -> CustodyRecord:
    audit = [AuditEntry(**e) for e in d.get("audit", [])]
    return CustodyRecord(
        coc_number=d["coc_number"],
        event_name=d["event_name"],
        site_id=d["site_id"],
        event_date=d["event_date"],
        lab_name=d["lab_name"],
        sample_ids=list(d.get("sample_ids", [])),
        state=d.get("state", DRAFT),
        audit=audit,
    )


def load_store(path: Path) -> Dict[str, CustodyRecord]:
    """Load a custody store (COC number → record). Empty dict if absent."""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise CustodyError(f"Cannot read custody store {p}: {exc}") from exc
    return {coc: _decode_record(rec) for coc, rec in raw.items()}


def save_store(path: Path, store: Dict[str, CustodyRecord]) -> None:
    """Write the custody store atomically (temp file + os.replace).

    ponytail: no cross-process lock — a COC store is single-writer in practice
    (one operator advances one event's COCs). Add an OS byte-range lock like
    run_history if concurrent multi-operator writes to one event appear.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {coc: asdict(rec) for coc, rec in store.items()}
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, p)


# ---------------------------------------------------------------------------
# Self-check
# ---------------------------------------------------------------------------

def _demo() -> None:
    """Runnable invariant check: assert-based, no framework."""
    import tempfile

    t0 = datetime(2026, 7, 23, 9, 0, 0)
    rec = new_record(
        "COC-001", event_name="EVT", site_id="SITE", event_date="2026-07-23",
        lab_name="LabCo", sample_ids=["S1", "S2", "S3"], at=t0, actor="planner",
    )
    assert rec.state == DRAFT and len(rec.audit) == 1

    # Legal path draft → generated → released → lab_received
    transition(rec, GENERATED, actor="planner", at=t0)
    transition(rec, RELEASED, actor="courier", at=t0, details={"carrier": "FedEx"})
    transition(rec, LAB_RECEIVED, actor="lab-tech", at=t0,
               details={"temperature_c": 4.0, "temperature_ok": True})
    assert rec.state == LAB_RECEIVED
    assert len(rec.audit) == 4

    # Illegal skip is rejected
    bad = new_record("COC-X", event_name="E", site_id="S", event_date="2026-07-23",
                     lab_name="L", sample_ids=[], at=t0, actor="x")
    try:
        transition(bad, RELEASED, actor="x", at=t0)  # draft → released skips generated
        raise AssertionError("illegal transition was allowed")
    except CustodyError:
        pass

    # actor is mandatory
    try:
        transition(rec, RESULTS_RECEIVED, actor="  ", at=t0)
        raise AssertionError("blank actor was allowed")
    except CustodyError:
        pass

    # Reconcile: lab received S1, S2 and an unexpected S9 (S3 missing)
    r = reconcile(rec, ["S1", "S2", "S9"])
    assert r.matched == ["S1", "S2"] and r.missing == ["S3"] and r.extra == ["S9"]
    assert not r.clean
    assert reconcile(rec, ["S1", "S2", "S3"]).clean

    # Discrepancy routes to exception; clean would route to reconciled
    transition(rec, EXCEPTION, actor="reviewer", at=t0,
               note="missing S3, extra S9", details=asdict(r))
    assert rec.state == EXCEPTION
    assert _ALLOWED[EXCEPTION] == set()  # terminal

    # Round-trip persistence
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "EVT_custody.json"
        save_store(path, {rec.coc_number: rec})
        back = load_store(path)
        assert back[rec.coc_number].state == EXCEPTION
        assert back[rec.coc_number].sample_ids == ["S1", "S2", "S3"]
        assert len(back[rec.coc_number].audit) == len(rec.audit)

    print("custody _demo OK")


if __name__ == "__main__":
    _demo()
