# RouteSurvey123Submission Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Implement `normalize_survey123.py` — maps Survey123 JSON/CSV submissions to
the same typed record dicts that `import_to_gdb.py` already writes, then adds a
`route-survey123` CLI command that calls the existing GDB write layer.
See spec: `docs/superpowers/specs/2026-06-27-route-survey123-submission-design.md`.

**Architecture:**
- New: `autogis/core/envmon/normalize_survey123.py`
- Modify: `autogis/adapters/cli.py` — add `route-survey123` command (LOCAL)
- New: `tests/envmon/test_normalize_survey123.py`

**Key insight from graph navigator:** Reuse `create_edd_import_batch`,
`append_records_idempotent`, `finalize_batch`, `write_qa_to_gdb` from `import_to_gdb.py`.
Do NOT reuse `normalize_groundwater.py` / other normalize_*.py — they're Excel-coupled.

## Global Constraints

- Branch: `feat/gdb-schema-upgrade`
- `normalize_survey123.py` is arcpy-free.
- GDB write tier calls `import_to_gdb` functions; those are LOCAL (`# pragma: no cover`).
- Run tests with `python -m pytest -q`.

---

### Task 1: `normalize_survey123.py` — pure Python layer

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_normalize_survey123.py`:

```python
import csv
from pathlib import Path
from autogis.core.envmon.normalize_survey123 import (
    Survey123Field, normalize_survey123_submission,
    load_survey123_csv_submissions,
)
from autogis.core.common.qa import QACollector

_PAYLOAD = {
    "WellID": "MW-01",
    "SamplingDate": "2026-06-15",
    "Matrix": "GW",
    "SampledBy": "Alice",
    "COCNumber": "H281-001",
    "DepthToWater_ft": 12.5,
    "Notes": "",
}


def test_minimal_payload_returns_water_level():
    qa = QACollector()
    wl, samp = normalize_survey123_submission(_PAYLOAD, "H281", "B1", qa)
    assert len(wl) == 1
    assert wl[0]["LocationID"] == "MW-01"
    assert wl[0]["DTW_ft"] == 12.5


def test_minimal_payload_returns_sample_record():
    qa = QACollector()
    wl, samp = normalize_survey123_submission(_PAYLOAD, "H281", "B1", qa)
    assert len(samp) == 1
    assert samp[0]["Matrix"] == "GW"


def test_missing_well_id_qa_error():
    qa = QACollector()
    bad = {k: v for k, v in _PAYLOAD.items() if k != "WellID"}
    normalize_survey123_submission(bad, "H281", "B1", qa)
    assert any(r.category == "missing_required_field" for r in qa.records)


def test_missing_dtw_omits_water_level():
    qa = QACollector()
    no_dtw = {k: v for k, v in _PAYLOAD.items() if k != "DepthToWater_ft"}
    wl, samp = normalize_survey123_submission(no_dtw, "H281", "B1", qa)
    assert wl == []


def test_csv_batch_two_rows(tmp_path):
    p = tmp_path / "s123.csv"
    rows = [
        {"WellID": "MW-01", "SamplingDate": "2026-06-15", "Matrix": "GW",
         "SampledBy": "Alice", "COCNumber": "H281-001", "DepthToWater_ft": "12.5", "Notes": ""},
        {"WellID": "MW-02", "SamplingDate": "2026-06-15", "Matrix": "GW",
         "SampledBy": "Bob", "COCNumber": "H281-001", "DepthToWater_ft": "8.3", "Notes": ""},
    ]
    with p.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    qa = QACollector()
    wl, samp = load_survey123_csv_submissions(p, "H281", "B1", qa)
    assert len(wl) == 2
    assert len(samp) == 2


def test_custom_field_map():
    qa = QACollector()
    payload = {"Well": "MW-01", "Date": "2026-06-15", "Type": "GW",
               "Crew": "Alice", "COC": "H281-001", "DTW": 10.0, "Notes": ""}
    fm = Survey123Field(well_id_field="Well", sampling_date_field="Date",
                        matrix_field="Type", sampled_by_field="Crew",
                        coc_number_field="COC", dtw_field="DTW")
    wl, samp = normalize_survey123_submission(payload, "H281", "B1", qa, field_map=fm)
    assert len(wl) == 1


def test_invalid_date_warns():
    qa = QACollector()
    bad_date = {**_PAYLOAD, "SamplingDate": "not-a-date"}
    normalize_survey123_submission(bad_date, "H281", "B1", qa)
    assert any(r.category == "invalid_date" for r in qa.records)
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_normalize_survey123.py -v
```

- [ ] **Step 3: Create `autogis/core/envmon/normalize_survey123.py`**

```python
"""normalize_survey123.py — map Survey123 JSON/CSV submissions to GDB record dicts.

Arcpy-free. Produces the same typed dicts as normalize_groundwater.py /
normalize_*.py so the existing import_to_gdb write layer can consume them.
"""
from __future__ import annotations

import csv
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..common.qa import QACollector, QARecord, SEV_ERROR, SEV_WARNING


@dataclass
class Survey123Field:
    well_id_field: str = "WellID"
    sampling_date_field: str = "SamplingDate"
    matrix_field: str = "Matrix"
    sampled_by_field: str = "SampledBy"
    coc_number_field: str = "COCNumber"
    dtw_field: str = "DepthToWater_ft"


def _parse_date(value: str, qa: QACollector, context: str) -> Optional[datetime]:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(str(value).strip(), fmt)
        except ValueError:
            continue
    qa.add(QARecord(SEV_WARNING, "invalid_date",
                    f"{context}: cannot parse date {value!r}"))
    return None


