# BatchEDDImport (HYBRID) — Implementation Plan

> **SUPERSEDED (2026-07-03) — do not implement this plan.** The user folded
> BatchEDDImport into the already-shipped Tool 2.2 `batch-import-workbooks`
> instead of building a new tool: the existing command gained an alternate
> `--edd-dir`/`--profile`/`--site`/`--pattern` input mode
> (`manifest_rows_from_dir()` in `core/envmon/batch_workbook_importer.py`).
> No `batch_edd.py`, no `BatchImportSummary`, no `batch-import-edd` command.
> Resolution recorded in
> `docs/superpowers/specs/2026-07-03-planned-roadmap-batch-brief.md` §4 and
> ADR-0048. (This plan was also independently stale: its central reused
> function `run_edd_import_csv` never existed.)

**Goal:** Add `envmon batch-import-edd` CLI command that processes a directory of EDD
files (CSV/XLSX matching a pattern), running the headless EDD import on each and
aggregating results into a single summary. Enables bulk import of lab deliverables
without shell scripting. Each file is processed independently; failures are captured in
the summary rather than aborting the batch.

**Architecture:** New pure-core module `autogis/core/envmon/batch_edd.py` with
`BatchImportSummary` dataclass and `batch_import_edd(edd_dir, profile, site_id,
output_dir, *, qa, pattern) -> BatchImportSummary`. Depends on the headless CSV output
path of `edd_importer.py` (Plan 2026-06-28-fix-import-edd-headless). HYBRID runtime
(CSV output is headless; GDB append optional, needs arcpy).

**Tech stack:** Python 3.14, click, stdlib csv/dataclasses/pathlib, pytest.
Reuses: `LabEDDProfile` (`edd_profile.py`), `run_edd_import_csv` (`edd_importer.py`),
`QACollector` (`common/qa.py`), `_render_qa` (`cli.py`).

## Global constraints

- `core/` imports without arcpy. The batch function itself is arcpy-free.
- Command name exactly `batch-import-edd`. Register as `Runtime.HYBRID`.
- Processes files matching `pattern` glob (default `*.csv`); falls back to `*.xlsx` if
  no CSV files found.
- Per-file QA records are merged into the caller's `QACollector` with file name context.
- A failed file (any exception) emits `SEV_WARNING` and increments `failed` counter;
  does not abort remaining files.
- Summary printed to stdout: file count, success/fail, total samples, total results.

---

### Task 1: Core module `batch_edd.py` + unit tests

**Files:**
- Create: `autogis/core/envmon/batch_edd.py`
- Create: `tests/test_batch_edd.py`

**Complete code — `batch_edd.py`:**

```python
"""Batch EDD directory import (Tool 2.3b)."""
from __future__ import annotations
import csv
import dataclasses
from pathlib import Path
from typing import Optional
from ..common.qa import QACollector, SEV_INFO, SEV_WARNING


@dataclasses.dataclass
class BatchImportSummary:
    site_id: str
    total_files: int
    successful: int
    failed: int
    total_samples: int
    total_results: int
    errors: list


def batch_import_edd(
    edd_dir: Path,
    profile,
    site_id: str,
    output_dir: Path,
    *,
    qa: QACollector,
    analyte_dictionary: Optional[dict] = None,
    screening_levels: Optional[dict] = None,
    pattern: str = "*.csv",
) -> BatchImportSummary:
    """Process all EDD files in edd_dir; write per-file CSVs to output_dir."""
    from .edd_importer import run_edd_import_csv

    edd_dir = Path(edd_dir)
    files = sorted(edd_dir.glob(pattern))
    if not files:
        files = sorted(edd_dir.glob("*.xlsx"))

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    successful = 0
    failed = 0
    total_samples = 0
    total_results = 0
    errors: list = []

    for f in files:
        file_qa = QACollector()
        try:
            samples_csv, results_csv, batch_id = run_edd_import_csv(
                f, profile, site_id, output_dir,
                analyte_dictionary=analyte_dictionary or {},
                screening_levels=screening_levels or {},
                qa=file_qa)
            with open(samples_csv, newline="", encoding="utf-8") as fh:
                n_samp = sum(1 for _ in csv.DictReader(fh))
            with open(results_csv, newline="", encoding="utf-8") as fh:
                n_res = sum(1 for _ in csv.DictReader(fh))
            total_samples += n_samp
            total_results += n_res
            qa.extend(file_qa.records)
            successful += 1
        except Exception as exc:
            err_msg = f"{f.name}: {exc}"
            errors.append(err_msg)
            qa.add(SEV_WARNING, "batch_file_failed", err_msg)
            failed += 1

    qa.add(SEV_INFO, "batch_import_complete",
           f"batch_import_edd: {successful}/{len(files)} files OK, "
           f"{total_samples} samples, {total_results} results")
    return BatchImportSummary(
        site_id=site_id,
        total_files=len(files),
        successful=successful,
        failed=failed,
        total_samples=total_samples,
        total_results=total_results,
        errors=errors,
    )
```

