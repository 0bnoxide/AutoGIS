# GenerateEventChangeLog (Roadmap 9.3) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or
> `superpowers:executing-plans` to implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add a headless `envmon generate-event-changelog` CLI command + core module that
diffs two results CSVs (prior and current monitoring event), classifies every
`(LocationID, AnalyteName)` pair into a structured change type, and emits a CSV changelog plus an
optional Excel workbook with one sheet per change type. CLOUD runtime, no arcpy.

**Architecture:**
- New: `autogis/core/envmon/event_changelog.py` — `ChangeType` constants, `ChangeRecord` dataclass,
  `EventChangeResult` dataclass, `generate_event_changelog`, `write_changelog_csv`,
  `write_changelog_workbook`.
- Modify: `autogis/adapters/cli.py` — add `generate-event-changelog` command under the `envmon`
  group (CLOUD, headless — no `_guard`).
- Modify: `autogis/runtime/capabilities.py` — register `"generate-event-changelog": Runtime.CLOUD`.
- New: `tests/envmon/test_event_changelog.py`

**Tech stack:** Python 3.14, `click`, stdlib `csv`/`dataclasses`, `openpyxl` (lazy, ADR-008),
`pytest`. Reuses: `QACollector`/`SEV_*` (`autogis.core.common.qa`), `_render_qa` (`cli.py`).

## Global constraints

- `core/` and `adapters/` import without `arcpy` or `arcgis` present. This is a CLOUD command —
  never call `_guard`, never import arcpy.
- Lazy-import `openpyxl` inside `write_changelog_workbook` (same pattern as `export_comparison_excel.py`).
- CLI reads CSVs via stdlib `csv.DictReader`; core function receives `list[dict]` — no dependency
  on `AnalyticalResultRecord`.
- Run tests with: `python -m pytest -q` (or `python -m pytest tests/envmon/test_event_changelog.py -q`).
- CLI lazy-imports all core modules inside the command function body.

---

### Task 1: Create `autogis/core/envmon/event_changelog.py`

**Files:**
- Create: `autogis/core/envmon/event_changelog.py`

**Complete code:**

