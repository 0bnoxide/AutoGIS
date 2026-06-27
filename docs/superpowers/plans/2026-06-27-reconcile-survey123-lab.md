# ReconcileSurvey123AndLabResults Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Implement `ReconcileSurvey123AndLabResults` — three-way field/lab/GIS sample
comparison before import. See spec: `docs/superpowers/specs/2026-06-27-reconcile-survey123-lab-design.md`.

**Architecture:**
- New: `autogis/core/envmon/reconcile_survey123_lab.py`
- Modify: `autogis/adapters/cli.py` — add `reconcile-survey123-lab` command (headless)
- New: `tests/envmon/test_reconcile_survey123_lab.py`

## Global Constraints

- Branch: `feat/gdb-schema-upgrade`
- Arcpy-free. CSV inputs for both field and lab data.
- Reuse `difflib.SequenceMatcher` from stdlib (no new packages).
- Run tests with `python -m pytest -q`.

---

### Task 1: Core `reconcile_survey123_lab.py`

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_reconcile_survey123_lab.py`:

```python
import csv
from pathlib import Path
import pytest
from autogis.core.envmon.reconcile_survey123_lab import (
    Survey123Sample, LabSample, reconcile_field_lab,
    reconcile_to_qa, load_survey123_csv,
)

_FIELD = [Survey123Sample("H281-MW01-20260615-GW", "MW-01", "2026-06-15", "GW")]
_LAB_MATCH = [LabSample("H281-MW01-20260615-GW", "MW-01", "2026-06-15", "GW", 10)]
_LAB_FUZZY = [LabSample("H281-MW01-20260615GW", "MW-01", "2026-06-15", "GW", 10)]  # no dash
_LAB_DATE_MISMATCH = [LabSample("H281-MW01-20260615-GW", "MW-01", "2026-06-16", "GW", 10)]
_LAB_MATRIX_MISMATCH = [LabSample("H281-MW01-20260615-GW", "MW-01", "2026-06-15", "SOIL", 10)]
_LAB_NO_MATCH = [LabSample("H281-MW99-20260615-GW", "MW-99", "2026-06-15", "GW", 10)]


def test_exact_match_one_pair():
    r = reconcile_field_lab(_FIELD, _LAB_MATCH)
    assert len(r.matched) == 1
    assert r.field_only == []
    assert r.lab_only == []


def test_fuzzy_match_flags_sample_id_mismatch():
    r = reconcile_field_lab(_FIELD, _LAB_FUZZY, threshold=0.8)
    assert len(r.matched) == 1
    assert any("sample_id_mismatch" in f for f in r.flags)


def test_date_mismatch_flagged():
    r = reconcile_field_lab(_FIELD, _LAB_DATE_MISMATCH)
    assert any("date_mismatch" in f for f in r.flags)


def test_matrix_mismatch_qa_error():
    r = reconcile_field_lab(_FIELD, _LAB_MATRIX_MISMATCH)
    qa = reconcile_to_qa(r)
    assert any(rec.category == "matrix_mismatch" for rec in qa.records)


def test_field_only_sample():
    r = reconcile_field_lab(_FIELD, _LAB_NO_MATCH)
    assert len(r.field_only) == 1
    assert r.matched == []


def test_lab_only_sample():
    r = reconcile_field_lab([], _LAB_MATCH)
    assert len(r.lab_only) == 1


def test_reconcile_to_qa_field_only_warning():
    r = reconcile_field_lab(_FIELD, _LAB_NO_MATCH)
    qa = reconcile_to_qa(r)
    assert any(rec.category == "field_only_sample" for rec in qa.records)


def test_load_survey123_csv(tmp_path):
    p = tmp_path / "s123.csv"
    with p.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["SampleID","LocationID","SamplingDate","Matrix","SampledBy"])
        w.writeheader()
        w.writerow({"SampleID": "H281-MW01-20260615-GW", "LocationID": "MW-01",
                    "SamplingDate": "2026-06-15", "Matrix": "GW", "SampledBy": "Alice"})
    samples = load_survey123_csv(p)
    assert len(samples) == 1
    assert samples[0].location_id == "MW-01"
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_reconcile_survey123_lab.py -v
```

- [ ] **Step 3: Create `autogis/core/envmon/reconcile_survey123_lab.py`**

```python
"""reconcile_survey123_lab.py — three-way field/lab/GIS sample reconciliation."""
from __future__ import annotations

