# Survey123 Phase 3 — `envmon reconcile-event` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One command that reconciles a monitoring event's samples across plan → Survey123 field submissions → COC custody forms → lab results → GDB rows, assigning each sample exactly one of six outcomes with a zero-residual balance proof.

**Architecture:** A pure presence-matrix engine (`core/envmon/reconcile_event.py`, dict-in/dict-out, arcpy-free) plus a thin CLI adapter that loads the five legs via existing readers. Approved design: `docs/superpowers/specs/2026-07-30-survey123-phase3-event-reconciliation-design.md` (D1–D10 are binding).

**Tech Stack:** Python stdlib only (dataclasses, csv, json, difflib). Reuses `sample_id`, `create_sampling_event`, `custody`, `normalize_survey123`, `records_csv`, `gdb_schema` records. No new dependencies, no arcpy, no arcgis.

## Global Constraints

- ponytail (full): laziest working solution; reuse before writing; no unrequested abstractions.
- `core/` and `adapters/` must import with neither `arcpy` nor `arcgis` present (CI is the only verifier — local venv has arcgis).
- Heavy imports in `cli.py` are **function-local** (convention, e.g. `cli.py:2706-2711`).
- No `find_spec("arcgis")` gate: this command is offline, same as `route-survey123` / `reconcile-survey123-lab` (the gate is only for live-arcgis commands like `sync-survey123`, `cli.py:4620-4625`).
- Exact-only matching (D7); fuzzy = post-hoc suggestions that consume nothing, never cross QC classes, never involve NODATE IDs.
- Every new command must be in BOTH `runtime/capabilities.py` structures or `requires_arcpy()` raises `KeyError` for it.
- Tests: `tests/envmon/test_reconcile_event.py`, run `python -m pytest tests/envmon/test_reconcile_event.py -q` with `PYTHONPATH` unset issues in mind — run from repo root. Full suite before PR.
- Commit after every task. `main` is read-only — all work on the feature branch.

## File Structure

| File | Responsibility |
|---|---|
| `autogis/core/envmon/reconcile_event.py` (create) | Pure engine: key policy, expected-presence masks, grid build, outcome judgment, balance, suggestions, CSV/JSON serialization |
| `autogis/adapters/cli.py` (modify) | `envmon reconcile-event` command: load five legs via existing readers, call engine, write outputs, exit codes |
| `autogis/runtime/capabilities.py` (modify) | Register command in `TOOLS` + `_REGISTRY_SEED` |
| `tests/envmon/test_reconcile_event.py` (create) | Engine unit tests + golden fixture event + CLI e2e (CliRunner) |

---

### Task 1: Engine skeleton — key policy, QC masks, dataclasses

**Files:**
- Create: `autogis/core/envmon/reconcile_event.py`
- Test: `tests/envmon/test_reconcile_event.py`

**Interfaces:**
- Consumes: `autogis.core.envmon.sample_id` — `parse_sample_id(s) -> Optional[SampleIdParts]` (fields `location_id, date_compact, matrix, qc`; `date_compact == ""` for NODATE), `qc_class(s) -> Optional[str]` (returns `PRIMARY == "primary"`, a `QC_SUFFIXES` value, or `None`), `QC_SUFFIXES` (dict), `PRIMARY`.
- Produces (later tasks rely on these exact names):
  - `SOURCES = ("plan", "field", "coc", "lab", "gdb")`
  - `REQUIRED = "required"; OPTIONAL = "optional"; FORBIDDEN = "forbidden"`
  - `normalize_key(sample_id: str) -> str`
  - `default_mask(sample_id: str) -> dict[str, str]` (one value per source)
  - `@dataclass SourceRow(sample_id: str, attrs: dict)`
  - `@dataclass GridRow(key, raw_ids: dict, present: dict, attrs: dict, mask: dict, origin: str, outcome: str, codes: list, last_stage: str)`

- [ ] **Step 1: Write the failing tests**

```python
"""tests/envmon/test_reconcile_event.py"""
from autogis.core.envmon import reconcile_event as re_mod
from autogis.core.envmon.sample_id import QC_SUFFIXES, PRIMARY


def test_normalize_key_uppercases_and_strips():
    assert re_mod.normalize_key("  mw-1-20260715-gw ") == "MW-1-20260715-GW"


def test_default_mask_primary_requires_downstream_plan_optional():
    m = re_mod.default_mask("MW-1-20260715-GW")
    assert m["plan"] == re_mod.OPTIONAL          # D3: plan never required
    for s in ("field", "coc", "lab", "gdb"):
        assert m[s] == re_mod.REQUIRED


def test_default_mask_lab_qc_is_lab_only():
    m = re_mod.default_mask("MW-1-20260715-GW-MB")
    assert m["lab"] == re_mod.REQUIRED
    assert m["field"] == re_mod.FORBIDDEN
    assert m["coc"] == re_mod.FORBIDDEN


def test_default_mask_trip_blank_forbids_field():
    m = re_mod.default_mask("MW-1-20260715-GW-TB")
    assert m["field"] == re_mod.FORBIDDEN
    assert m["coc"] == re_mod.REQUIRED
    assert m["lab"] == re_mod.REQUIRED


def test_every_qc_class_has_a_mask():
    # The table must stay exhaustive as sample_id.QC_SUFFIXES evolves.
    classes = set(QC_SUFFIXES.values()) | {PRIMARY}
    for cls in classes:
        assert cls in re_mod.QC_MASKS or re_mod.UNKNOWN_QC_MASK, cls
        # default_mask must never KeyError on any real suffix:
    for suffix in QC_SUFFIXES:
        re_mod.default_mask(f"MW-1-20260715-GW-{suffix}")


def test_unknown_or_unparseable_id_gets_all_optional_mask():
    m = re_mod.default_mask("GARBAGE!!")
    assert set(m.values()) == {re_mod.OPTIONAL}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/envmon/test_reconcile_event.py -q`
