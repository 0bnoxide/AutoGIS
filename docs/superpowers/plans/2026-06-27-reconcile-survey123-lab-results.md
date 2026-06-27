# ReconcileSurvey123AndLabResults (Tool 4.5) — Implementation Plan

**Goal:** Add a headless `envmon reconcile-survey123` CLI command + core module that
cross-references Survey123 field-collection records against laboratory EDD records and
produces a reconciliation report: matched pairs, unmatched field records (labs never
received), and orphan lab records (no corresponding field record).

**Architecture:** New pure-core module `autogis/core/envmon/reconcile_survey123.py`
with `reconcile_survey123(field_records, lab_records, *, match_keys, qa)
-> ReconciliationReport`. The report dataclass carries three lists: `matched`,
`field_only`, `lab_only`. A single `click` command reads two CSVs and a match-key
list, calls the function, writes three output CSVs (one per list), renders QA + exit
via `_render_qa`. No arcpy, no openpyxl.

**Tech stack:** Python 3.14, `click`, stdlib `csv`/`dataclasses`/`datetime`, `pytest`.
Reuses: `QACollector` (`common/qa.py`), `_render_qa` (`cli.py`),
`read_records_csv` (`evaluate_rpd_qa.py`).

## Global constraints

- `core/` and `adapters/` import without arcpy. Headless — no `_guard`.
- Command name exactly `reconcile-survey123`. Register as `Runtime.CLOUD`.
- Match keys default to `["SampleID"]`; user can override with
  `--match-keys SampleID,LocationID,SampleDate`.
- Duplicate field-side matches (same key mapped to multiple field rows) emit WARNING
  `duplicate_field_key`. Duplicate lab-side matches emit WARNING `duplicate_lab_key`.
- Output CSVs written to `--output-dir`: `matched.csv`, `field_only.csv`,
  `lab_only.csv`. `--output-dir` created if absent.

---

### Task 1: Core module `reconcile_survey123.py` + unit tests

**Files:**
- Create: `autogis/core/envmon/reconcile_survey123.py`
- Create: `tests/test_reconcile_survey123.py`

**Complete code:**

```python
"""Cross-reference Survey123 field records against lab EDD records (Tool 4.5)."""
from __future__ import annotations
import dataclasses
from typing import Any, Dict, List, Tuple
from ..common.qa import QACollector, SEV_INFO, SEV_WARNING


@dataclasses.dataclass
class ReconciliationReport:
    matched: List[Tuple[Dict, Dict]]  # (field_row, lab_row)
    field_only: List[Dict]
    lab_only: List[Dict]


def _make_key(row: Dict[str, Any], keys: List[str]) -> tuple:
    return tuple(str(row.get(k, "")).strip() for k in keys)


def reconcile_survey123(
    field_records: List[Dict[str, Any]],
    lab_records: List[Dict[str, Any]],
    *,
    match_keys: List[str],
    qa: QACollector,
) -> ReconciliationReport:
    """Match field and lab records on match_keys; report unmatched on both sides."""
    # Index lab records.
    lab_index: Dict[tuple, List[Dict]] = {}
    for row in lab_records:
        k = _make_key(row, match_keys)
        lab_index.setdefault(k, []).append(row)
    for k, rows in lab_index.items():
        if len(rows) > 1:
            qa.add(SEV_WARNING, "duplicate_lab_key",
                   f"Lab key {k} has {len(rows)} records; using first")

    # Index field records.
    field_index: Dict[tuple, List[Dict]] = {}
    for row in field_records:
        k = _make_key(row, match_keys)
        field_index.setdefault(k, []).append(row)
    for k, rows in field_index.items():
        if len(rows) > 1:
            qa.add(SEV_WARNING, "duplicate_field_key",
                   f"Field key {k} has {len(rows)} records; using first")

    matched: List[Tuple[Dict, Dict]] = []
    field_only: List[Dict] = []
    all_field_keys = set()

    for row in field_records:
        k = _make_key(row, match_keys)
        if k in all_field_keys:
            continue  # already processed duplicate
        all_field_keys.add(k)
        lab_rows = lab_index.get(k)
        if lab_rows:
            matched.append((row, lab_rows[0]))
        else:
            field_only.append(row)

    matched_keys = {_make_key(pair[0], match_keys) for pair in matched}
    lab_only = [
        lab_index[k][0]
        for k in lab_index
        if k not in matched_keys
    ]

    qa.add(SEV_INFO, "reconcile_complete",
           f"reconcile_survey123: {len(matched)} matched, "
           f"{len(field_only)} field-only, {len(lab_only)} lab-only")
    return ReconciliationReport(matched=matched, field_only=field_only,
                                lab_only=lab_only)
```

