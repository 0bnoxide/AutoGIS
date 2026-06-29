# SurveyToWellElevationUpdate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Implement `SurveyToWellElevationUpdate` — join RTK survey points to well table, compute elevation deltas, write patch CSV + audit history.
See spec: `docs/superpowers/specs/2026-06-28-survey-to-well-elevation-update-design.md`.

**Architecture:**
- New: `autogis/core/envmon/survey_well_elevation_update.py`
- Modify: `autogis/adapters/cli.py` — add `survey-to-well-elevations` command (headless)
- New: `tests/envmon/test_survey_well_elevation_update.py`

## Global Constraints

- Arcpy-free. stdlib only: `csv`, `datetime`, `uuid`.
- Input: `SurveyPoints_QA` CSV + `Env_Wells` CSV. Output: patch CSV + history CSV.
- Run tests with `python -m pytest -q`.

---

### Task 1: Core `survey_well_elevation_update.py`

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_survey_well_elevation_update.py`:

```python
from pathlib import Path
import csv
import pytest
from autogis.core.envmon.survey_well_elevation_update import (
    WellElevationDelta, compute_elevation_deltas,
    write_well_elevation_patch, ElevationUpdateResult,
)

_SURVEY = [
    {"location_id": "MW-01", "ground_elev_ft": "105.5",
     "toc_elev_ft": "106.1", "survey_date": "2026-06-15",
     "point_id": "SP-01", "qa_status": "pass"},
    {"location_id": "MW-02", "ground_elev_ft": "98.0",
     "toc_elev_ft": "98.6", "survey_date": "2026-06-15",
     "point_id": "SP-02", "qa_status": "pass"},
]
_WELLS = [
    {"LocationID": "MW-01", "GroundElev_ft": "105.0",
     "TOC_Elev_ft": "105.6", "TOC_Offset_ft": "0.6"},
    {"LocationID": "MW-02", "GroundElev_ft": "98.0",
     "TOC_Elev_ft": "98.6", "TOC_Offset_ft": "0.6"},
]


def test_delta_computed():
    result = compute_elevation_deltas(_SURVEY, _WELLS)
    mw01 = next(d for d in result.deltas if d.location_id == "MW-01")
    assert mw01.delta_ground_elev == pytest.approx(0.5)
    assert mw01.new_ground_elev == pytest.approx(105.5)


def test_no_change_status():
    result = compute_elevation_deltas(_SURVEY, _WELLS)
    mw02 = next(d for d in result.deltas if d.location_id == "MW-02")
    assert mw02.status == "no_change"


def test_large_change_flagged():
    survey = [{"location_id": "MW-01", "ground_elev_ft": "106.5",
               "toc_elev_ft": "107.1", "survey_date": "2026-06-15",
               "point_id": "SP-01", "qa_status": "pass"}]
    result = compute_elevation_deltas(survey, _WELLS, large_change_threshold_ft=0.5)
    mw01 = next(d for d in result.deltas if d.location_id == "MW-01")
    assert mw01.is_large_change is True


def test_no_survey_point():
    survey = [{"location_id": "MW-01", "ground_elev_ft": "105.5",
               "toc_elev_ft": "106.1", "survey_date": "2026-06-15",
               "point_id": "SP-01", "qa_status": "pass"}]
    result = compute_elevation_deltas(survey, _WELLS)
    mw02 = next(d for d in result.deltas if d.location_id == "MW-02")
    assert mw02.status == "no_survey_point"


def test_write_patch_csv(tmp_path):
    result = compute_elevation_deltas(_SURVEY, _WELLS)
    patch = tmp_path / "patch.csv"
    hist  = tmp_path / "history.csv"
    write_well_elevation_patch(result, patch, hist)
    with patch.open() as fh:
        rows = list(csv.DictReader(fh))
    # Only MW-01 changed
    assert len(rows) == 1
    assert rows[0]["LocationID"] == "MW-01"


def test_history_csv_written(tmp_path):
    result = compute_elevation_deltas(_SURVEY, _WELLS)
    patch = tmp_path / "patch.csv"
    hist  = tmp_path / "history.csv"
    write_well_elevation_patch(result, patch, hist)
    with hist.open() as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) >= 1
    assert "location_id" in rows[0]