import csv
import difflib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..common.qa import QACollector, QARecord, SEV_ERROR, SEV_WARNING, SEV_INFO

DEFAULT_HEADER_MAP = {
    "sample_id": "SampleID",
    "location_id": "LocationID",
    "sample_date": "SamplingDate",
    "matrix": "Matrix",
    "sampled_by": "SampledBy",
}


@dataclass
class Survey123Sample:
    sample_id: str
    location_id: str
    sample_date: str
    matrix: str
    sampled_by: str = ""


@dataclass
class LabSample:
    sample_id: str
    location_id: str
    sample_date: str
    matrix: str
    analyte_count: int = 0


@dataclass
class ReconcileS123LabResult:
    matched: list[tuple[Survey123Sample, LabSample]] = field(default_factory=list)
    field_only: list[Survey123Sample] = field(default_factory=list)
    lab_only: list[LabSample] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)


def load_survey123_csv(
    path: Path,
    header_map: Optional[dict[str, str]] = None,
) -> list[Survey123Sample]:
    hm = {**DEFAULT_HEADER_MAP, **(header_map or {})}
    out: list[Survey123Sample] = []
    with Path(path).open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            out.append(Survey123Sample(
                sample_id=row.get(hm["sample_id"], ""),
                location_id=row.get(hm["location_id"], ""),
                sample_date=row.get(hm["sample_date"], ""),
                matrix=row.get(hm["matrix"], ""),
                sampled_by=row.get(hm["sampled_by"], ""),
            ))
    return out


def _sim(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.upper(), b.upper()).ratio()


def reconcile_field_lab(
    field_samples: list[Survey123Sample],
    lab_samples: list[LabSample],
    threshold: float = 0.85,
) -> ReconcileS123LabResult:
    result = ReconcileS123LabResult()
    unmatched_lab = list(lab_samples)

    for fs in field_samples:
        # exact match first
        exact = next((ls for ls in unmatched_lab if ls.sample_id == fs.sample_id), None)
        if exact:
            unmatched_lab.remove(exact)
            _check_pair(result, fs, exact)
            continue
        # fuzzy match
        best = max(unmatched_lab, key=lambda ls: _sim(fs.sample_id, ls.sample_id),
                   default=None)
        if best and _sim(fs.sample_id, best.sample_id) >= threshold:
            unmatched_lab.remove(best)
            result.flags.append(
                f"sample_id_mismatch: field={fs.sample_id!r} lab={best.sample_id!r}")
            _check_pair(result, fs, best)
        else:
            result.field_only.append(fs)

    result.lab_only.extend(unmatched_lab)
    return result


def _check_pair(result: ReconcileS123LabResult,
                fs: Survey123Sample, ls: LabSample) -> None:
    result.matched.append((fs, ls))
    if fs.sample_date != ls.sample_date:
        result.flags.append(
            f"date_mismatch: field={fs.sample_date} lab={ls.sample_date} "
            f"sample={fs.sample_id}")
    if fs.matrix.upper() != ls.matrix.upper():
        result.flags.append(
            f"matrix_mismatch: field={fs.matrix} lab={ls.matrix} "
            f"sample={fs.sample_id}")
    if fs.location_id.upper() != ls.location_id.upper():
        result.flags.append(
            f"location_mismatch: field={fs.location_id} lab={ls.location_id}")