Expected: FAIL — `ModuleNotFoundError` / `AttributeError` (module doesn't exist).

- [ ] **Step 3: Write the module skeleton**

```python
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
    "FD": dict(_ALL_REQUIRED_DOWNSTREAM),          # field duplicate travels the full chain
    "TB": {"plan": OPTIONAL, "field": FORBIDDEN, "coc": REQUIRED,
           "lab": REQUIRED, "gdb": OPTIONAL},      # trip blank: never a field entry
    "EB": {"plan": OPTIONAL, "field": OPTIONAL, "coc": REQUIRED,
           "lab": REQUIRED, "gdb": OPTIONAL},      # equipment blank
    "MB": {"plan": FORBIDDEN, "field": FORBIDDEN, "coc": FORBIDDEN,
           "lab": REQUIRED, "gdb": OPTIONAL},      # lab method blank
    "MS": {"plan": FORBIDDEN, "field": FORBIDDEN, "coc": FORBIDDEN,
           "lab": REQUIRED, "gdb": OPTIONAL},
    "MSD": {"plan": FORBIDDEN, "field": FORBIDDEN, "coc": FORBIDDEN,
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
```

Adjust the two QC-table tests if `sample_id.QC_SUFFIXES` spells classes differently — **read `sample_id.py:24-30` first** and key `QC_MASKS` by the exact `qc_class` return values; the exhaustiveness test exists to force this alignment.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/envmon/test_reconcile_event.py -q`
Expected: PASS (all 6).

- [ ] **Step 5: Commit**

```bash
git add autogis/core/envmon/reconcile_event.py tests/envmon/test_reconcile_event.py
git commit -m "feat(envmon): reconcile-event key policy and QC expected-presence masks"
```

---

### Task 2: Grid build

**Files:**
- Modify: `autogis/core/envmon/reconcile_event.py`
- Test: `tests/envmon/test_reconcile_event.py`

**Interfaces:**
- Consumes: Task 1 names.
- Produces: `build_grid(legs: dict[str, list[SourceRow]], *, overrides: Optional[dict] = None) -> dict[str, GridRow]` — `legs` keys are a subset of `SOURCES`; `overrides` maps normalized sample id → `{source: mask_value}` (D5 plan override). Sources absent from `legs` get mask forced to `OPTIONAL` on every row (omitted leg is never judged). Multi-occurrence within one source: presence stays True, first attrs win, except `coc` where a second *distinct* COC number appends code `"multi_coc"`.

- [ ] **Step 1: Write the failing tests**

```python
def _legs(**kw):
    return {k: [re_mod.SourceRow(s, a) for s, a in v] for k, v in kw.items()}


def test_build_grid_one_row_per_normalized_id():
    legs = _legs(field=[("mw-1-20260715-gw", {})], lab=[("MW-1-20260715-GW", {})])
    grid = re_mod.build_grid(legs)
    assert list(grid) == ["MW-1-20260715-GW"]
    row = grid["MW-1-20260715-GW"]
    assert row.present["field"] and row.present["lab"]
    assert not row.present["plan"]


def test_build_grid_omitted_leg_mask_forced_optional():
    grid = re_mod.build_grid(_legs(field=[("MW-1-20260715-GW", {})]))
    row = grid["MW-1-20260715-GW"]
    assert row.mask["lab"] == re_mod.OPTIONAL      # lab leg not provided
    assert row.mask["coc"] == re_mod.OPTIONAL


def test_build_grid_override_beats_default():
    ov = {"MW-1-20260715-GW": {"gdb": re_mod.FORBIDDEN}}
    grid = re_mod.build_grid(_legs(field=[("MW-1-20260715-GW", {})],
                                   gdb=[("MW-1-20260715-GW", {})]), overrides=ov)
    assert grid["MW-1-20260715-GW"].mask["gdb"] == re_mod.FORBIDDEN


def test_build_grid_multi_coc_flagged():
    legs = _legs(coc=[("MW-1-20260715-GW", {"coc_number": "COC-001"}),
                      ("MW-1-20260715-GW", {"coc_number": "COC-002"})])
    row = re_mod.build_grid(legs)["MW-1-20260715-GW"]
    assert "multi_coc" in row.codes


def test_build_grid_duplicate_same_coc_not_flagged():
    # 422 shape: planner repeats the same id on the same COC — dedupe silently.
    legs = _legs(coc=[("MW-1-20260715-GW", {"coc_number": "COC-001"}),
                      ("MW-1-20260715-GW", {"coc_number": "COC-001"})])
    assert re_mod.build_grid(legs)["MW-1-20260715-GW"].codes == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/envmon/test_reconcile_event.py -q`
Expected: FAIL — `AttributeError: ... no attribute 'build_grid'`.

- [ ] **Step 3: Implement `build_grid`**

```python
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
                if (source == "coc"
                        and obs.attrs.get("coc_number")
                        and obs.attrs["coc_number"] != row.attrs["coc"].get("coc_number")
                        and "multi_coc" not in row.codes):
                    row.codes.append("multi_coc")
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/envmon/test_reconcile_event.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -u && git add tests/envmon/test_reconcile_event.py
git commit -m "feat(envmon): reconcile-event presence grid build"
```

---

### Task 3: Outcome judgment (anchor, contiguity, attribute checks, precedence)

**Files:**
- Modify: `autogis/core/envmon/reconcile_event.py`
- Test: `tests/envmon/test_reconcile_event.py`

**Interfaces:**
- Consumes: Tasks 1–2.
- Produces: `judge_row(row: GridRow, *, dry_wells: Optional[dict] = None) -> None` — sets `origin` (`"planned"` / `"field-added"` / `"<source>-origin"`), `outcome`, `last_stage`, appends `codes`. Attribute comparison helpers `_dates_match(a, b) -> bool` (date-part, tolerant of `datetime`/ISO str/`YYYYMMDD`), `_norm(s) -> str` (upper/strip). `dry_wells` maps `LocationID -> reason` (D8).

Judgment algorithm (spec §4):
1. `anchor` = first source in `SOURCES` order with `present`. Origin: plan→`"planned"`, field→`"field-added"`, else `f"{anchor}-origin"`.
2. `forbidden_present` = sources present where mask is FORBIDDEN → code `f"unexpected_in_{s}"` each.
3. Required chain = sources at/after anchor with mask REQUIRED. Walk it: contiguous present-prefix then all absent → **stalled** (`last_stage` = last present source overall); absent-then-present hole → **needs_review** + code `"presence_gap"`.
4. **orphan**: a REQUIRED source *before* any present one is absent — i.e. mask requires field but anchor is lab/gdb (`anchor` not in ("plan","field") and mask["field"] == REQUIRED).
5. **not_collected**: anchor == "plan" and nothing else present; dry_wells annotation by `attrs["plan"]["location_id"]` → code `f"dry:{reason}"`.
6. Attribute checks between anchor and each downstream present source: date (`event_date`/`SampleDate`/`sample_date` — first key found), location (`location_id`/`LocationID`), matrix (`matrix`/`Matrix`), each via `_norm`/`_dates_match`; mismatch → code `f"{attr}_mismatch:{source}"`. COC number: field vs coc attrs when both present → `"coc_number_mismatch"`. Lab analyte set: when plan and lab present and plan attrs carry `analytes` (a set), missing = `plan_analytes - lab_analytes` → `"analyte_missing:<sorted,csv>"`, extra → `"analyte_unexpected:<sorted,csv>"`.
7. Headline outcome by `OUTCOME_ORDER`: needs_review if presence_gap/multi_coc/unparseable codes; else orphan; else not_collected; else stalled; else detail_conflict if any `*_mismatch`/`analyte_*`/`unexpected_in_*` code; else reconciled.

- [ ] **Step 1: Write the failing tests**

```python
def _judged(legs, **kw):
    grid = re_mod.build_grid(legs)
    for row in grid.values():
        re_mod.judge_row(row, **kw)
    return grid


def test_planned_clean_sample_reconciled():
    a = {"location_id": "MW-1", "event_date": "2026-07-15", "matrix": "GW"}
    legs = _legs(plan=[("MW-1-20260715-GW", a)], field=[("MW-1-20260715-GW", a)],
                 coc=[("MW-1-20260715-GW", {"coc_number": "COC-001"})],
                 lab=[("MW-1-20260715-GW", a)], gdb=[("MW-1-20260715-GW", a)])
    row = _judged(legs)["MW-1-20260715-GW"]
    assert row.outcome == re_mod.OUTCOME_RECONCILED
    assert row.origin == "planned"


def test_field_added_sample_reconciled_not_flagged():
    a = {"LocationID": "MW-9", "SampleDate": "2026-07-15", "Matrix": "GW"}
    legs = _legs(field=[("MW-9-20260715-GW", a)],
                 coc=[("MW-9-20260715-GW", {"coc_number": "COC-001"})],
                 lab=[("MW-9-20260715-GW", a)], gdb=[("MW-9-20260715-GW", a)])
    row = _judged(legs)["MW-9-20260715-GW"]
    assert row.outcome == re_mod.OUTCOME_RECONCILED
    assert row.origin == "field-added"      # D3: unplanned is legitimate


def test_stalled_after_coc_names_last_stage():
    legs = _legs(field=[("MW-2-20260715-GW", {})],
                 coc=[("MW-2-20260715-GW", {"coc_number": "COC-001"})])
    # lab and gdb legs ARE provided (empty) so their absence is judged
    legs["lab"], legs["gdb"] = [], []
    row = _judged(legs)["MW-2-20260715-GW"]
    assert row.outcome == re_mod.OUTCOME_STALLED
    assert row.last_stage == "coc"


def test_not_collected_with_dry_reason():
    legs = _legs(plan=[("MW-3-20260715-GW", {"location_id": "MW-3"})])
    legs["field"] = legs["coc"] = legs["lab"] = legs["gdb"] = []
    row = _judged(legs, dry_wells={"MW-3": "well dry"})["MW-3-20260715-GW"]
    assert row.outcome == re_mod.OUTCOME_NOT_COLLECTED
    assert any(c.startswith("dry:") for c in row.codes)


def test_orphan_lab_only_primary():
    legs = _legs(lab=[("MW-4-20260715-GW", {})])
    legs["field"] = legs["coc"] = legs["gdb"] = []
    row = _judged(legs)["MW-4-20260715-GW"]
    assert row.outcome == re_mod.OUTCOME_ORPHAN


def test_lab_only_method_blank_is_reconciled():
    legs = _legs(lab=[("MW-4-20260715-GW-MB", {})])
    legs["field"] = legs["coc"] = legs["gdb"] = []
    row = _judged(legs)["MW-4-20260715-GW-MB"]
    assert row.outcome == re_mod.OUTCOME_RECONCILED   # matches its mask


def test_presence_gap_needs_review():
    legs = _legs(field=[("MW-5-20260715-GW", {})], gdb=[("MW-5-20260715-GW", {})])
    legs["coc"], legs["lab"] = [], []
    row = _judged(legs)["MW-5-20260715-GW"]
    assert row.outcome == re_mod.OUTCOME_NEEDS_REVIEW
    assert "presence_gap" in row.codes


def test_matrix_mismatch_detail_conflict():
    legs = _legs(field=[("MW-6-20260715-GW", {"Matrix": "GW"})],
                 lab=[("MW-6-20260715-GW", {"matrix": "SO"})],
                 coc=[("MW-6-20260715-GW", {"coc_number": "C1"})],
                 gdb=[("MW-6-20260715-GW", {"Matrix": "GW"})])
    row = _judged(legs)["MW-6-20260715-GW"]
    assert row.outcome == re_mod.OUTCOME_DETAIL_CONFLICT
    assert any(c.startswith("matrix_mismatch") for c in row.codes)


def test_stalled_beats_detail_conflict_in_headline():
    legs = _legs(field=[("MW-7-20260715-GW", {"Matrix": "GW"})],
                 coc=[("MW-7-20260715-GW", {"coc_number": "C1", "matrix": "SO"})])
    legs["lab"], legs["gdb"] = [], []
    row = _judged(legs)["MW-7-20260715-GW"]
    assert row.outcome == re_mod.OUTCOME_STALLED
    assert any(c.startswith("matrix_mismatch") for c in row.codes)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/envmon/test_reconcile_event.py -q`
Expected: FAIL — no `judge_row`.

- [ ] **Step 3: Implement `judge_row` + helpers**

```python
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
    plan_analytes = row.attrs.get("plan", {}).get("analytes")
    lab_analytes = row.attrs.get("lab", {}).get("analytes")
    if plan_analytes and row.present["lab"] and lab_analytes is not None:
        missing = sorted(set(plan_analytes) - set(lab_analytes))
        extra = sorted(set(lab_analytes) - set(plan_analytes))
        if missing:
            row.codes.append("analyte_missing:" + ",".join(missing))
        if extra:
            row.codes.append("analyte_unexpected:" + ",".join(extra))

    review = gap or "multi_coc" in row.codes or "unparseable_sample_id" in row.codes
    conflict = any(c.split(":")[0].endswith("_mismatch")
                   or c.startswith(("analyte_", "unexpected_in_"))
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/envmon/test_reconcile_event.py -q`
Expected: PASS (all so far).

- [ ] **Step 5: Commit**

```bash
git add -u && git commit -m "feat(envmon): reconcile-event outcome judgment"
```

---

### Task 4: Balance, suggestions, result object, serialization

**Files:**
- Modify: `autogis/core/envmon/reconcile_event.py`
- Test: `tests/envmon/test_reconcile_event.py`

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces:
  - `@dataclass ReconcileEventResult(rows: list[GridRow], observations: dict, excluded: dict, suggestions: list, legs_run: list, counts: dict, residual: int)` with property `clean -> bool` (`residual == 0` and no `needs_review` rows).
  - `reconcile_event(legs, *, overrides=None, dry_wells=None, garbled=None, observations=None, excluded=None) -> ReconcileEventResult` — the one entry point the CLI calls. `garbled`: list of raw-id strings from *sample-form* rows whose ID is empty/unparseable; each becomes a `needs_review` GridRow with code `"unparseable_sample_id"` (D6: never demoted to observation).
  - `suggest(rows) -> list[dict]` — near-miss pairs `{"missing": key, "candidate": key, "ratio": float}`; same `qc_class` both sides; neither side NODATE (`parse_sample_id(k).date_compact == ""` excluded); `difflib.SequenceMatcher` ratio ≥ 0.85; consumes nothing.
  - `rows_to_csv(result, path) -> None` — columns: `SampleID, Outcome, Origin, LastStage, In_Plan, In_Field, In_COC, In_Lab, In_GDB, Codes` (codes `;`-joined).
  - `summary_dict(result) -> dict` — keys: `legs_run, counts` (per source: `present`, `required_missing`, `forbidden_present`), `outcome_totals`, `observations`, `excluded`, `residual`, `clean`, `suggestions`.
  - Residual definition (falsifiable, spec §3 step 5): `residual = Σ over rows of (#REQUIRED sources absent + #FORBIDDEN sources present)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_reconcile_event_residual_zero_when_all_masks_met():
    a = {"location_id": "MW-1", "event_date": "2026-07-15", "matrix": "GW"}
    legs = _legs(plan=[("MW-1-20260715-GW", a)], field=[("MW-1-20260715-GW", a)],
                 coc=[("MW-1-20260715-GW", {"coc_number": "C1"})],
                 lab=[("MW-1-20260715-GW", a)], gdb=[("MW-1-20260715-GW", a)])
    result = re_mod.reconcile_event(legs)
    assert result.residual == 0
    assert result.clean


def test_reconcile_event_stalled_sample_breaks_balance():
    legs = _legs(field=[("MW-2-20260715-GW", {})])
    legs["coc"] = legs["lab"] = legs["gdb"] = []
    result = re_mod.reconcile_event(legs)
    assert result.residual == 3          # coc, lab, gdb required-missing
    assert not result.clean


def test_garbled_sample_form_row_is_needs_review_not_observation():
    result = re_mod.reconcile_event({"field": []}, garbled=["???"])
    assert len(result.rows) == 1
    assert result.rows[0].outcome == re_mod.OUTCOME_NEEDS_REVIEW
    assert "unparseable_sample_id" in result.rows[0].codes
    assert not result.clean


def test_suggest_pairs_near_miss_same_class_only():
    legs = _legs(field=[("MW-03-20260801-GW", {})], lab=[("MW03-20260801-GW", {})])
    legs["coc"], legs["gdb"] = [], []
    result = re_mod.reconcile_event(legs)
    pairs = {(s["missing"], s["candidate"]) for s in result.suggestions}
    assert any("MW-03-20260801-GW" in p and "MW03-20260801-GW" in p for p in pairs)


def test_suggest_never_offers_nodate():
    legs = _legs(field=[("MW-03-NODATE-ABC123-GW", {})],
                 lab=[("MW03-NODATE-ABC123-GW", {})])
    legs["coc"], legs["gdb"] = [], []
    result = re_mod.reconcile_event(legs)
    assert result.suggestions == []


def test_csv_and_summary_roundtrip(tmp_path):
    legs = _legs(field=[("MW-1-20260715-GW", {})])
    legs["coc"] = legs["lab"] = legs["gdb"] = []
    result = re_mod.reconcile_event(legs, observations={"water_levels": 3})
    out = tmp_path / "recon.csv"
    re_mod.rows_to_csv(result, out)
    text = out.read_text(encoding="utf-8")
    assert "SampleID" in text and "MW-1-20260715-GW" in text
    summary = re_mod.summary_dict(result)
    assert summary["observations"] == {"water_levels": 3}
    assert summary["residual"] == result.residual
    assert "field" in summary["legs_run"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/envmon/test_reconcile_event.py -q`
Expected: FAIL — no `reconcile_event`.

- [ ] **Step 3: Implement**

```python
import csv as _csv
import json as _json
from pathlib import Path


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
                out.append({"missing": m.key, "candidate": e.key,
                            "ratio": round(ratio, 3)})
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
        excluded=dict(excluded or {}), suggestions=suggest(rows),
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
```

Note for the NODATE test: read `sample_id.py:53-72` first and use a *real* NODATE-form ID string in the test (the exact spelling `build_sample_id` produces when date is missing); adjust the fixture string if the format differs from `MW-03-NODATE-ABC123-GW`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/envmon/test_reconcile_event.py -q`
Expected: PASS.

- [ ] **Step 5: Add the `_demo()` self-check (repo convention, e.g. custody.py:271) and commit**

```python
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
```

```bash
git add -u && git commit -m "feat(envmon): reconcile-event balance, suggestions, serialization"
```

---

### Task 5: CLI command + capabilities registration

**Files:**
- Modify: `autogis/adapters/cli.py` (new command in the `envmon` group; module constant near `cli.py:2439`'s `_COC_DISCREPANCY_EXIT`)
- Modify: `autogis/runtime/capabilities.py` (`TOOLS` dict ~line 52 area; `_REGISTRY_SEED` ~line 422 area)
- Test: `tests/envmon/test_reconcile_event.py`

**Interfaces:**
- Consumes (exact, verified 2026-08-01):
  - `SiteConfig.load(Path)`, `load_event_config(Path)`, `load_analyte_dictionary(Path)`, `build_sampling_event_plan(site_cfg.data, event_cfg, analyte_dict, run_id=...)` — the `envmon coc generate` pattern at `cli.py:2519-2536`.
  - `custody.load_store(Path) -> Dict[str, CustodyRecord]` (`custody.py:240-249`; raises `CustodyError`).
  - `load_survey123_csv_submissions(path, site_id, batch_id, qa, field_map=None) -> (water_levels, samples)` (`normalize_survey123.py:140-156`).
  - `read_records_csv(path, AnalyticalResultRecord)` and `read_records_csv(path, SampleRecord)` (`records_csv.py:87-109`; `gdb_schema.py:467/458`).
  - `@qa_report_options` + `_render_qa(qa, report, fail_on)` (`cli.py:25-41`, `:1813-1837` — raises SystemExit(1) itself on fail_on breach; call it BEFORE the semantic exit-2 check, mirroring `coc reconcile` at `cli.py:2661-2662`).
- Produces: `envmon reconcile-event` with options:
  - `--site PATH` `--event PATH` `--analytes PATH` (all three or none — plan leg),
  - `--submissions-csv PATH` (field leg; raw Survey123 submissions CSV — normalized in-process),
  - `--custody-store PATH` (COC leg),
  - `--lab-results-csv PATH` (canonical `AnalyticalResultRecord` CSV, same contract as `export-wqx`, `cli.py:2740-2743`),
  - `--gdb-samples-csv PATH` (CSV export of `Env_Samples`, same contract as `evaluate-rpd-qa --samples-csv`, `cli.py:625-628`),
  - `--dry-wells PATH` (optional JSON `{LocationID: reason}`),
  - `--presence-overrides PATH` (optional JSON `{SampleID: {source: required|optional|forbidden}}`),
  - `--out-csv PATH` (required), `--out-json PATH` (required), `@qa_report_options`.
  - At least ONE of the five legs required, else `click.UsageError`.
  - Exit: 0 clean; `_RECONCILE_EVENT_DISCREPANCY_EXIT = 2` when `not result.clean` (after outputs written and `_render_qa` called).

- [ ] **Step 1: Write the failing CLI tests**

```python
# ── CLI end-to-end ───────────────────────────────────────────────
import json
from click.testing import CliRunner

from autogis.adapters.cli import autogis


def _field_csv(tmp_path, rows):
    # Columns per Survey123Field defaults (normalize_survey123.py:28-36)
    p = tmp_path / "subs.csv"
    hdr = "WellID,SamplingDate,Matrix,SampledBy,COCNumber,DepthToWater_ft,QAFlags"
    p.write_text(hdr + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return p


def test_reconcile_event_in_help():
    res = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "reconcile-event" in res.output


def test_reconcile_event_field_only_clean_exit_zero(tmp_path):
    subs = _field_csv(tmp_path, ["MW-1,2026-07-15,GW,AB,COC-001,,"])
    out_csv, out_json = tmp_path / "r.csv", tmp_path / "r.json"
    res = CliRunner().invoke(autogis, [
        "envmon", "reconcile-event", "--site-id", "SITE1",
        "--submissions-csv", str(subs),
        "--out-csv", str(out_csv), "--out-json", str(out_json)])
    assert res.exit_code == 0, res.output
    summary = json.loads(out_json.read_text(encoding="utf-8"))
    assert summary["clean"] is True
    assert summary["legs_run"] == ["field"]
    assert summary["observations"]                      # water-level block exists


def test_reconcile_event_stalled_exits_2(tmp_path):
    subs = _field_csv(tmp_path, ["MW-1,2026-07-15,GW,AB,COC-001,,"])
    store = tmp_path / "custody.json"
    store.write_text("{}", encoding="utf-8")            # provided but empty COC leg
    res = CliRunner().invoke(autogis, [
        "envmon", "reconcile-event", "--site-id", "SITE1",
        "--submissions-csv", str(subs), "--custody-store", str(store),
        "--out-csv", str(tmp_path / "r.csv"), "--out-json", str(tmp_path / "r.json")])
    assert res.exit_code == 2, res.output


def test_reconcile_event_no_legs_is_usage_error(tmp_path):
    res = CliRunner().invoke(autogis, [
        "envmon", "reconcile-event", "--site-id", "SITE1",
        "--out-csv", str(tmp_path / "r.csv"), "--out-json", str(tmp_path / "r.json")])
    assert res.exit_code != 0
    assert "at least one" in res.output.lower()


def test_reconcile_event_registered_in_capabilities():
    from autogis.runtime.capabilities import TOOLS, requires_arcpy
    assert "reconcile-event" in TOOLS
    assert requires_arcpy("reconcile-event") is False
```

Note `--site-id`: the field/lab/gdb legs need a site id for normalization; when the plan leg is provided it comes from the site config, otherwise `--site-id` supplies it (required if any of field/lab/gdb given without `--site`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/envmon/test_reconcile_event.py -q -k "cli or registered or help or exits or usage or field_only"`
Expected: FAIL — no such command.

- [ ] **Step 3: Implement the command**

```python
# Near the other semantic exit constants (cli.py:2439 area):
# reconcile-event: exit 2 = event does not reconcile (residual/needs_review),
# distinct from exit 1 (QA fail-on breach) — same convention as _COC_DISCREPANCY_EXIT.
_RECONCILE_EVENT_DISCREPANCY_EXIT = 2


@envmon.command("reconcile-event")
@click.option("--site", "site_path", type=click.Path(exists=True),
              help="Site config (plan leg, with --event and --analytes).")
@click.option("--event", "event_path", type=click.Path(exists=True),
              help="Event config (plan leg).")
@click.option("--analytes", "analytes_path", type=click.Path(exists=True),
              help="Analyte dictionary (plan leg).")
@click.option("--site-id", "site_id", default="",
              help="Site id for field/lab/gdb legs when --site is not given.")
@click.option("--submissions-csv", type=click.Path(exists=True),
              help="Raw Survey123 submissions CSV (field leg; normalized in-process).")
@click.option("--custody-store", type=click.Path(exists=True),
              help="Custody store JSON (COC leg).")
@click.option("--lab-results-csv", type=click.Path(exists=True),
              help="Canonical AnalyticalResultRecord CSV (lab leg).")
@click.option("--gdb-samples-csv", type=click.Path(exists=True),
              help="CSV export of Env_Samples (GDB leg).")
@click.option("--dry-wells", type=click.Path(exists=True),
              help="Optional JSON {LocationID: reason} for dry/inactive wells.")
@click.option("--presence-overrides", type=click.Path(exists=True),
              help="Optional JSON {SampleID: {source: required|optional|forbidden}}.")
@click.option("--out-csv", required=True, type=click.Path())
@click.option("--out-json", required=True, type=click.Path())
@qa_report_options
def reconcile_event_cmd(site_path, event_path, analytes_path, site_id,
                        submissions_csv, custody_store, lab_results_csv,
                        gdb_samples_csv, dry_wells, presence_overrides,
                        out_csv, out_json, report, fail_on):
    """Reconcile one event's samples across plan/field/COC/lab/GDB."""
    import json as _json
    import uuid
    from pathlib import Path

    from ..core.common.qa import QACollector, SEV_INFO
    from ..core.common.records_csv import read_records_csv
    from ..core.envmon import custody as custody_mod
    from ..core.envmon import reconcile_event as engine
    from ..core.envmon.gdb_schema import AnalyticalResultRecord, SampleRecord
    from ..core.envmon.normalize_survey123 import load_survey123_csv_submissions

    plan_given = [p for p in (site_path, event_path, analytes_path) if p]
    if plan_given and len(plan_given) != 3:
        raise click.UsageError("--site, --event and --analytes go together.")
    legs, garbled, observations = {}, [], {}
    qa = QACollector()

    if plan_given:
        from ..core.common.config import SiteConfig, load_analyte_dictionary
        from ..core.envmon.create_sampling_event import (
            build_sampling_event_plan, load_event_config)
        site_cfg = SiteConfig.load(Path(site_path))
        site_id = site_id or site_cfg.data.get("site_id", "")
        try:
            plan = build_sampling_event_plan(
                site_cfg.data, load_event_config(Path(event_path)),
                load_analyte_dictionary(Path(analytes_path)),
                run_id=str(uuid.uuid4()))
        except (ValueError, KeyError) as exc:
            raise click.ClickException(f"plan leg failed: {exc}")
        by_id = {}
        for row in plan.expected_samples:      # dedupe rows, union analyte groups (#422 shape)
            attrs = by_id.setdefault(row.sample_id, {
                "location_id": row.location_id, "event_date": row.event_date,
                "matrix": row.matrix, "coc_number": row.coc_number,
                "analytes": set()})
            attrs["analytes"].add(row.analyte_group)
        legs["plan"] = [engine.SourceRow(sid, attrs) for sid, attrs in by_id.items()]

    if submissions_csv:
        if not site_id:
            raise click.UsageError("--site-id (or the plan leg) is required "
                                   "with --submissions-csv.")
        water_levels, samples = load_survey123_csv_submissions(
            Path(submissions_csv), site_id, "reconcile", qa)
        observations["water_levels"] = len(water_levels)
        rows = []
        for s in samples:
            if not (s.get("SampleID") or "").strip():
                garbled.append(str(s))         # sample-form row, id-less: needs_review
            else:
                rows.append(engine.SourceRow(s["SampleID"], s))
        legs["field"] = rows

    if custody_store:
        try:
            store = custody_mod.load_store(Path(custody_store))
        except custody_mod.CustodyError as exc:
            raise click.ClickException(f"custody store unreadable: {exc}")
        rows = []
        for rec in store.values():
            for sid in dict.fromkeys(rec.sample_ids):   # dedupe within a COC (#422)
                rows.append(engine.SourceRow(sid, {
                    "coc_number": rec.coc_number, "event_date": rec.event_date,
                    "state": rec.state}))
        legs["coc"] = rows

    if lab_results_csv:
        records = read_records_csv(Path(lab_results_csv), AnalyticalResultRecord)
        by_id = {}
        for r in records:                       # QC rows included: presence needs them
            attrs = by_id.setdefault(r.SampleID, {
                "location_id": r.LocationID, "sample_date": str(r.SampleDate or ""),
                "matrix": r.Matrix, "analytes": set()})
            if r.AnalyteCanonicalName:
                attrs["analytes"].add(r.AnalyteCanonicalName)
        legs["lab"] = [engine.SourceRow(sid, attrs) for sid, attrs in by_id.items()]

    if gdb_samples_csv:
        records = read_records_csv(Path(gdb_samples_csv), SampleRecord)
        legs["gdb"] = [engine.SourceRow(r.SampleID, {
            "location_id": r.LocationID, "sample_date": str(r.SampleDate or ""),
            "matrix": r.Matrix}) for r in records]

    if not legs:
        raise click.UsageError("Provide at least one source leg.")

    dry = _json.loads(Path(dry_wells).read_text(encoding="utf-8")) if dry_wells else None
    overrides = (_json.loads(Path(presence_overrides).read_text(encoding="utf-8"))
                 if presence_overrides else None)
    result = engine.reconcile_event(legs, overrides=overrides, dry_wells=dry,
                                    garbled=garbled, observations=observations)

    engine.rows_to_csv(result, Path(out_csv))
    Path(out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(out_json).write_text(
        _json.dumps(engine.summary_dict(result), indent=2, sort_keys=True,
                    default=str) + "\n", encoding="utf-8")
    for row in result.rows:
        if row.outcome != engine.OUTCOME_RECONCILED:
            qa.add("WARNING", f"outcome_{row.outcome}",
                   f"{row.key}: {row.outcome} ({';'.join(row.codes)})")
    qa.add(SEV_INFO, "reconcile_summary",
           f"residual={result.residual} clean={result.clean} "
           f"legs={','.join(result.legs_run)}")
    _render_qa(qa, report, fail_on)
    if not result.clean:
        raise SystemExit(_RECONCILE_EVENT_DISCREPANCY_EXIT)
```

Before writing, read the real import names once (`SiteConfig`, `load_analyte_dictionary`, `SEV_WARNING` vs the string `"WARNING"` — match how `cli.py:2519-2536` and nearby commands spell them exactly) and mirror `coc reconcile`'s render-then-exit-2 ordering (`cli.py:2661-2662`). Outcome QA records go in at WARNING severity so default `--fail-on error` does not preempt exit 2 (the custody test at `test_custody.py:249-267` proves that ordering works).

Capabilities — two entries:

```python
# capabilities.py TOOLS (alphabetical near "reconcile-survey123-lab"):
"reconcile-event": Runtime.CLOUD,  # Survey123 Phase 3 five-source event reconciliation (headless)

# capabilities.py _REGISTRY_SEED:
("reconcile-event", "ReconcileMonitoringEvent", "",
 "CLOUD", "stable", "qa",
 "Five-source event reconciliation: plan/Survey123/COC/lab/GDB presence "
 "matrix with per-sample outcomes and zero-residual balance"),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/envmon/test_reconcile_event.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -u && git commit -m "feat(cli): envmon reconcile-event command + capabilities registration"
```

---

### Task 6: Golden fixture event — every outcome at least once

**Files:**
- Test: `tests/envmon/test_reconcile_event.py`

**Interfaces:**
- Consumes: everything above; engine API only (no CLI — the golden event exercises judgment breadth, the CLI e2e already covers plumbing).

- [ ] **Step 1: Write the golden test (it should PASS immediately if Tasks 1–4 are correct — treat any failure as a real engine bug, not a fixture to bend)**

```python
def test_golden_event_every_outcome_and_balance_explains_residual():
    a = lambda loc: {"location_id": loc, "event_date": "2026-07-15", "matrix": "GW"}
    C = lambda n: {"coc_number": n}
    legs = {
        "plan": [re_mod.SourceRow("MW-1-20260715-GW", a("MW-1")),    # clean planned
                 re_mod.SourceRow("MW-3-20260715-GW", a("MW-3")),    # dry / not collected
                 re_mod.SourceRow("MW-6-20260715-GW", a("MW-6"))],   # detail conflict
        "field": [re_mod.SourceRow("MW-1-20260715-GW", a("MW-1")),
                  re_mod.SourceRow("MW-9-20260715-GW", a("MW-9")),   # field-added clean
                  re_mod.SourceRow("MW-2-20260715-GW", a("MW-2")),   # stalled after coc
                  re_mod.SourceRow("MW-5-20260715-GW", a("MW-5")),   # presence gap
                  re_mod.SourceRow("MW-6-20260715-GW", a("MW-6"))],
        "coc": [re_mod.SourceRow("MW-1-20260715-GW", C("C1")),
                re_mod.SourceRow("MW-9-20260715-GW", C("C1")),
                re_mod.SourceRow("MW-2-20260715-GW", C("C1")),
                re_mod.SourceRow("MW-6-20260715-GW", C("C1")),
                re_mod.SourceRow("MW-8-20260715-GW", C("C1")),       # multi-coc
                re_mod.SourceRow("MW-8-20260715-GW", C("C2"))],
        "lab": [re_mod.SourceRow("MW-1-20260715-GW", a("MW-1")),
                re_mod.SourceRow("MW-9-20260715-GW", a("MW-9")),
                re_mod.SourceRow("MW-6-20260715-GW",
                                 {"location_id": "MW-6", "matrix": "SO",
                                  "sample_date": "2026-07-15"}),      # matrix conflict
                re_mod.SourceRow("MW-4-20260715-GW", a("MW-4")),      # orphan
                re_mod.SourceRow("MW-1-20260715-GW-MB", {}),          # lab QC, mask-clean
                re_mod.SourceRow("MW-8-20260715-GW", a("MW-8"))],
        "gdb": [re_mod.SourceRow("MW-1-20260715-GW", a("MW-1")),
                re_mod.SourceRow("MW-9-20260715-GW", a("MW-9")),
                re_mod.SourceRow("MW-5-20260715-GW", a("MW-5")),
                re_mod.SourceRow("MW-6-20260715-GW", a("MW-6")),
                re_mod.SourceRow("MW-8-20260715-GW", a("MW-8"))],
    }
    result = re_mod.reconcile_event(
        legs, dry_wells={"MW-3": "well dry"}, garbled=["??bad-row??"],
        observations={"water_levels": 4, "site_conditions": 2})
    by = {r.key: r.outcome for r in result.rows}
    assert by["MW-1-20260715-GW"] == re_mod.OUTCOME_RECONCILED
    assert by["MW-9-20260715-GW"] == re_mod.OUTCOME_RECONCILED
    assert by["MW-1-20260715-GW-MB"] == re_mod.OUTCOME_RECONCILED
    assert by["MW-2-20260715-GW"] == re_mod.OUTCOME_STALLED
    assert by["MW-3-20260715-GW"] == re_mod.OUTCOME_NOT_COLLECTED
    assert by["MW-4-20260715-GW"] == re_mod.OUTCOME_ORPHAN
    assert by["MW-5-20260715-GW"] == re_mod.OUTCOME_NEEDS_REVIEW
    assert by["MW-6-20260715-GW"] == re_mod.OUTCOME_DETAIL_CONFLICT
    assert by["MW-8-20260715-GW"] == re_mod.OUTCOME_NEEDS_REVIEW   # multi-coc
    assert by["UNPARSEABLE:??bad-row??"] == re_mod.OUTCOME_NEEDS_REVIEW
    assert not result.clean
    # Every point of residual is explained by a named row:
    explained = sum(
        sum(1 for s in re_mod.SOURCES
            if r.mask[s] == re_mod.REQUIRED and not r.present[s])
        + sum(1 for s in re_mod.SOURCES
              if r.mask[s] == re_mod.FORBIDDEN and r.present[s])
        for r in result.rows)
    assert result.residual == explained
    # Observations stayed out of the grid but in the summary:
    s = re_mod.summary_dict(result)
    assert s["observations"] == {"water_levels": 4, "site_conditions": 2}
    assert all(not k.startswith("WL") for k in by)
```

- [ ] **Step 2: Run it**

Run: `python -m pytest tests/envmon/test_reconcile_event.py::test_golden_event_every_outcome_and_balance_explains_residual -v`
Expected: PASS. If any assertion fails, debug the ENGINE (systematic-debugging), don't edit the expected outcomes — this fixture encodes the approved spec §4.

- [ ] **Step 3: Full suite + commit**

Run: `python -m pytest -q` (full suite, repo root). Expected: green (same count as before this branch + new tests).

```bash
git add -u && git commit -m "test(envmon): reconcile-event golden fixture event"
```

---

### Task 7: Docs, spec sync, ADR, real-console smoke

**Files:**
- Modify: `docs/superpowers/specs/2026-07-30-survey123-phase3-event-reconciliation-design.md` (§6 input list — already amended 2026-08-01; verify it matches the shipped options)
- Create: `docs/adr/0119-survey123-phase3-event-reconciliation.md` (**re-verify 0119 is still free** vs origin/main AND all open PRs first — collisions are frequent; `coord reserve-adr` if available)
- Modify: `README.md` (Runtime Matrix row + tool index, following the `reconcile-survey123-lab` row's format)
- Modify: `docs/adr/README.md` index (per `/new-adr` format)

**Interfaces:** none produced — documentation and verification only.

- [ ] **Step 1: Real Windows console smoke (CliRunner masks cp1252 crashes — Phase 6 lesson)**

Run in a REAL PowerShell console (not CliRunner), with a tiny submissions CSV from the test fixture:

```powershell
python -m autogis envmon reconcile-event --site-id SITE1 --submissions-csv .\tmp_subs.csv --out-csv .\tmp_r.csv --out-json .\tmp_r.json
```

Expected: exit 0, readable output, no UnicodeEncodeError. Delete the tmp files after.

- [ ] **Step 2: Write ADR-0119** — decision: Phase 3 gate implementation; six-outcome taxonomy; cascade anchor; QC masks; exact-only; deferred attachment checks + per-record observation tracing (#414); owner-gated exit-gate leg ("sanitized real event reconciles end-to-end" as Proposed sign-off item); #420 limitation note (GDB leg lacks COC linkage until fixed). Follow `docs/adr/README.md` format via `/new-adr`.

- [ ] **Step 3: PR preflight** — the PR description must classify the five probes from `docs/pr-review-failure-mode-audit.md` (`BOUNDARY_SHAPE`, `CONTRACT_REACHABILITY`, `IDENTITY_PROVENANCE`, `SIDE_EFFECT_SAFETY`, `ENVIRONMENT_SEAM`) with a minimal adversarial command each:
  - BOUNDARY_SHAPE: empty legs, id-less rows, duplicate ids (Tasks 2/4 tests are the evidence).
  - CONTRACT_REACHABILITY: exit-2 test; `requires_arcpy("reconcile-event")` test.
  - IDENTITY_PROVENANCE: garbled-id → needs_review test; suggestions-never-consume tests.
  - SIDE_EFFECT_SAFETY: outputs written before exit 2 (assert files exist in the exit-2 CLI test).
  - ENVIRONMENT_SEAM: no arcpy/arcgis import anywhere in the new module (CI leg verifies; locally `python -c "import sys; sys.modules['arcpy']=None; import autogis.core.envmon.reconcile_event"` is NOT valid evidence — cite CI).

- [ ] **Step 4: Commit docs, push branch, open PR (do NOT self-merge; pr-reviewer runs against final head per repo gate)**

```bash
git add -u docs README.md && git commit -m "docs: ADR-0119 + README entries for envmon reconcile-event"
```

---

## Self-Review (done at write time)

1. **Spec coverage:** D1–D10 → Tasks 1–5; six outcomes + precedence → Task 3; balance/residual → Task 4; observation partition + garbled protection → Tasks 4/5 (partition happens at the CLI via `load_survey123_csv_submissions`'s two-stream return); dry-wells → Tasks 3/5; suggestions guards (QC class, NODATE) → Task 4; omitted-vs-unreadable → Task 2 (mask forced OPTIONAL) + Task 5 (`ClickException` on unreadable store); golden fixture → Task 6; owner exit-gate + ADR → Task 7. Gap check: multi-COC → Tasks 2/3/6. Event-window filtering (spec §7): **deliberately thinned** — plan/custody are event-scoped by construction; field/lab/GDB CSVs are event exports in practice; a `--date-from/--date-to` filter adds real code for a filter the operator applies when exporting. Recorded as a deferral in the ADR (Task 7); `excluded` plumbing exists in the result object so adding it later is additive.
2. **Placeholder scan:** none — every step carries runnable code; the two "read the real spelling first" notes (QC_SUFFIXES keys, NODATE format, import names) are verification instructions with concrete fallbacks, not TBDs.
3. **Type consistency:** `SourceRow/GridRow/ReconcileEventResult` names and signatures match across Tasks 1→6; CLI consumes `engine.SourceRow`, `engine.reconcile_event`, `engine.rows_to_csv`, `engine.summary_dict`, `engine.OUTCOME_RECONCILED` — all defined in Tasks 1/4.
