# FixImportEDDHeadless — Implementation Plan

**Goal:** Fix `import-edd` CLI command so it works headlessly for CSV input as ADR-016 specifies. Currently it calls `_guard("LOCAL")` unconditionally, but ADR-016 says the core import logic is arcpy-free — only the final GDB write needs arcpy. Split into two modes: `--output-csv PATH` (headless, writes CSV of imported records) and `--gdb PATH` (requires arcpy). This unlocks automated batch imports and CI testing without an ArcGIS Pro license.

**Architecture:** (1) Add `run_edd_import_csv()` function to `autogis/core/envmon/edd_importer.py` — pure Python, no arcpy. (2) Add `--output-csv` option to the `import-edd` CLI command and remove the unconditional `_guard("LOCAL")` from the headless path. (3) When `--output-csv` is given: call `run_edd_import_csv()` which writes SampleRecord and AnalyticalResultRecord CSVs. (4) When `--gdb` is given: guard then call the existing GDB write path. (5) Update `import-edd` in the TOOLS dict from its current incorrect value to `Runtime.HYBRID`.

**Tech stack:** Python 3.14, click, csv, dataclasses. Reuses: all of `autogis/core/envmon/edd_importer.py`, `QACollector` from `autogis/core/common/qa.py`.

## Global constraints
- `core/` and `adapters/` import without arcpy or arcgis present
- Use openpyxl for Excel (ADR-008) — edd_importer already does this
- `import-edd` runtime changes to `Runtime.HYBRID` in capabilities.py
- Run tests with: `python -m pytest -q`

---

### Task 1: Add `run_edd_import_csv()` to `autogis/core/envmon/edd_importer.py`

**Files:**
- Modify: `autogis/core/envmon/edd_importer.py`

**Complete function to add:**

```python
def run_edd_import_csv(
    edd_path: Path,
    profile: "LabEDDProfile",
    site_id: str,
    output_dir: Path,
    *,
    analyte_dictionary: dict = None,
    screening_levels: dict = None,
    event_date_override=None,
    qa: "QACollector" = None,
) -> tuple:
    """Headless path: parse EDD and write CSVs instead of GDB rows.

    Returns: (samples_csv_path, results_csv_path, batch_id)

    No arcpy dependency. All output written as plain CSV files using
    dataclasses.asdict() on SampleRecord and AnalyticalResultRecord.
    """
    import csv
    import dataclasses
    from datetime import date as _date
    from autogis.core.common.qa import QACollector as _QACollector

    if qa is None:
        qa = _QACollector()

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Parse the EDD using the existing parse function
    batch_id, sample_records, result_records = parse_edd(
        edd_path=edd_path,
        profile=profile,
        site_id=site_id,
        analyte_dictionary=analyte_dictionary or {},
        screening_levels=screening_levels or {},
        event_date_override=event_date_override,
        qa=qa,
    )

    # Write samples CSV
    samples_csv = output_dir / f"{batch_id}_samples.csv"
    if sample_records:
        fields = [f.name for f in dataclasses.fields(sample_records[0])]
        with open(samples_csv, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            for rec in sample_records:
                row = dataclasses.asdict(rec)
                # Serialize dates
                for k, v in row.items():
                    if hasattr(v, "isoformat"):
                        row[k] = v.isoformat()
                writer.writerow(row)
    else:
        samples_csv.write_text("", encoding="utf-8")

    # Write results CSV
    results_csv = output_dir / f"{batch_id}_results.csv"
    if result_records:
        fields = [f.name for f in dataclasses.fields(result_records[0])]
        with open(results_csv, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            for rec in result_records:
                row = dataclasses.asdict(rec)
                for k, v in row.items():
                    if hasattr(v, "isoformat"):
                        row[k] = v.isoformat()
                writer.writerow(row)
    else:
        results_csv.write_text("", encoding="utf-8")

    qa.add(
        SEV_INFO, "edd_import_csv_complete",
        f"run_edd_import_csv: batch={batch_id}, "
        f"{len(sample_records)} samples, {len(result_records)} results "
        f"-> {output_dir}",
    )
    return samples_csv, results_csv, batch_id
```

**Steps:**
- [ ] Read current `autogis/core/envmon/edd_importer.py` to understand `parse_edd` signature and imports already present
- [ ] Add `run_edd_import_csv()` at the end of the module (before any `if __name__ == "__main__"` block)
- [ ] Verify no arcpy import is introduced

---

### Task 2: Write `tests/test_edd_importer_headless.py`

**Files:**
- Create: `tests/test_edd_importer_headless.py`

**Complete code:**