```python
"""Generate structured event changelog from two results CSV sets (headless).

Diffs prior-event and current-event result rows keyed on (LocationID, AnalyteName)
and classifies each pair into one of eight ChangeType values.

No arcpy dependency. stdlib + openpyxl (lazy) for optional Excel output.
"""
from __future__ import annotations

import csv
import dataclasses
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from autogis.core.common.qa import QACollector, SEV_ERROR, SEV_INFO, SEV_WARNING


class ChangeType:
    NEW_LOCATION = "NEW_LOCATION"
    DROPPED_LOCATION = "DROPPED_LOCATION"
    NEW_ANALYTE = "NEW_ANALYTE"
    DROPPED_ANALYTE = "DROPPED_ANALYTE"
    NEW_EXCEEDANCE = "NEW_EXCEEDANCE"
    CLEARED_EXCEEDANCE = "CLEARED_EXCEEDANCE"
    VALUE_CHANGE = "VALUE_CHANGE"
    NO_CHANGE = "NO_CHANGE"


@dataclasses.dataclass
class ChangeRecord:
    location_id: str
    analyte_name: str
    change_type: str
    prior_value: Optional[float]
    current_value: Optional[float]
    prior_exceeds: Optional[bool]
    current_exceeds: Optional[bool]
    delta_pct: Optional[float]
    notes: str


@dataclasses.dataclass
class EventChangeResult:
    prior_event_id: str
    current_event_id: str
    changes: List[ChangeRecord]
    new_location_count: int
    dropped_location_count: int
    new_exceedance_count: int
    cleared_exceedance_count: int
    qa: QACollector


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_float(v) -> Optional[float]:
    if v is None or str(v).strip() == "":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _parse_exceed(v) -> Optional[bool]:
    if v is None or str(v).strip() == "":
        return None
    try:
        return int(v) == 1
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def generate_event_changelog(
    prior_rows: List[dict],
    current_rows: List[dict],
    *,
    prior_event_id: str = "prior",
    current_event_id: str = "current",
    delta_pct_threshold: float = 10.0,
) -> EventChangeResult:
    """Diff two result sets and classify each (LocationID, AnalyteName) pair.

    Args:
        prior_rows: List of dict rows from the prior event CSV.
        current_rows: List of dict rows from the current event CSV.
        prior_event_id: Label for the prior event (default ``"prior"``).
        current_event_id: Label for the current event (default ``"current"``).
        delta_pct_threshold: Minimum absolute percent change required to
            classify a row as VALUE_CHANGE rather than NO_CHANGE (default 10.0).

    Returns:
        EventChangeResult containing the classified ChangeRecord list and
        summary counts. The embedded ``qa`` collector holds any warnings.
    """
    qa = QACollector()

    def _key(row: dict) -> Tuple[str, str]:
        return row.get("LocationID", ""), row.get("AnalyteName", "")

    prior_map: Dict[Tuple[str, str], dict] = {_key(r): r for r in prior_rows}
    current_map: Dict[Tuple[str, str], dict] = {_key(r): r for r in current_rows}

    prior_locs = {k[0] for k in prior_map}
    current_locs = {k[0] for k in current_map}
    new_locs = current_locs - prior_locs
    dropped_locs = prior_locs - current_locs

    all_keys = sorted(set(prior_map) | set(current_map))
    changes: List[ChangeRecord] = []

    for loc, analyte in all_keys:
        key = (loc, analyte)
        in_prior = key in prior_map
        in_current = key in current_map

        # --- Entirely new or dropped ---
        if not in_prior:
            cr = current_map[key]
            change_type = (
                ChangeType.NEW_LOCATION if loc in new_locs else ChangeType.NEW_ANALYTE
            )
            changes.append(ChangeRecord(
                location_id=loc,
                analyte_name=analyte,
                change_type=change_type,
                prior_value=None,
                current_value=_parse_float(cr.get("ResultNumeric")),
                prior_exceeds=None,
                current_exceeds=_parse_exceed(cr.get("ExceedsScreeningLevel")),
                delta_pct=None,
                notes="",
            ))
            continue

        if not in_current:
            pr = prior_map[key]
            change_type = (
                ChangeType.DROPPED_LOCATION if loc in dropped_locs
                else ChangeType.DROPPED_ANALYTE
            )
            changes.append(ChangeRecord(
                location_id=loc,
                analyte_name=analyte,
                change_type=change_type,
                prior_value=_parse_float(pr.get("ResultNumeric")),
                current_value=None,
                prior_exceeds=_parse_exceed(pr.get("ExceedsScreeningLevel")),
                current_exceeds=None,
                delta_pct=None,
                notes="",
            ))
            continue

        # --- Present in both — classify the change ---
        pr = prior_map[key]
        cr = current_map[key]

        prior_val = _parse_float(pr.get("ResultNumeric"))
        current_val = _parse_float(cr.get("ResultNumeric"))
        prior_exc = _parse_exceed(pr.get("ExceedsScreeningLevel"))
        current_exc = _parse_exceed(cr.get("ExceedsScreeningLevel"))

        # Compute delta_pct (used by exceedance branches too)
        delta_pct: Optional[float] = None
        if prior_val is not None and current_val is not None:
            if prior_val != 0:
                delta_pct = round((current_val - prior_val) / prior_val * 100, 2)
            else:
                qa.add(SEV_WARNING, "zero_prior_value",
                       f"{loc}/{analyte}: prior value is 0, delta_pct undefined")

        # Exceedance flips take priority over value-change classification
        if prior_exc is False and current_exc is True:
            change_type = ChangeType.NEW_EXCEEDANCE
        elif prior_exc is True and current_exc is False:
            change_type = ChangeType.CLEARED_EXCEEDANCE
        elif delta_pct is not None and abs(delta_pct) > delta_pct_threshold:
            change_type = ChangeType.VALUE_CHANGE
        else:
            change_type = ChangeType.NO_CHANGE

        changes.append(ChangeRecord(
            location_id=loc,
            analyte_name=analyte,
            change_type=change_type,
            prior_value=prior_val,
            current_value=current_val,
            prior_exceeds=prior_exc,
            current_exceeds=current_exc,
            delta_pct=delta_pct,
            notes="",
        ))

    new_loc_count = sum(1 for c in changes if c.change_type == ChangeType.NEW_LOCATION)
    dropped_loc_count = sum(1 for c in changes if c.change_type == ChangeType.DROPPED_LOCATION)
    new_exc_count = sum(1 for c in changes if c.change_type == ChangeType.NEW_EXCEEDANCE)
    cleared_exc_count = sum(1 for c in changes if c.change_type == ChangeType.CLEARED_EXCEEDANCE)

    qa.add(
        SEV_INFO, "changelog_complete",
        f"generate_event_changelog: {len(changes)} record(s) — "
        f"{new_loc_count} new location(s), {dropped_loc_count} dropped location(s), "
        f"{new_exc_count} new exceedance(s), {cleared_exc_count} cleared exceedance(s)",
    )
    return EventChangeResult(
        prior_event_id=prior_event_id,
        current_event_id=current_event_id,
        changes=changes,
        new_location_count=new_loc_count,
        dropped_location_count=dropped_loc_count,
        new_exceedance_count=new_exc_count,
        cleared_exceedance_count=cleared_exc_count,
        qa=qa,
    )


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def write_changelog_csv(result: EventChangeResult, out_path: Path) -> None:
    """Write ChangeRecord list to a flat CSV."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [f.name for f in dataclasses.fields(ChangeRecord)]
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for rec in result.changes:
            writer.writerow(dataclasses.asdict(rec))


def write_changelog_workbook(result: EventChangeResult, out_path: Path) -> None:
    """Write ChangeRecord list to Excel workbook — one sheet per change type.

    Sheets are created for every ChangeType constant, in declaration order.
    Empty sheets (no rows of that type) are still created so the workbook
    structure is predictable. Requires ``openpyxl`` (ADR-008).
    """
    try:
        import openpyxl
        from openpyxl.styles import Font
    except ImportError as exc:
        result.qa.add(SEV_ERROR, "openpyxl_missing",
                      f"openpyxl not installed: {exc}")
        return

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fields = [f.name for f in dataclasses.fields(ChangeRecord)]
    change_type_order = [
        ChangeType.NEW_LOCATION,
        ChangeType.DROPPED_LOCATION,
        ChangeType.NEW_ANALYTE,
        ChangeType.DROPPED_ANALYTE,
        ChangeType.NEW_EXCEEDANCE,
        ChangeType.CLEARED_EXCEEDANCE,
        ChangeType.VALUE_CHANGE,
        ChangeType.NO_CHANGE,
    ]

    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # remove default blank sheet

    for ct in change_type_order:
        ws = wb.create_sheet(ct)
        ws.append(fields)
        for cell in ws[1]:
            cell.font = Font(bold=True)
        ws.freeze_panes = ws["A2"]
        for rec in result.changes:
            if rec.change_type == ct:
                row_dict = dataclasses.asdict(rec)
                ws.append([row_dict.get(f) for f in fields])

    wb.save(out_path)
    result.qa.add(SEV_INFO, "workbook_written",
                  f"Changelog workbook written to {out_path} "
                  f"({len(result.changes)} record(s))")
```