def reconcile_to_qa(result: ReconcileS123LabResult) -> QACollector:
    qa = QACollector()
    for flag in result.flags:
        if "matrix_mismatch" in flag:
            sev, cat = SEV_ERROR, "matrix_mismatch"
        elif "sample_id_mismatch" in flag:
            sev, cat = SEV_WARNING, "sample_id_mismatch"
        elif "date_mismatch" in flag:
            sev, cat = SEV_WARNING, "date_mismatch"
        else:
            sev, cat = SEV_WARNING, "location_mismatch"
        qa.add(QARecord(severity=sev, category=cat, message=flag))
    for fs in result.field_only:
        qa.add(QARecord(SEV_WARNING, "field_only_sample",
                        f"Field sample {fs.sample_id!r} has no lab result."))
    for ls in result.lab_only:
        qa.add(QARecord(SEV_WARNING, "lab_only_sample",
                        f"Lab sample {ls.sample_id!r} has no field submission."))
    qa.add(QARecord(SEV_INFO, "reconcile_complete",
                    f"Matched: {len(result.matched)}  "
                    f"Field-only: {len(result.field_only)}  "
                    f"Lab-only: {len(result.lab_only)}"))
    return qa
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_reconcile_survey123_lab.py -v
```

Expected: all 8 PASS.

- [ ] **Step 5: Full suite + commit**

```bash
git add autogis/core/envmon/reconcile_survey123_lab.py tests/envmon/test_reconcile_survey123_lab.py
git commit -m "feat(envmon): reconcile_survey123_lab — three-way field/lab sample comparison"
```

---

### Task 2: CLI command

- [ ] **Step 1: Add to `cli.py`** (headless)

```python
@envmon.command("reconcile-survey123-lab")
@click.option("--survey", "survey_csv", required=True, type=click.Path(exists=True),
              help="Survey123 export CSV.")
@click.option("--edd", "edd_path", required=True, type=click.Path(exists=True),
              help="Lab EDD CSV or XLSX.")
@click.option("--edd-profile", "profile_path", required=True, type=click.Path(exists=True),
              help="Lab EDD profile YAML.")
@click.option("--site", "site_id", required=True)
@click.option("--threshold", type=float, default=0.85, show_default=True)
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error")
def reconcile_survey123_lab_cmd(survey_csv, edd_path, profile_path, site_id,
                                threshold, report, fail_on):
    """Pre-production: reconcile Survey123 field submissions vs lab EDD (headless)."""
    from autogis.core.envmon.reconcile_survey123_lab import (
        load_survey123_csv, reconcile_field_lab, reconcile_to_qa)
    from autogis.core.common.config import ParserProfile
    from autogis.core.envmon.edd_importer import extract_sample_roster

    field_samples = load_survey123_csv(Path(survey_csv))
    profile = ParserProfile.load(Path(profile_path))
    lab_samples = extract_sample_roster(Path(edd_path), profile, site_id)

    result = reconcile_field_lab(field_samples, lab_samples, threshold=threshold)
    qa = reconcile_to_qa(result)
    _render_qa(qa, report, fail_on)
```

> Note: `extract_sample_roster()` is a thin addition to `edd_importer.py` that runs
> the EDD parser and returns `list[LabSample]` without writing to a GDB.

- [ ] **Step 2: Add `extract_sample_roster` to `edd_importer.py`**

Add to `autogis/core/envmon/edd_importer.py`:

```python
def extract_sample_roster(
    edd_path: Path,
    profile,          # EddProfile or ParserProfile — duck-typed
    site_id: str,
) -> list:
    """Return list[LabSample] from an EDD without importing to GDB."""
    from .reconcile_survey123_lab import LabSample
    from ..common.qa import QACollector
    qa = QACollector()
    records = import_edd(edd_path, profile, site_id, batch_id="", qa=qa)
    seen: dict[str, LabSample] = {}
    for r in records:
        key = r.get("SampleID", "")
        if key not in seen:
            seen[key] = LabSample(
                sample_id=key,
                location_id=r.get("LocationID", ""),
                sample_date=str(r.get("SampleDate", "")),
                matrix=r.get("Matrix", ""),
                analyte_count=0,
            )
        seen[key].analyte_count += 1
    return list(seen.values())
```

- [ ] **Step 3: Help test + commit**

```python
def test_reconcile_survey123_lab_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "reconcile-survey123-lab" in result.output
```

```bash
git add autogis/core/envmon/reconcile_survey123_lab.py \
        autogis/core/envmon/edd_importer.py \
        autogis/adapters/cli.py \
        tests/envmon/test_reconcile_survey123_lab.py
git commit -m "feat(cli): add reconcile-survey123-lab command; edd_importer.extract_sample_roster"
```