```python
"""Tests for the headless CSV output path of edd_importer (ADR-016)."""
import csv
from pathlib import Path

import pytest

from autogis.core.common.qa import QACollector


def _make_minimal_edd_csv(path: Path, site_id: str = "TEST") -> None:
    """Write a minimal EDD CSV that the default profile can parse."""
    # Minimal required columns — adjust to match actual profile expectations
    path.write_text(
        "SampleID,LocationID,SampleDate,Matrix,AnalyteName,Result,Units,Qualifier\n"
        "S-001,MW-1,2026-04-15,GW,Benzene,5.0,ug/L,\n"
        "S-001,MW-1,2026-04-15,GW,Toluene,<0.5,ug/L,U\n",
        encoding="utf-8",
    )


def test_run_edd_import_csv_returns_paths(tmp_path):
    """run_edd_import_csv should return (samples_csv, results_csv, batch_id)."""
    from autogis.core.envmon.edd_importer import run_edd_import_csv

    edd = tmp_path / "test_edd.csv"
    _make_minimal_edd_csv(edd)
    qa = QACollector()

    result = run_edd_import_csv(
        edd_path=edd,
        profile=None,  # will use default profile
        site_id="TEST",
        output_dir=tmp_path / "output",
        qa=qa,
    )
    assert len(result) == 3
    samples_csv, results_csv, batch_id = result
    assert Path(samples_csv).exists()
    assert Path(results_csv).exists()
    assert isinstance(batch_id, str) and batch_id


def test_run_edd_import_csv_writes_results_rows(tmp_path):
    """Output results CSV should contain at least one data row."""
    from autogis.core.envmon.edd_importer import run_edd_import_csv

    edd = tmp_path / "test_edd.csv"
    _make_minimal_edd_csv(edd)
    qa = QACollector()

    samples_csv, results_csv, batch_id = run_edd_import_csv(
        edd_path=edd, profile=None, site_id="TEST",
        output_dir=tmp_path / "output", qa=qa,
    )
    with open(results_csv, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) >= 1


def test_run_edd_import_csv_no_arcpy(tmp_path):
    """Importing run_edd_import_csv must not require arcpy."""
    import sys
    assert "arcpy" not in sys.modules, "arcpy must not be imported in this environment"
    from autogis.core.envmon.edd_importer import run_edd_import_csv  # noqa: F401


def test_run_edd_import_csv_emits_qa_info(tmp_path):
    """QACollector should receive at least one INFO record."""
    from autogis.core.envmon.edd_importer import run_edd_import_csv

    edd = tmp_path / "test_edd.csv"
    _make_minimal_edd_csv(edd)
    qa = QACollector()

    run_edd_import_csv(
        edd_path=edd, profile=None, site_id="TEST",
        output_dir=tmp_path / "output", qa=qa,
    )
    categories = {r.category for r in qa.records}
    assert "edd_import_csv_complete" in categories
```

**Steps:**
- [ ] Write test file
- [ ] Run `python -m pytest tests/test_edd_importer_headless.py -q` — expect ImportError or AttributeError
- [ ] Implement `run_edd_import_csv()` as in Task 1
- [ ] Run tests again — expect pass

---

### Task 3: Update CLI command in `autogis/adapters/cli.py`

**Files:**
- Modify: `autogis/adapters/cli.py` (update `import-edd` command)

**Changes required:**
1. Add `--output-csv` option to the `import-edd` command
2. Remove `_guard("LOCAL")` from the code path taken when `--output-csv` is provided
3. When `--output-csv` given: call `run_edd_import_csv()` and report results
4. When `--gdb` given: call `_guard("LOCAL")` then existing GDB path

**Updated command signature:**

```python
@envmon.command("import-edd")
@click.option("--edd", "edd_path", required=True, type=click.Path(exists=True),
              help="Path to EDD file (CSV or XLSX).")
@click.option("--site", "site_id", required=True, help="Site ID.")
@click.option("--profile", default=None, help="Parser profile name.")
@click.option("--output-csv", "output_csv_dir", default=None, type=click.Path(),
              help="(CLOUD) Write imported records as CSVs to this directory.")
@click.option("--gdb", "gdb_path", default=None, type=click.Path(),
              help="(LOCAL) ArcGIS GDB path for direct GDB write (requires arcpy).")
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error")
def import_edd_cmd(edd_path, site_id, profile, output_csv_dir, gdb_path, report, fail_on):
    """Import a lab EDD file into analytical results (HYBRID)."""
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.edd_importer import load_profile

    if output_csv_dir is None and gdb_path is None:
        raise click.UsageError("Provide --output-csv (headless) or --gdb (LOCAL).")

    qa = QACollector()
    parsed_profile = load_profile(profile) if profile else None

    if output_csv_dir:
        # CLOUD / headless path — no arcpy guard
        from autogis.core.envmon.edd_importer import run_edd_import_csv
        samples_csv, results_csv, batch_id = run_edd_import_csv(
            edd_path=Path(edd_path),
            profile=parsed_profile,
            site_id=site_id,
            output_dir=Path(output_csv_dir),
            qa=qa,
        )
        click.echo(f"Batch: {batch_id}")
        click.echo(f"Samples: {samples_csv}")
        click.echo(f"Results: {results_csv}")
    else:
        # LOCAL path — requires arcpy
        _guard("LOCAL")
        # ... existing GDB write logic unchanged ...
        click.echo("GDB write path — invoke via ArcGIS Pro toolbox.")

    _render_qa(qa, report, fail_on)
```

**Steps:**
- [ ] Read current `import-edd` command implementation in `autogis/adapters/cli.py`
- [ ] Apply targeted edit to add `--output-csv` option and conditional guard
- [ ] Update `TOOLS` entry in `autogis/runtime/capabilities.py`: `"import-edd": Runtime.HYBRID`

---

### Task 4: Full test suite + commit

**Steps:**
- [ ] Run `python -m pytest -q` — expect all existing tests plus new headless tests pass
- [ ] Commit: `fix(envmon): import-edd — headless CSV output path (ADR-016)`

---

## Run commands

```bash
# TDD step 1: verify test file fails before implementation
python -m pytest tests/test_edd_importer_headless.py -q

# TDD step 2: after implementing run_edd_import_csv
python -m pytest tests/test_edd_importer_headless.py -q

# TDD step 3: full suite
python -m pytest -q
```