**Steps:**
- [ ] Create module file as shown above
- [ ] Verify `from autogis.core.common.qa import QACollector, SEV_ERROR, SEV_INFO, SEV_WARNING`
  resolves without error in the project environment

---

### Task 2: Write `tests/envmon/test_event_changelog.py`

**Files:**
- Create: `tests/envmon/test_event_changelog.py`

**Complete code:**

```python
"""Tests for GenerateEventChangeLog (roadmap 9.3) — event_changelog.py."""
import zipfile

import pytest

from autogis.core.envmon.event_changelog import (
    ChangeRecord,
    ChangeType,
    EventChangeResult,
    generate_event_changelog,
    write_changelog_csv,
    write_changelog_workbook,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row(loc: str, analyte: str, value=1.0, exceeds=0) -> dict:
    return {
        "LocationID": loc,
        "AnalyteName": analyte,
        "ResultNumeric": str(value) if value is not None else "",
        "ExceedsScreeningLevel": str(exceeds) if exceeds is not None else "",
    }


PRIOR = [
    _row("MW-1", "Benzene", 1.0, 0),
    _row("MW-1", "Toluene", 5.0, 0),
    _row("MW-2", "Benzene", 10.0, 1),
]

CURRENT = [
    _row("MW-1", "Benzene", 1.0, 0),    # NO_CHANGE (0% delta)
    _row("MW-1", "Toluene", 20.0, 0),   # VALUE_CHANGE (+300%)
    _row("MW-2", "Benzene", 2.0, 0),    # CLEARED_EXCEEDANCE (was 1 → 0)
    _row("MW-3", "Benzene", 1.0, 0),    # NEW_LOCATION (MW-3 absent from prior)
]


def _by_key(result: EventChangeResult) -> dict:
    return {(c.location_id, c.analyte_name): c for c in result.changes}


# ---------------------------------------------------------------------------
# Change-type classification
# ---------------------------------------------------------------------------

def test_new_location():
    m = _by_key(generate_event_changelog(PRIOR, CURRENT))
    c = m[("MW-3", "Benzene")]
    assert c.change_type == ChangeType.NEW_LOCATION
    assert c.prior_value is None
    assert c.current_value == pytest.approx(1.0)


def test_dropped_location():
    prior = PRIOR + [_row("MW-99", "Benzene", 5.0, 0)]
    m = _by_key(generate_event_changelog(prior, CURRENT))
    c = m[("MW-99", "Benzene")]
    assert c.change_type == ChangeType.DROPPED_LOCATION
    assert c.current_value is None
    assert c.prior_value == pytest.approx(5.0)


def test_new_analyte_in_existing_location():
    current = CURRENT + [_row("MW-1", "Arsenic", 0.5, 0)]
    m = _by_key(generate_event_changelog(PRIOR, current))
    # MW-1 already in prior, so Arsenic is NEW_ANALYTE (not NEW_LOCATION)
    assert m[("MW-1", "Arsenic")].change_type == ChangeType.NEW_ANALYTE


def test_dropped_analyte_existing_location():
    prior = PRIOR + [_row("MW-2", "Toluene", 3.0, 0)]
    m = _by_key(generate_event_changelog(prior, CURRENT))
    # MW-2 still present in current (Benzene exists), so Toluene is DROPPED_ANALYTE
    assert m[("MW-2", "Toluene")].change_type == ChangeType.DROPPED_ANALYTE


def test_new_exceedance():
    prior = [_row("MW-1", "Lead", 1.0, 0)]
    current = [_row("MW-1", "Lead", 12.0, 1)]
    m = _by_key(generate_event_changelog(prior, current))
    assert m[("MW-1", "Lead")].change_type == ChangeType.NEW_EXCEEDANCE


def test_cleared_exceedance():
    m = _by_key(generate_event_changelog(PRIOR, CURRENT))
    assert m[("MW-2", "Benzene")].change_type == ChangeType.CLEARED_EXCEEDANCE


def test_value_change_above_threshold():
    m = _by_key(generate_event_changelog(PRIOR, CURRENT))
    c = m[("MW-1", "Toluene")]
    assert c.change_type == ChangeType.VALUE_CHANGE
    assert c.delta_pct == pytest.approx(300.0)


def test_no_change_identical_rows():
    m = _by_key(generate_event_changelog(PRIOR, CURRENT))
    assert m[("MW-1", "Benzene")].change_type == ChangeType.NO_CHANGE


def test_delta_pct_below_threshold_is_no_change():
    prior = [_row("MW-1", "Benzene", 10.0, 0)]
    current = [_row("MW-1", "Benzene", 10.5, 0)]   # +5%, below default 10%
    m = _by_key(generate_event_changelog(prior, current, delta_pct_threshold=10.0))
    assert m[("MW-1", "Benzene")].change_type == ChangeType.NO_CHANGE


# ---------------------------------------------------------------------------
# delta_pct calculation
# ---------------------------------------------------------------------------

def test_delta_pct_positive():
    prior = [_row("MW-1", "Benzene", 10.0, 0)]
    current = [_row("MW-1", "Benzene", 15.0, 0)]   # +50%
    m = _by_key(generate_event_changelog(prior, current, delta_pct_threshold=10.0))
    assert m[("MW-1", "Benzene")].delta_pct == pytest.approx(50.0)


def test_delta_pct_negative():
    prior = [_row("MW-1", "Benzene", 20.0, 0)]
    current = [_row("MW-1", "Benzene", 10.0, 0)]   # -50%
    m = _by_key(generate_event_changelog(prior, current, delta_pct_threshold=10.0))
    assert m[("MW-1", "Benzene")].delta_pct == pytest.approx(-50.0)


def test_delta_pct_none_when_prior_zero():
    prior = [_row("MW-1", "Benzene", 0.0, 0)]
    current = [_row("MW-1", "Benzene", 5.0, 0)]
    result = generate_event_changelog(prior, current)
    m = _by_key(result)
    assert m[("MW-1", "Benzene")].delta_pct is None
    assert any(r.category == "zero_prior_value" for r in result.qa.records)


def test_delta_pct_none_when_either_value_missing():
    prior = [_row("MW-1", "Benzene", None, 0)]
    current = [_row("MW-1", "Benzene", 5.0, 0)]
    m = _by_key(generate_event_changelog(prior, current))
    assert m[("MW-1", "Benzene")].delta_pct is None


# ---------------------------------------------------------------------------
# Summary counts and metadata
# ---------------------------------------------------------------------------

def test_summary_counts():
    result = generate_event_changelog(PRIOR, CURRENT)
    assert result.new_location_count == 1         # MW-3
    assert result.dropped_location_count == 0
    assert result.cleared_exceedance_count == 1   # MW-2/Benzene
    assert result.new_exceedance_count == 0


def test_event_ids_propagate():
    result = generate_event_changelog(
        PRIOR, CURRENT,
        prior_event_id="E-2025-Q3",
        current_event_id="E-2026-Q1",
    )
    assert result.prior_event_id == "E-2025-Q3"
    assert result.current_event_id == "E-2026-Q1"


def test_qa_changelog_complete_emitted():
    result = generate_event_changelog(PRIOR, CURRENT)
    assert any(r.category == "changelog_complete" for r in result.qa.records)


def test_empty_inputs_return_no_changes():
    result = generate_event_changelog([], [])
    assert result.changes == []
    assert result.new_location_count == 0


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def test_write_changelog_csv(tmp_path):
    result = generate_event_changelog(PRIOR, CURRENT)
    out = tmp_path / "changelog.csv"
    write_changelog_csv(result, out)
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "location_id" in text
    assert "change_type" in text
    assert "delta_pct" in text


def test_write_changelog_csv_row_count(tmp_path):
    result = generate_event_changelog(PRIOR, CURRENT)
    out = tmp_path / "changelog.csv"
    write_changelog_csv(result, out)
    lines = out.read_text(encoding="utf-8").splitlines()
    # header + one row per change record
    assert len(lines) == 1 + len(result.changes)


def test_write_changelog_workbook(tmp_path):
    result = generate_event_changelog(PRIOR, CURRENT)
    out = tmp_path / "changelog.xlsx"
    write_changelog_workbook(result, out)
    assert out.exists()
    # XLSX is a ZIP archive; check it opens and has sheet XML files
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
    assert any("sheet" in n.lower() for n in names)


def test_write_changelog_workbook_has_all_sheets(tmp_path):
    result = generate_event_changelog(PRIOR, CURRENT)
    out = tmp_path / "changelog.xlsx"
    write_changelog_workbook(result, out)
    import openpyxl
    wb = openpyxl.load_workbook(out)
    expected_sheets = {
        "NEW_LOCATION", "DROPPED_LOCATION", "NEW_ANALYTE", "DROPPED_ANALYTE",
        "NEW_EXCEEDANCE", "CLEARED_EXCEEDANCE", "VALUE_CHANGE", "NO_CHANGE",
    }
    assert expected_sheets == set(wb.sheetnames)


def test_workbook_qa_info_emitted(tmp_path):
    result = generate_event_changelog(PRIOR, CURRENT)
    out = tmp_path / "changelog.xlsx"
    write_changelog_workbook(result, out)
    assert any(r.category == "workbook_written" for r in result.qa.records)
```