def test_toc_offset_recomputed():
    result = compute_elevation_deltas(_SURVEY, _WELLS)
    mw01 = next(d for d in result.deltas if d.location_id == "MW-01")
    # new_toc - new_ground = 106.1 - 105.5 = 0.6
    assert mw01.delta_toc_elev == pytest.approx(0.5)
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_survey_well_elevation_update.py -v
```

- [ ] **Step 3: Create `autogis/core/envmon/survey_well_elevation_update.py`**

```python
"""survey_well_elevation_update.py — RTK survey → well elevation patch + audit."""
from __future__ import annotations

import csv
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..common.qa import QACollector, QARecord, SEV_INFO, SEV_WARNING

_LARGE_CHANGE_THRESHOLD_FT = 0.5


@dataclass
class WellElevationDelta:
    location_id: str
    prior_ground_elev: Optional[float]
    new_ground_elev: Optional[float]
    prior_toc_elev: Optional[float]
    new_toc_elev: Optional[float]
    delta_ground_elev: Optional[float]
    delta_toc_elev: Optional[float]
    survey_date: str
    survey_point_id: str
    is_large_change: bool
    status: str   # updated | no_change | no_survey_point | error


@dataclass
class ElevationUpdateResult:
    deltas: list
    update_count: int
    no_change_count: int
    missing_count: int
    qa: QACollector


def _f(v: str) -> Optional[float]:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def compute_elevation_deltas(
    survey_points: list,
    well_rows: list,
    *,
    large_change_threshold_ft: float = _LARGE_CHANGE_THRESHOLD_FT,
    qa: Optional[QACollector] = None,
) -> ElevationUpdateResult:
    if qa is None:
        qa = QACollector()

    # Index survey points by location_id
    survey_idx = {r.get("location_id", ""): r for r in survey_points
                  if r.get("qa_status", "pass").lower() == "pass"}

    deltas = []
    update_count = no_change_count = missing_count = 0

    for well in well_rows:
        loc = well.get("LocationID", "")
        sp = survey_idx.get(loc)

        if sp is None:
            deltas.append(WellElevationDelta(
                location_id=loc,
                prior_ground_elev=_f(well.get("GroundElev_ft")),
                new_ground_elev=None, prior_toc_elev=_f(well.get("TOC_Elev_ft")),
                new_toc_elev=None,
                delta_ground_elev=None, delta_toc_elev=None,
                survey_date="", survey_point_id="",
                is_large_change=False, status="no_survey_point",
            ))
            missing_count += 1
            qa.add(QARecord(SEV_WARNING, "no_survey_point",
                            f"{loc} has no matching survey point."))
            continue

        prior_ge = _f(well.get("GroundElev_ft"))
        new_ge   = _f(sp.get("ground_elev_ft"))
        prior_te = _f(well.get("TOC_Elev_ft"))
        new_te   = _f(sp.get("toc_elev_ft"))

        delta_ge = (new_ge - prior_ge) if (new_ge is not None and prior_ge is not None) else None
        delta_te = (new_te - prior_te) if (new_te is not None and prior_te is not None) else None
        is_large = abs(delta_ge or 0) > large_change_threshold_ft

        changed = (delta_ge is not None and abs(delta_ge) > 1e-4) or \
                  (delta_te is not None and abs(delta_te) > 1e-4)
        status = "updated" if changed else "no_change"
        if changed:
            update_count += 1
        else:
            no_change_count += 1

        if is_large:
            qa.add(QARecord(SEV_WARNING, "large_elevation_change",
                            f"{loc}: ΔGE={delta_ge:.3f} ft exceeds threshold"))

        deltas.append(WellElevationDelta(
            location_id=loc,
            prior_ground_elev=prior_ge, new_ground_elev=new_ge,
            prior_toc_elev=prior_te, new_toc_elev=new_te,
            delta_ground_elev=round(delta_ge, 4) if delta_ge is not None else None,
            delta_toc_elev=round(delta_te, 4) if delta_te is not None else None,
            survey_date=sp.get("survey_date", ""),
            survey_point_id=sp.get("point_id", ""),
            is_large_change=is_large, status=status,
        ))

    qa.add(QARecord(SEV_INFO, "elevation_update_computed",
                    f"Updated: {update_count}  No change: {no_change_count}  "
                    f"Missing: {missing_count}"))
    return ElevationUpdateResult(
        deltas=deltas, update_count=update_count,
        no_change_count=no_change_count, missing_count=missing_count, qa=qa,
    )