**Complete code — `tests/test_batch_edd.py`:**

```python
"""Unit tests for batch_edd (Tool 2.3b)."""
import csv
from pathlib import Path
import pytest
from autogis.core.common.qa import QACollector
from autogis.core.envmon.batch_edd import batch_import_edd, BatchImportSummary


class _FakeProfile:
    """Minimal LabEDDProfile stub for testing."""
    lab_name = "TestLab"
    profile_id = "test"


def _write_dummy_edd(path):
    """Write a minimal CSV that run_edd_import_csv can parse."""
    path.write_text(
        "SampleID,AnalyteName,Result,Units,Method,ReportDate\n"
        "S1,Benzene,5.0,ug/L,EPA8260,2026-04-01\n",
        encoding="utf-8")


def test_empty_directory(tmp_path):
    qa = QACollector()
    result = batch_import_edd(
        edd_dir=tmp_path / "edd_in",
        profile=_FakeProfile(),
        site_id="H281",
        output_dir=tmp_path / "out",
        qa=qa)
    assert result.total_files == 0
    assert result.successful == 0
    assert result.failed == 0


def test_failed_file_captured(tmp_path, monkeypatch):
    """A file that raises an exception increments failed, not successful."""
    edd_dir = tmp_path / "edd"
    edd_dir.mkdir()
    bad = edd_dir / "bad.csv"
    bad.write_text("junk,data\n", encoding="utf-8")

    def _fail(*a, **kw):
        raise ValueError("parse error")

    from autogis.core.envmon import batch_edd
    monkeypatch.setattr(batch_edd, "_import_one", None, raising=False)

    import autogis.core.envmon.edd_importer as _edi
    monkeypatch.setattr(_edi, "run_edd_import_csv",
                        lambda *a, **kw: (_ for _ in ()).throw(ValueError("err")))

    qa = QACollector()
    result = batch_import_edd(
        edd_dir=edd_dir,
        profile=_FakeProfile(),
        site_id="H281",
        output_dir=tmp_path / "out",
        qa=qa)
    assert result.failed == 1
    assert result.successful == 0
    assert any(r.category == "batch_file_failed" for r in qa.records)


def test_summary_dataclass_fields():
    s = BatchImportSummary(
        site_id="S", total_files=2, successful=1, failed=1,
        total_samples=10, total_results=50, errors=["f: err"])
    assert s.total_files == 2
    assert s.errors == ["f: err"]
```

**Steps:**
- [ ] Write test file, verify ImportError.
- [ ] Implement `batch_edd.py`.
- [ ] Run unit tests, verify pass.

---

### Task 2: Wire CLI + register

**CLI command (insert before `_render_qa` in `cli.py`):**

```python
@envmon.command("batch-import-edd")
@click.option("--edd-dir", required=True, type=click.Path(exists=True),
              help="Directory containing EDD CSV/XLSX files.")
@click.option("--profile-path", required=True, type=click.Path(exists=True),
              help="Lab EDD profile YAML.")
@click.option("--site", "site_id", required=True)
@click.option("--output-dir", required=True, type=click.Path(),
              help="Directory for per-file output CSVs.")
@click.option("--pattern", default="*.csv", show_default=True,
              help="Glob pattern for input files (default: *.csv).")
@click.option("--analytes", default=None, type=click.Path(exists=True))
@click.option("--screening", default=None, type=click.Path(exists=True))
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error")
def batch_import_edd_cmd(edd_dir, profile_path, site_id, output_dir,
                          pattern, analytes, screening, report, fail_on):
    """Tool 2.3b: batch import EDD files from a directory (HYBRID)."""
    import yaml as _yaml
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.edd_profile import LabEDDProfile
    from autogis.core.envmon.batch_edd import batch_import_edd

    profile = LabEDDProfile.load(Path(profile_path))
    analyte_dict = (_yaml.safe_load(Path(analytes).read_text(encoding="utf-8"))
                    if analytes else {})
    screening_lvls = (_yaml.safe_load(Path(screening).read_text(encoding="utf-8"))
                      if screening else {})
    qa = QACollector()
    summary = batch_import_edd(
        Path(edd_dir), profile, site_id, Path(output_dir),
        qa=qa, analyte_dictionary=analyte_dict,
        screening_levels=screening_lvls, pattern=pattern)
    click.echo(
        f"Batch complete: {summary.successful}/{summary.total_files} files OK, "
        f"{summary.total_samples} samples, {summary.total_results} results, "
        f"{summary.failed} failed")
    for err in summary.errors:
        click.echo(f"  FAIL: {err}")
    _render_qa(qa, report, fail_on)
```

**`capabilities.py` entry:** `"batch-import-edd": Runtime.HYBRID`

**Steps:**
- [ ] Write failing CLI test in `tests/test_cli_batch_import_edd.py`.
- [ ] Add command, update capabilities.
- [ ] Run `python -m pytest -q`, verify all pass.
- [ ] Commit: `feat(envmon): batch-import-edd — bulk EDD directory import (HYBRID)`