**Test file `tests/test_reconcile_survey123.py`:**

```python
"""Unit tests for reconcile_survey123 (Tool 4.5)."""
from autogis.core.common.qa import QACollector
from autogis.core.envmon.reconcile_survey123 import reconcile_survey123

KEYS = ["SampleID"]

def test_full_match():
    field = [{"SampleID": "S1", "LocationID": "MW-1"},
             {"SampleID": "S2", "LocationID": "MW-2"}]
    lab   = [{"SampleID": "S1", "Analyte": "Benzene"},
             {"SampleID": "S2", "Analyte": "Toluene"}]
    qa = QACollector()
    rpt = reconcile_survey123(field, lab, match_keys=KEYS, qa=qa)
    assert len(rpt.matched) == 2
    assert len(rpt.field_only) == 0
    assert len(rpt.lab_only) == 0

def test_field_only():
    field = [{"SampleID": "S1"}, {"SampleID": "S3"}]
    lab   = [{"SampleID": "S1"}]
    qa = QACollector()
    rpt = reconcile_survey123(field, lab, match_keys=KEYS, qa=qa)
    assert len(rpt.field_only) == 1
    assert rpt.field_only[0]["SampleID"] == "S3"

def test_lab_only():
    field = [{"SampleID": "S1"}]
    lab   = [{"SampleID": "S1"}, {"SampleID": "S99"}]
    qa = QACollector()
    rpt = reconcile_survey123(field, lab, match_keys=KEYS, qa=qa)
    assert len(rpt.lab_only) == 1
    assert rpt.lab_only[0]["SampleID"] == "S99"

def test_duplicate_lab_warns():
    field = [{"SampleID": "S1"}]
    lab   = [{"SampleID": "S1", "A": "x"}, {"SampleID": "S1", "A": "y"}]
    qa = QACollector()
    reconcile_survey123(field, lab, match_keys=KEYS, qa=qa)
    assert any(r.category == "duplicate_lab_key" for r in qa.records)

def test_multi_key_match():
    field = [{"SampleID": "S1", "LocationID": "MW-1"}]
    lab   = [{"SampleID": "S1", "LocationID": "MW-2"}]  # different location
    qa = QACollector()
    rpt = reconcile_survey123(field, lab, match_keys=["SampleID", "LocationID"], qa=qa)
    assert len(rpt.field_only) == 1
    assert len(rpt.lab_only) == 1
```

**Steps:**
- [ ] Write test file, verify ImportError.
- [ ] Implement `reconcile_survey123.py`.
- [ ] Run unit tests, verify pass.

---

### Task 2: Wire CLI + register

```python
@envmon.command("reconcile-survey123")
@click.option("--field-csv", required=True, type=click.Path(exists=True))
@click.option("--lab-csv", required=True, type=click.Path(exists=True))
@click.option("--output-dir", required=True, type=click.Path())
@click.option("--match-keys", default="SampleID",
              help="Comma-separated column names for join key.")
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error")
def reconcile_survey123_cmd(field_csv, lab_csv, output_dir, match_keys, report, fail_on):
    """Tool 4.5: cross-reference Survey123 field records against lab EDD."""
    ...
```

`capabilities.py`: `"reconcile-survey123": Runtime.CLOUD`

**Steps:**
- [ ] Write failing CLI test, verify fail.
- [ ] Add command, update capabilities.
- [ ] Full suite, commit: `feat(envmon): reconcile-survey123 — field/lab cross-reference report (Tool 4.5)`