def write_well_elevation_patch(
    result: ElevationUpdateResult,
    patch_path: Path,
    history_path: Path,
    survey_batch_id: str = "",
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    patch_fields = ["LocationID", "GroundElev_ft", "TOC_Elev_ft", "TOC_Offset_ft"]
    hist_fields = [
        "history_id", "location_id", "survey_date", "survey_batch_id",
        "prior_ground_elev", "new_ground_elev", "delta_ground_elev",
        "prior_toc_elev", "new_toc_elev", "delta_toc_elev", "updated_at",
    ]

    updated = [d for d in result.deltas if d.status == "updated"]

    with Path(patch_path).open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=patch_fields)
        w.writeheader()
        for d in updated:
            toc_offset = ((d.new_toc_elev - d.new_ground_elev)
                          if d.new_toc_elev is not None and d.new_ground_elev is not None
                          else None)
            w.writerow({
                "LocationID": d.location_id,
                "GroundElev_ft": d.new_ground_elev,
                "TOC_Elev_ft": d.new_toc_elev,
                "TOC_Offset_ft": round(toc_offset, 4) if toc_offset is not None else "",
            })

    write_header = not Path(history_path).exists()
    with Path(history_path).open("a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=hist_fields)
        if write_header:
            w.writeheader()
        for d in updated:
            w.writerow({
                "history_id": str(uuid.uuid4()),
                "location_id": d.location_id,
                "survey_date": d.survey_date,
                "survey_batch_id": survey_batch_id,
                "prior_ground_elev": d.prior_ground_elev,
                "new_ground_elev": d.new_ground_elev,
                "delta_ground_elev": d.delta_ground_elev,
                "prior_toc_elev": d.prior_toc_elev,
                "new_toc_elev": d.new_toc_elev,
                "delta_toc_elev": d.delta_toc_elev,
                "updated_at": now,
            })
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_survey_well_elevation_update.py -v
```

Expected: all 7 PASS.

- [ ] **Step 5: Full suite + commit**

```bash
git add autogis/core/envmon/survey_well_elevation_update.py \
        tests/envmon/test_survey_well_elevation_update.py
git commit -m "feat(envmon): survey_well_elevation_update — RTK survey → elevation patch + audit"
```

---

### Task 2: CLI command

- [ ] **Step 1: Add to `cli.py`**

```python
@envmon.command("survey-to-well-elevations")
@click.option("--survey-points", "survey_path", required=True, type=click.Path(exists=True))
@click.option("--wells", "wells_path", required=True, type=click.Path(exists=True))
@click.option("--patch-out", required=True, type=click.Path())
@click.option("--history-out", required=True, type=click.Path())
@click.option("--large-change-threshold", type=float, default=0.5, show_default=True)
@click.option("--batch-id", default="")
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="warning")
def survey_to_well_elevations_cmd(survey_path, wells_path, patch_out, history_out,
                                   large_change_threshold, batch_id, report, fail_on):
    """Compute elevation deltas from RTK survey and write well update patch (headless)."""
    import csv as _csv
    from autogis.core.envmon.survey_well_elevation_update import (
        compute_elevation_deltas, write_well_elevation_patch)
    from autogis.core.common.qa import QACollector

    with open(survey_path, newline="", encoding="utf-8") as fh:
        survey = list(_csv.DictReader(fh))
    with open(wells_path, newline="", encoding="utf-8") as fh:
        wells = list(_csv.DictReader(fh))
    qa = QACollector()
    result = compute_elevation_deltas(survey, wells,
                                       large_change_threshold_ft=large_change_threshold,
                                       qa=qa)
    write_well_elevation_patch(result, Path(patch_out), Path(history_out),
                                survey_batch_id=batch_id)
    click.echo(f"Updated: {result.update_count}  No change: {result.no_change_count}  "
               f"Missing: {result.missing_count}")
    _render_qa(qa, report, fail_on)
```

- [ ] **Step 2: Help test + commit**

```python
def test_survey_to_well_elevations_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "survey-to-well-elevations" in result.output
```

```bash
git add autogis/adapters/cli.py tests/envmon/test_survey_well_elevation_update.py
git commit -m "feat(cli): add survey-to-well-elevations command"
```