**Steps:**
- [ ] Write test file as shown above
- [ ] Run `python -m pytest tests/envmon/test_event_changelog.py -q` — expect `ImportError`
  (module does not exist yet)
- [ ] Create `event_changelog.py` (Task 1)
- [ ] Run tests again — expect all pass
- [ ] Note: `test_write_changelog_workbook_has_all_sheets` requires `openpyxl` installed in the
  test environment; skip if missing (`pytest.importorskip("openpyxl")` may be added if CI lacks it)

---

### Task 3: Wire CLI command in `autogis/adapters/cli.py`

**Files:**
- Modify: `autogis/adapters/cli.py`
- Modify: `autogis/runtime/capabilities.py`

**Complete command code (add after the `compare-events` block, before the LOCAL-tools section):**

```python
@envmon.command("generate-event-changelog")
@click.option("--prior-csv", required=True, type=click.Path(exists=True),
              help="CSV of prior event analytical results (LocationID, AnalyteName, "
                   "ResultNumeric, ExceedsScreeningLevel columns required).")
@click.option("--current-csv", required=True, type=click.Path(exists=True),
              help="CSV of current event analytical results.")
@click.option("--prior-event-id", default="prior", show_default=True,
              help="Label for the prior event (e.g. 'E-2025-Q3').")
@click.option("--current-event-id", default="current", show_default=True,
              help="Label for the current event (e.g. 'E-2026-Q1').")
@click.option("--out", required=True, type=click.Path(),
              help="Output changelog CSV path.")
@click.option("--out-xlsx", default=None, type=click.Path(),
              help="Optional output Excel workbook (one sheet per change type).")
@click.option("--delta-pct-threshold", default=10.0, type=float, show_default=True,
              help="Minimum absolute %% change required to classify as VALUE_CHANGE.")
@click.option("--report", default=None, type=click.Path(),
              help="Write QA report to PATH (.md/.json/.csv by extension).")
@click.option("--fail-on", type=click.Choice(["error", "warning"]),
              default="error", show_default=True)
def generate_event_changelog_cmd(
    prior_csv, current_csv, prior_event_id, current_event_id,
    out, out_xlsx, delta_pct_threshold, report, fail_on,
):
    """Tool 9.3: Generate structured changelog from two monitoring event CSVs.

    Diffs prior and current result CSVs, classifies every (LocationID, AnalyteName)
    pair as NEW_LOCATION, DROPPED_LOCATION, NEW_ANALYTE, DROPPED_ANALYTE,
    NEW_EXCEEDANCE, CLEARED_EXCEEDANCE, VALUE_CHANGE, or NO_CHANGE.
    Headless, no arcpy.
    """
    import csv as _csv
    from autogis.core.envmon.event_changelog import (
        generate_event_changelog,
        write_changelog_csv,
        write_changelog_workbook,
    )

    def _read_csv(path: str) -> list:
        with open(path, newline="", encoding="utf-8") as fh:
            return list(_csv.DictReader(fh))

    prior_rows = _read_csv(prior_csv)
    current_rows = _read_csv(current_csv)

    result = generate_event_changelog(
        prior_rows,
        current_rows,
        prior_event_id=prior_event_id,
        current_event_id=current_event_id,
        delta_pct_threshold=delta_pct_threshold,
    )

    write_changelog_csv(result, Path(out))
    click.echo(f"Written: {out}  ({len(result.changes)} record(s))")
    click.echo(
        f"  NEW_LOCATION: {result.new_location_count}  "
        f"DROPPED_LOCATION: {result.dropped_location_count}  "
        f"NEW_EXCEEDANCE: {result.new_exceedance_count}  "
        f"CLEARED_EXCEEDANCE: {result.cleared_exceedance_count}"
    )

    if out_xlsx:
        write_changelog_workbook(result, Path(out_xlsx))
        click.echo(f"Workbook: {out_xlsx}")

    _render_qa(result.qa, report, fail_on)
```

