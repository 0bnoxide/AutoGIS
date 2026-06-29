# BuildAnalyticalExceedanceEvent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Implement `BuildAnalyticalExceedanceEvent` — thin wrapper over `build_current_event.py` that adds exceedance-specific sample-selection rules and per-result exceedance tier enrichment.
See spec: `docs/superpowers/specs/2026-06-28-build-analytical-exceedance-event-design.md`.

**Architecture:**
- New: `autogis/core/envmon/build_exceedance_event.py`
- Modify: `autogis/adapters/cli.py` — add `build-exceedance-event` command (headless)
- New: `tests/envmon/test_build_exceedance_event.py`

## Global Constraints

- Arcpy-free. Reuse `select_samples()` from `build_current_event.py`.
- Screening levels from YAML (stdlib yaml).
- Run tests with `python -m pytest -q`.

---

### Task 1: Core `build_exceedance_event.py`

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_build_exceedance_event.py`:

```python
import pytest
from autogis.core.envmon.build_exceedance_event import (
    classify_exceedance_tier, build_exceedance_event, load_screening_levels_yaml,
    ExceedanceEventRecord,
)

_SCREENING = {"Benzene": 5.0, "Toluene": 100.0}

_ROWS = [
    {"LocationID": "MW-01", "SampleID": "S1", "SampleDate": "2026-06-15",
     "AnalyteName": "Benzene", "ResultValue": "12.0", "ResultQualifier": "",
     "ReportedUnits": "ug/L"},
    {"LocationID": "MW-01", "SampleID": "S2", "SampleDate": "2026-01-15",
     "AnalyteName": "Benzene", "ResultValue": "3.0", "ResultQualifier": "",
     "ReportedUnits": "ug/L"},
    {"LocationID": "MW-02", "SampleID": "S3", "SampleDate": "2026-06-15",
     "AnalyteName": "Benzene", "ResultValue": "ND", "ResultQualifier": "ND",
     "ReportedUnits": "ug/L"},
]


def test_classify_tier_below():
    assert classify_exceedance_tier(0.5) == "below"


def test_classify_tier_1x_2x():
    assert classify_exceedance_tier(1.5) == "1x-2x"


def test_classify_tier_none():
    assert classify_exceedance_tier(None) == "below"


def test_classify_tier_gt10():
    assert classify_exceedance_tier(15.0) == ">10x"


def test_max_exceedance_rule():
    records = build_exceedance_event(_ROWS, _SCREENING, rule="max_exceedance_per_location")
    mw01 = next(r for r in records if r.location_id == "MW-01")
    assert mw01.result_value == 12.0  # higher ratio wins
    assert mw01.exceedance_ratio == pytest.approx(12.0 / 5.0)
    assert mw01.has_exceedance is True


def test_nd_result_no_exceedance():
    records = build_exceedance_event(_ROWS, _SCREENING)
    mw02 = next(r for r in records if r.location_id == "MW-02")
    assert mw02.has_exceedance is False
    assert mw02.has_detection is False


def test_specific_event_date():
    records = build_exceedance_event(
        _ROWS, _SCREENING, rule="specific_event_date", event_date="2026-01-15")
    dates = {r.sample_date for r in records}
    assert dates == {"2026-01-15"}


