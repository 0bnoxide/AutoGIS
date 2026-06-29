# MergeEventResults Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Implement `MergeEventResults` — concatenate multiple event result CSVs, add EventLabel column, deduplicate on canonical key, write merged output + SHA-256 manifest.
See spec: `docs/superpowers/specs/2026-06-28-merge-event-results-design.md`.

**Architecture:**
- New: `autogis/core/envmon/event_results_merger.py`
- Modify: `autogis/adapters/cli.py` — add `merge-event-results` command (headless)
- New: `tests/envmon/test_event_results_merger.py`

## Global Constraints

- Arcpy-free. stdlib only: `csv`, `hashlib`, `re`, `uuid`.
- Dedup key: `(SampleID, AnalyteName, ReportedUnits)` — first occurrence wins.
- Run tests with `python -m pytest -q`.

---

### Task 1: Core `event_results_merger.py`

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_event_results_merger.py`:

```python
from pathlib import Path
import csv
import pytest
from autogis.core.envmon.event_results_merger import (
    SourceFile, MergeResult, infer_event_label,
    merge_event_results, write_merge_manifest,
)


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow(r)


_ROW_A = {"SampleID": "S1", "AnalyteName": "Benzene",
          "ReportedUnits": "ug/L", "ResultValue": "5.0",
          "LocationID": "MW-01", "SampleDate": "2026-01-15"}
_ROW_B = {"SampleID": "S2", "AnalyteName": "Benzene",
          "ReportedUnits": "ug/L", "ResultValue": "12.0",
          "LocationID": "MW-01", "SampleDate": "2026-06-15"}
_ROW_DUP = dict(_ROW_A)  # same SampleID, AnalyteName, Units


def test_merge_two_files(tmp_path):
    f1 = tmp_path / "Env_Results_20260115.csv"
    f2 = tmp_path / "Env_Results_20260615.csv"
    _write_csv(f1, [_ROW_A])
    _write_csv(f2, [_ROW_B])
    out = tmp_path / "merged.csv"
    manifest = tmp_path / "manifest.csv"
    result = merge_event_results([f1, f2], out, manifest_path=manifest)
    assert result.total_rows == 2
    assert result.duplicate_rows_dropped == 0


def test_deduplication(tmp_path):
    f1 = tmp_path / "Env_Results_20260115.csv"
    f2 = tmp_path / "Env_Results_20260615.csv"
    _write_csv(f1, [_ROW_A])
    _write_csv(f2, [_ROW_DUP])  # same key as f1
    out = tmp_path / "merged.csv"
    result = merge_event_results([f1, f2], out)
    assert result.total_rows == 1
    assert result.duplicate_rows_dropped == 1


def test_event_label_added(tmp_path):
    f1 = tmp_path / "Env_Results_20260115.csv"
    _write_csv(f1, [_ROW_A])
    out = tmp_path / "merged.csv"
    merge_event_results([f1], out, event_labels=["Q1-2026"])
    with out.open() as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0].get("EventLabel") == "Q1-2026"


def test_infer_event_label_date():
    p = Path("Env_Results_20260615_GW.csv")
    assert infer_event_label(p) == "20260615"


def test_infer_event_label_fallback():
    p = Path("custom_export.csv")
    assert infer_event_label(p) == "custom_export"


def test_manifest_written(tmp_path):
    f1 = tmp_path / "Env_Results_20260115.csv"
    _write_csv(f1, [_ROW_A])
    out = tmp_path / "merged.csv"
    manifest = tmp_path / "manifest.csv"
    merge_event_results([f1], out, manifest_path=manifest)
    assert manifest.exists()
    with manifest.open() as fh:
        rows = list(csv.DictReader(fh))
    assert "sha256" in rows[0]


def test_missing_source_error(tmp_path):
    f1 = tmp_path / "nonexistent.csv"
    out = tmp_path / "merged.csv"
    result = merge_event_results([f1], out)
    assert any(r.severity == "ERROR" for r in result.qa.records)


def test_single_file_valid(tmp_path):
    f1 = tmp_path / "Env_Results_20260615.csv"
    _write_csv(f1, [_ROW_A])
    out = tmp_path / "merged.csv"
    result = merge_event_results([f1], out)
    assert result.total_rows == 1
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_event_results_merger.py -v
```

- [ ] **Step 3: Create `autogis/core/envmon/event_results_merger.py`**

```python
"""event_results_merger.py — multi-event CSV concatenator with dedup + manifest."""
from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..common.qa import QACollector, QARecord, SEV_ERROR, SEV_INFO, SEV_WARNING

_DEFAULT_DEDUP_KEY = ("SampleID", "AnalyteName", "ReportedUnits")


@dataclass
class SourceFile:
    path: Path
    event_label: str
    event_date: str
    sha256: str
    row_count: int


@dataclass
class MergeResult:
    merged_path: Path
    manifest_path: Optional[Path]
    source_files: list
    total_rows: int
    duplicate_rows_dropped: int
    qa: QACollector


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def infer_event_label(path: Path, pattern: str = r"(\d{8})") -> str:
    m = re.search(pattern, path.stem)
    if m:
        return m.group(1)
    return path.stem