**capabilities.py line to add (in the `TOOLS` dict, after `"compare-events"`):**

```python
"generate-event-changelog": Runtime.CLOUD,  # tool 9.3
```

**Steps:**
- [ ] Add the command to `autogis/adapters/cli.py` (inside the `envmon` group, headless section)
- [ ] Add `"generate-event-changelog": Runtime.CLOUD` to `TOOLS` in
  `autogis/runtime/capabilities.py`
- [ ] Write a minimal CLI smoke test (or verify via `CliRunner`):

```python
def test_help_lists_options():
    from click.testing import CliRunner
    from autogis.adapters.cli import autogis
    r = CliRunner().invoke(autogis, ["envmon", "generate-event-changelog", "--help"])
    assert r.exit_code == 0
    for opt in (
        "--prior-csv", "--current-csv", "--prior-event-id", "--current-event-id",
        "--out", "--out-xlsx", "--delta-pct-threshold", "--report", "--fail-on",
    ):
        assert opt in r.output
```

- [ ] Run `python -m pytest tests/envmon/test_event_changelog.py -q` — all pass
- [ ] Run `python -m pytest -q` — no regressions
- [ ] Commit:

```
feat(envmon): generate-event-changelog — structured event diff/changelog (Tool 9.3)

Headless event_changelog core + envmon generate-event-changelog CLI. Diffs two
results CSVs keyed on (LocationID, AnalyteName), classifies into 8 ChangeType
values, emits CSV + optional per-change-type Excel workbook. Reuses QACollector
+ _render_qa. No arcpy.
```