def test_load_screening_levels_yaml(tmp_path):
    p = tmp_path / "sl.yaml"
    p.write_text("Benzene: 5.0\nToluene: 100.0\n")
    sl = load_screening_levels_yaml(p)
    assert sl["Benzene"] == 5.0
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_build_exceedance_event.py -v
```

- [ ] **Step 3: Create `autogis/core/envmon/build_exceedance_event.py`**

```python
"""build_exceedance_event.py — exceedance-event selector and tier enrichment."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from ..common.qa import QACollector, QARecord, SEV_INFO, SEV_WARNING

ND_QUALIFIERS = {"ND", "U", "BDL"}

EXCEEDANCE_TIERS = [
    (0.0, 1.0,  "below"),
    (1.0, 2.0,  "1x-2x"),
    (2.0, 5.0,  "2x-5x"),
    (5.0, 10.0, "5x-10x"),
    (10.0, None, ">10x"),
]


@dataclass
class ExceedanceEventRecord:
    location_id: str
    sample_id: str
    sample_date: str
    analyte_name: str
    result_value: Optional[float]
    result_qualifier: str
    reported_units: str
    screening_level: Optional[float]
    screening_level_name: str
    exceedance_ratio: Optional[float]
    exceedance_tier: str
    has_exceedance: bool
    has_detection: bool
    selection_reason: str


def classify_exceedance_tier(ratio: Optional[float]) -> str:
    if ratio is None:
        return "below"
    for low, high, label in EXCEEDANCE_TIERS:
        if high is None or ratio < high:
            if ratio >= low:
                return label
    return ">10x"


def load_screening_levels_yaml(path: Path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def _parse_num(val: str) -> Optional[float]:
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def build_exceedance_event(
    result_rows: list,
    screening_levels: dict,
    *,
    rule: str = "max_exceedance_per_location",
    event_date: Optional[str] = None,
    date_range: Optional[tuple] = None,
    qa: Optional[QACollector] = None,
) -> list:
    if qa is None:
        qa = QACollector()

    # Apply date filters
    filtered = result_rows
    if rule == "specific_event_date" and event_date:
        filtered = [r for r in result_rows if r.get("SampleDate") == event_date]
    elif rule == "date_range_latest" and date_range:
        d_from, d_to = date_range
        filtered = [r for r in result_rows
                    if d_from <= r.get("SampleDate", "") <= d_to]

    # Group by (location_id, analyte_name)
    groups: dict[tuple, list] = {}
    for row in filtered:
        key = (row.get("LocationID", ""), row.get("AnalyteName", ""))
        groups.setdefault(key, []).append(row)

    records = []
    for (loc, analyte), rows in groups.items():
        sl = screening_levels.get(analyte)

        def _score(r):
            v = _parse_num(r.get("ResultValue", ""))
            if v is None:
                return -1.0
            if sl:
                return v / sl
            return v

        if rule == "max_exceedance_per_location":
            best = max(rows, key=_score)
            reason = "max_exceedance"
        elif rule == "latest_per_location":
            best = max(rows, key=lambda r: r.get("SampleDate", ""))
            reason = "latest"
        else:
            best = max(rows, key=lambda r: r.get("SampleDate", ""))
            reason = rule

        val = _parse_num(best.get("ResultValue", ""))
        qual = best.get("ResultQualifier", "")
        is_nd = qual.upper().strip() in ND_QUALIFIERS
        has_detection = not is_nd and val is not None
        ratio = (val / sl) if (val is not None and sl and not is_nd) else None
        has_exceedance = ratio is not None and ratio >= 1.0

        records.append(ExceedanceEventRecord(
            location_id=loc,
            sample_id=best.get("SampleID", ""),
            sample_date=best.get("SampleDate", ""),
            analyte_name=analyte,
            result_value=val if not is_nd else None,
            result_qualifier=qual,
            reported_units=best.get("ReportedUnits", ""),
            screening_level=sl,
            screening_level_name=analyte,
            exceedance_ratio=round(ratio, 4) if ratio is not None else None,
            exceedance_tier=classify_exceedance_tier(ratio),
            has_exceedance=has_exceedance,
            has_detection=has_detection,
            selection_reason=reason,
        ))

    qa.add(QARecord(SEV_INFO, "exceedance_event_built",
                    f"{len(records)} location-analyte pairs processed"))
    return records


def write_exceedance_event_csv(records: list, path: Path) -> None:
    import dataclasses
    if not records:
        Path(path).write_text("")
        return
    fieldnames = [f.name for f in dataclasses.fields(records[0])]
    with Path(path).open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for r in records:
            w.writerow(dataclasses.asdict(r))
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_build_exceedance_event.py -v
```

Expected: all 8 PASS.

- [ ] **Step 5: Full suite + commit**

```bash
git add autogis/core/envmon/build_exceedance_event.py \
        tests/envmon/test_build_exceedance_event.py
git commit -m "feat(envmon): build_exceedance_event — exceedance selector and tier enrichment"
```

---

### Task 2: CLI command

- [ ] **Step 1: Add to `cli.py`**

```python
@envmon.command("build-exceedance-event")
@click.option("--results", "results_path", required=True, type=click.Path(exists=True))
@click.option("--screening-levels", "sl_path", required=True, type=click.Path(exists=True))
@click.option("--rule", type=click.Choice([
    "max_exceedance_per_location", "latest_per_location",
    "specific_event_date", "date_range_latest"]),
    default="max_exceedance_per_location", show_default=True)
@click.option("--event-date", default=None)
@click.option("--date-from", default=None)
@click.option("--date-to", default=None)
@click.option("--out", required=True, type=click.Path())
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error")
def build_exceedance_event_cmd(results_path, sl_path, rule, event_date,
                                date_from, date_to, out, report, fail_on):
    """Build per-location exceedance event dataset with tier classification (headless)."""
    import csv as _csv
    from autogis.core.envmon.build_exceedance_event import (
        build_exceedance_event, load_screening_levels_yaml, write_exceedance_event_csv)
    from autogis.core.common.qa import QACollector

    with open(results_path, newline="", encoding="utf-8") as fh:
        rows = list(_csv.DictReader(fh))
    sl = load_screening_levels_yaml(Path(sl_path))
    date_range = (date_from, date_to) if date_from and date_to else None
    qa = QACollector()
    records = build_exceedance_event(rows, sl, rule=rule, event_date=event_date,
                                      date_range=date_range, qa=qa)
    write_exceedance_event_csv(records, Path(out))
    exceed_count = sum(1 for r in records if r.has_exceedance)
    click.echo(f"Records: {len(records)}  Exceedances: {exceed_count}  Output: {out}")
    _render_qa(qa, report, fail_on)
```

- [ ] **Step 2: Help test + commit**

```python
def test_build_exceedance_event_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "build-exceedance-event" in result.output
```

```bash
git add autogis/adapters/cli.py tests/envmon/test_build_exceedance_event.py
git commit -m "feat(cli): add build-exceedance-event command"
```