def normalize_survey123_submission(
    payload: dict,
    site_id: str,
    batch_id: str,
    qa: QACollector,
    field_map: Optional[Survey123Field] = None,
) -> tuple[list[dict], list[dict]]:
    fm = field_map or Survey123Field()
    well_id = payload.get(fm.well_id_field)
    if not well_id:
        qa.add(QARecord(SEV_ERROR, "missing_required_field",
                        f"Survey123 submission missing {fm.well_id_field!r}"))
        return [], []

    date_raw = payload.get(fm.sampling_date_field, "")
    dt = _parse_date(date_raw, qa, f"submission/{well_id}") if date_raw else None
    matrix = payload.get(fm.matrix_field, "GW")
    sampled_by = payload.get(fm.sampled_by_field, "")
    coc = payload.get(fm.coc_number_field, "")
    dtw_raw = payload.get(fm.dtw_field)

    water_levels: list[dict] = []
    if dtw_raw is not None:
        try:
            dtw = float(dtw_raw)
            water_levels.append({
                "ImportBatchID": batch_id,
                "SiteID": site_id,
                "LocationID": str(well_id),
                "MeasurementDate": dt,
                "DTW_ft": dtw,
                "GWE_ft": None,  # computed when TOC elevation is available
                "MeasuredBy": sampled_by,
                "MeasurementMethod": "Survey123",
            })
        except (TypeError, ValueError):
            qa.add(QARecord(SEV_WARNING, "invalid_dtw",
                            f"{well_id}: cannot parse DTW value {dtw_raw!r}"))

    sample_id = f"{well_id}-{dt.strftime('%Y%m%d') if dt else 'NODATE'}-{matrix}"
    samples: list[dict] = [{
        "ImportBatchID": batch_id,
        "SiteID": site_id,
        "LocationID": str(well_id),
        "SampleID": sample_id,
        "SampleDate": dt,
        "Matrix": matrix,
        "SampledBy": sampled_by,
        "COCNumber": coc,
        "SampleSource": "Survey123",
    }]
    return water_levels, samples


def load_survey123_csv_submissions(
    path: Path,
    site_id: str,
    batch_id: str,
    qa: QACollector,
    field_map: Optional[Survey123Field] = None,
) -> tuple[list[dict], list[dict]]:
    all_wl: list[dict] = []
    all_samp: list[dict] = []
    with Path(path).open(newline="", encoding="utf-8") as fh:
        for i, row in enumerate(csv.DictReader(fh)):
            step_batch = f"{batch_id}_{i}"
            wl, samp = normalize_survey123_submission(
                dict(row), site_id, step_batch, qa, field_map)
            all_wl.extend(wl)
            all_samp.extend(samp)
    return all_wl, all_samp
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_normalize_survey123.py -v
```

Expected: all 7 PASS.

- [ ] **Step 5: Full suite + commit**

```bash
git add autogis/core/envmon/normalize_survey123.py tests/envmon/test_normalize_survey123.py
git commit -m "feat(envmon): normalize_survey123 — JSON/CSV submission → GDB record dicts"
```

---

### Task 2: CLI command `route-survey123`

- [ ] **Step 1: Add to `cli.py`** (LOCAL — arcpy needed to write GDB)

```python
@envmon.command("route-survey123")
@click.argument("input_path", metavar="INPUT", type=click.Path(exists=True))
@click.option("--site", "site_id", required=True)
@click.option("--gdb", "gdb_path", required=True, type=click.Path())
@click.option("--batch-id", default=None, help="Override auto-generated batch ID.")
@click.option("--format", "input_format",
              type=click.Choice(["csv", "json"]), default="csv", show_default=True)
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error")
def route_survey123_cmd(input_path, site_id, gdb_path, batch_id, input_format,
                        report, fail_on):
    """Route Survey123 field submissions into the GDB (ArcGIS Pro)."""
    import json
    import uuid
    _guard("route-survey123")
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.normalize_survey123 import (
        normalize_survey123_submission, load_survey123_csv_submissions)
    from autogis.core.envmon.import_to_gdb import (
        create_edd_import_batch, append_records_idempotent,
        finalize_batch, write_qa_to_gdb)

    bid = batch_id or f"S123-{uuid.uuid4().hex[:8].upper()}"
    qa = QACollector()

    if input_format == "json":
        payload = json.loads(Path(input_path).read_text(encoding="utf-8"))
        wl, samp = normalize_survey123_submission(payload, site_id, bid, qa)
    else:
        wl, samp = load_survey123_csv_submissions(Path(input_path), site_id, bid, qa)

    create_edd_import_batch(gdb_path, bid, site_id, source="Survey123")
    append_records_idempotent(gdb_path, "Env_WaterLevels", wl, bid, qa)
    append_records_idempotent(gdb_path, "Env_Samples", samp, bid, qa)
    finalize_batch(gdb_path, bid)
    write_qa_to_gdb(gdb_path, qa, bid)

    click.echo(f"Batch {bid}: {len(wl)} water levels, {len(samp)} samples imported.")
    _render_qa(qa, report, fail_on)
```

- [ ] **Step 2: Help test + commit**

```python
def test_route_survey123_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "route-survey123" in result.output
```

```bash
git add autogis/adapters/cli.py tests/envmon/test_normalize_survey123.py
git commit -m "feat(cli): add route-survey123 command (LOCAL, Survey123 JSON/CSV → GDB)"
```