---

## Run commands

```bash
# TDD step 1: verify tests fail before module exists
python -m pytest tests/envmon/test_event_changelog.py -q

# TDD step 2: after creating event_changelog.py
python -m pytest tests/envmon/test_event_changelog.py -q

# TDD step 3: after wiring CLI
python -m pytest tests/envmon/test_event_changelog.py -q

# TDD step 4: full suite — no regressions
python -m pytest -q
```

## Self-review

- Change-type priority order: exceedance flip (NEW_EXCEEDANCE / CLEARED_EXCEEDANCE)
  is evaluated before value-change — a row that crosses both thresholds is correctly
  labelled as an exceedance change. ✓
- NEW_LOCATION vs NEW_ANALYTE distinction is keyed on whether the `loc` is entirely
  absent from the prior location set — not just the analyte. Same logic applies to
  DROPPED_LOCATION vs DROPPED_ANALYTE. ✓
- `delta_pct` is `None` when either value is missing or prior is zero; the zero-prior
  case emits a SEV_WARNING `zero_prior_value`. ✓
- `EventChangeResult.qa` is passed directly to `_render_qa` in the CLI command — no
  second `QACollector` created, so all warnings from the core function surface to the
  caller. ✓
- Lazy `openpyxl` import in `write_changelog_workbook` — module imports are arcpy-free
  even when openpyxl is absent. ✓
- `write_changelog_workbook` creates all 8 sheets regardless of row count — predictable
  workbook structure even when some change types have no records. ✓
- No `AnalyticalResultRecord` dependency — core function accepts `list[dict]`, making
  it usable with any CSV source. ✓
- All module-level imports: stdlib + `autogis.core.common.qa` only. ✓