def merge_event_results(
    source_paths: list,
    out_path: Path,
    *,
    event_labels: Optional[list] = None,
    dedup_key: tuple = _DEFAULT_DEDUP_KEY,
    add_source_column: bool = True,
    manifest_path: Optional[Path] = None,
    qa: Optional[QACollector] = None,
) -> MergeResult:
    if qa is None:
        qa = QACollector()

    all_rows: list[dict] = []
    source_files: list[SourceFile] = []

    for idx, src in enumerate(source_paths):
        src = Path(src)
        label = (event_labels[idx] if event_labels and idx < len(event_labels)
                 else infer_event_label(src))
        if not src.exists():
            qa.add(QARecord(SEV_ERROR, "missing_source",
                            f"Source file not found: {src}"))
            source_files.append(SourceFile(path=src, event_label=label,
                                           event_date="", sha256="", row_count=0))
            continue
        sha = _sha256_file(src)
        with src.open(newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        if add_source_column:
            for r in rows:
                r["EventLabel"] = label
        all_rows.extend(rows)
        source_files.append(SourceFile(
            path=src, event_label=label, event_date="",
            sha256=sha, row_count=len(rows),
        ))

    # Dedup
    seen_keys: set[tuple] = set()
    deduped: list[dict] = []
    dropped = 0
    for r in all_rows:
        key = tuple(r.get(k, "") for k in dedup_key)
        if key in seen_keys:
            dropped += 1
        else:
            seen_keys.add(key)
            deduped.append(r)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if deduped:
        with out_path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(deduped[0].keys()))
            w.writeheader()
            for r in deduped:
                w.writerow(r)
    else:
        out_path.write_text("")

    if manifest_path:
        write_merge_manifest(source_files, Path(manifest_path))

    qa.add(QARecord(SEV_INFO, "merge_complete",
                    f"{len(source_files)} sources, {len(deduped)} rows, "
                    f"{dropped} duplicates dropped → {out_path}"))

    return MergeResult(
        merged_path=out_path,
        manifest_path=Path(manifest_path) if manifest_path else None,
        source_files=source_files,
        total_rows=len(deduped),
        duplicate_rows_dropped=dropped,
        qa=qa,
    )


def write_merge_manifest(source_files: list, manifest_path: Path) -> None:
    fields = ["source_file", "event_label", "event_date", "sha256", "row_count"]
    with Path(manifest_path).open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for sf in source_files:
            w.writerow({
                "source_file": str(sf.path),
                "event_label": sf.event_label,
                "event_date": sf.event_date,
                "sha256": sf.sha256,
                "row_count": sf.row_count,
            })
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_event_results_merger.py -v
```

Expected: all 9 PASS.

- [ ] **Step 5: Full suite + commit**

```bash
git add autogis/core/envmon/event_results_merger.py \
        tests/envmon/test_event_results_merger.py
git commit -m "feat(envmon): event_results_merger — multi-event CSV merge with dedup + manifest"
```

---

### Task 2: CLI command

- [ ] **Step 1: Add to `cli.py`**

```python
@envmon.command("merge-event-results")
@click.option("--results", "result_paths", multiple=True, type=click.Path(exists=True),
              help="Result CSV file(s). Repeatable.")
@click.option("--results-dir", default=None, type=click.Path(exists=True),
              help="Directory to scan for result CSVs.")
@click.option("--event-labels", default=None,
              help="Comma-separated event labels (parallel to --results).")
@click.option("--out", required=True, type=click.Path())
@click.option("--manifest", "manifest_path", default=None, type=click.Path())
@click.option("--no-dedup", is_flag=True, default=False)
@click.option("--report", default=None, type=click.Path())
def merge_event_results_cmd(result_paths, results_dir, event_labels,
                             out, manifest_path, no_dedup, report):
    """Merge multiple event result CSVs into one long-format file (headless)."""
    from autogis.core.envmon.event_results_merger import merge_event_results

    paths = [Path(p) for p in result_paths]
    if results_dir:
        paths += sorted(Path(results_dir).glob("*.csv"))
    labels = [l.strip() for l in event_labels.split(",")] if event_labels else None
    from autogis.core.envmon.event_results_merger import _DEFAULT_DEDUP_KEY
    result = merge_event_results(
        paths, Path(out),
        event_labels=labels,
        dedup_key=() if no_dedup else _DEFAULT_DEDUP_KEY,
        manifest_path=Path(manifest_path) if manifest_path else None,
    )
    click.echo(f"Sources: {len(result.source_files)}  Rows: {result.total_rows}  "
               f"Duplicates dropped: {result.duplicate_rows_dropped}  Output: {out}")
    _render_qa(result.qa, report, "warning")
```

- [ ] **Step 2: Help test + commit**

```python
def test_merge_event_results_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "merge-event-results" in result.output
```

```bash
git add autogis/adapters/cli.py tests/envmon/test_event_results_merger.py
git commit -m "feat(cli): add merge-event-results command"
```
