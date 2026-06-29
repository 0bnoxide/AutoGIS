# BatchImportEnvironmentalWorkbooks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Add a `run_batch_import` function to a new `batch_import.py` module that globs a directory of Excel workbooks and calls `import_to_gdb.run_import` on each, collecting per-file outcomes and aggregate QA, then wire it to `autogis envmon batch-import-gdb` (LOCAL, arcpy required for GDB writes).

[No spec file reference needed — this plan is self-contained.]

**Architecture:**
- New: `autogis/core/envmon/batch_import.py`
- Modify: `autogis/adapters/cli.py` — add `batch-import-gdb` command (LOCAL)
- Modify: `autogis/runtime/capabilities.py` — register `"batch-import-gdb": Runtime.LOCAL`
- New: `tests/envmon/test_batch_import.py`

## Global Constraints

- `batch_import.py` must remain importable without arcpy; arcpy is only reached transitively via `import_to_gdb.run_import`, which is called inside function bodies.
- All tests are arcpy-free: use `dry_run=True` for structural tests; monkeypatch `autogis.core.envmon.import_to_gdb.run_import` for error/stop-on-error paths.
- The CLI guard `_guard("batch-import-gdb")` must be the **first** statement in the command body, before any core imports; `"batch-import-gdb"` must already be in `capabilities.TOOLS` or `_guard` raises `KeyError`.
- `QACollector` / `QARecord` from `autogis.core.common.qa`; severity constants `SEV_INFO`, `SEV_WARNING`, `SEV_ERROR`.
- Every `per_file` entry is a `dict` with exactly three keys: `"filename"` (str, basename only), `"status"` (one of `"ok"`, `"failed"`, `"dry_run"`, `"skipped"`), `"error_msg"` (str, empty on success).
- `BatchImportResult.qa` is the single aggregate `QACollector` covering all files in the run.
- `stop_on_error=True`: after the first file that raises an exception **or** returns a `BLOCKED_BY_QA` qa_status, all remaining files get `"skipped"` status and are not attempted.
- `analyte_dict_path` and `screening_levels_path` are optional in `BatchImportConfig` because `run_import` requires non-None `Path` arguments for both; when `None`, the implementation creates a temporary empty-YAML sentinel file (`suffix=".yaml"`, content `b"{}\n"`) and cleans it up after the run. `yaml.safe_load("{}\n")` → `{}` satisfies both `load_analyte_dictionary` (iterates over `{}.items()` — no-op) and `load_screening_levels` (returns `{}`) without errors.
- `BatchImportConfig` exposes four fields beyond the user-specified six (`workbook_dir`, `gdb_path`, `profile_path`, `site_config_path`, `glob_pattern`, `stop_on_error`). The extras are intentional extensions required to adapt to `run_import`'s signature: `mode` (default `"append"` — the correct batch default; intentionally NOT exposed on the CLI since batch always appends), `analyte_dict_path`, `screening_levels_path` (both `Optional[Path]`, default `None`), and `qa_output_dir` (default `None`, auto-resolved to `workbook_dir / "qa_reports"`). These are additive; the specified six are present with the specified defaults.

---

### Task 1: Core `batch_import.py`

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_batch_import.py`:

```python
"""Arcpy-free tests for batch_import (Tool 2.2 — BatchImportEnvironmentalWorkbooks)."""
from __future__ import annotations

from pathlib import Path
import pytest

from autogis.core.common.qa import QACollector, SEV_ERROR, SEV_INFO, SEV_WARNING
from autogis.core.envmon.batch_import import (
    BatchImportConfig,
    BatchImportResult,
    run_batch_import,
)


def _make_config(tmp_path, *, workbook_dir=None, pattern="*.xlsx", stop_on_error=False):
    """Return a minimal BatchImportConfig pointing at tmp_path."""
    d = workbook_dir or tmp_path / "workbooks"
    d.mkdir(exist_ok=True)
    return BatchImportConfig(
        workbook_dir=d,
        gdb_path=tmp_path / "test.gdb",
        profile_path=tmp_path / "profile.yaml",
        site_config_path=tmp_path / "site.yaml",
        glob_pattern=pattern,
        stop_on_error=stop_on_error,
    )


# ─── empty directory ─────────────────────────────────────────────────────────

def test_empty_dir_zero_attempted(tmp_path):
    """Empty workbook_dir → all counters zero, per_file empty."""
    result = run_batch_import(_make_config(tmp_path), dry_run=True)
    assert result.attempted == 0
    assert result.succeeded == 0
    assert result.failed == 0
    assert result.skipped == 0
    assert result.per_file == []


# ─── dry_run ─────────────────────────────────────────────────────────────────

def test_dry_run_three_files_attempted(tmp_path):
    """dry_run=True with 3 .xlsx files → attempted=3, succeeded/failed/skipped=0."""
    d = tmp_path / "workbooks"
    d.mkdir()
    for name in ["alpha.xlsx", "beta.xlsx", "gamma.xlsx"]:
        (d / name).write_bytes(b"")
    result = run_batch_import(_make_config(tmp_path, workbook_dir=d), dry_run=True)
    assert result.attempted == 3
    assert result.succeeded == 0
    assert result.failed == 0
    assert result.skipped == 0
    assert len(result.per_file) == 3


def test_dry_run_status_is_dry_run(tmp_path):
    """Every per_file entry in dry_run mode has status='dry_run'."""
    d = tmp_path / "workbooks"
    d.mkdir()
    (d / "wb.xlsx").write_bytes(b"")
    result = run_batch_import(_make_config(tmp_path, workbook_dir=d), dry_run=True)
    assert all(e["status"] == "dry_run" for e in result.per_file)


def test_dry_run_filenames_match(tmp_path):
    """per_file filenames are basenames matching files on disk."""
    d = tmp_path / "workbooks"
    d.mkdir()
    names = {"a.xlsx", "b.xlsx"}
    for n in names:
        (d / n).write_bytes(b"")
    result = run_batch_import(_make_config(tmp_path, workbook_dir=d), dry_run=True)
    assert {e["filename"] for e in result.per_file} == names


# ─── per_file structure ───────────────────────────────────────────────────────

def test_per_file_entry_has_required_keys(tmp_path):
    """Every per_file dict exposes 'filename', 'status', 'error_msg'."""
    d = tmp_path / "workbooks"
    d.mkdir()
    (d / "wb.xlsx").write_bytes(b"")
    result = run_batch_import(_make_config(tmp_path, workbook_dir=d), dry_run=True)
    entry = result.per_file[0]
    assert "filename" in entry
    assert "status" in entry
    assert "error_msg" in entry


def test_per_file_error_msg_empty_on_dry_run(tmp_path):
    """error_msg is '' (not None) in dry_run mode."""
    d = tmp_path / "workbooks"
    d.mkdir()
    (d / "ok.xlsx").write_bytes(b"")
    result = run_batch_import(_make_config(tmp_path, workbook_dir=d), dry_run=True)
    assert result.per_file[0]["error_msg"] == ""


# ─── stop_on_error ────────────────────────────────────────────────────────────

def _patch_for_live_run(monkeypatch, *, run_import_side_effect):
    """Patch ParserProfile, SiteConfig, and import_to_gdb.run_import."""
    from autogis.core.common import config as _cfg_mod

    class _FakeProfile:
        profile_id = "test"
        sheets = ["Sheet1"]

    class _FakeSite:
        site_id = "H281"
        site_name = "Test Site"

    monkeypatch.setattr(
        _cfg_mod,
        "ParserProfile",
        type("P", (), {"load": staticmethod(lambda p: _FakeProfile())}),
    )
    monkeypatch.setattr(
        _cfg_mod,
        "SiteConfig",
        type("S", (), {"load": staticmethod(lambda p: _FakeSite())}),
    )

    import autogis.core.envmon.import_to_gdb as _igdb
    monkeypatch.setattr(_igdb, "run_import", run_import_side_effect)


def test_stop_on_error_skips_remaining(tmp_path, monkeypatch):
    """stop_on_error=True: first failure stops loop; remaining files are 'skipped'."""
    d = tmp_path / "workbooks"
    d.mkdir()
    for name in ["a.xlsx", "b.xlsx", "c.xlsx"]:
        (d / name).write_bytes(b"")

    def _fail(**kw):
        raise RuntimeError("arcpy gone")

    _patch_for_live_run(monkeypatch, run_import_side_effect=_fail)

    config = _make_config(tmp_path, workbook_dir=d, stop_on_error=True)
    result = run_batch_import(config, dry_run=False)

    assert result.attempted == 1
    assert result.failed == 1
    assert result.skipped == 2
    statuses = [e["status"] for e in result.per_file]
    assert statuses.count("failed") == 1
    assert statuses.count("skipped") == 2


def test_stop_on_error_false_continues(tmp_path, monkeypatch):
    """stop_on_error=False (default): all files attempted even if all fail."""
    d = tmp_path / "workbooks"
    d.mkdir()
    for name in ["a.xlsx", "b.xlsx", "c.xlsx"]:
        (d / name).write_bytes(b"")

    def _fail(**kw):
        raise RuntimeError("fail")

    _patch_for_live_run(monkeypatch, run_import_side_effect=_fail)

    config = _make_config(tmp_path, workbook_dir=d, stop_on_error=False)
    result = run_batch_import(config, dry_run=False)

    assert result.attempted == 3
    assert result.failed == 3
    assert result.skipped == 0


def test_stop_on_error_error_msg_captured(tmp_path, monkeypatch):
    """The exception message appears in per_file[*].error_msg for failed entries."""
    d = tmp_path / "workbooks"
    d.mkdir()
    (d / "bad.xlsx").write_bytes(b"")

    def _fail(**kw):
        raise ValueError("bad workbook structure")

    _patch_for_live_run(monkeypatch, run_import_side_effect=_fail)

    config = _make_config(tmp_path, workbook_dir=d)
    result = run_batch_import(config, dry_run=False)

    assert result.per_file[0]["status"] == "failed"
    assert "bad workbook structure" in result.per_file[0]["error_msg"]


# ─── result dataclass ─────────────────────────────────────────────────────────

def test_result_dataclass_fields():
    """BatchImportResult can be constructed directly and fields are accessible."""
    qa = QACollector()
    r = BatchImportResult(
        attempted=3,
        succeeded=2,
        failed=1,
        skipped=0,
        qa=qa,
        per_file=[{"filename": "a.xlsx", "status": "ok", "error_msg": ""}],
    )
    assert r.attempted == 3
    assert r.succeeded == 2
    assert r.failed == 1
    assert r.skipped == 0
    assert isinstance(r.qa, QACollector)
    assert len(r.per_file) == 1


def test_result_qa_is_collector(tmp_path):
    """BatchImportResult.qa is always a QACollector instance."""
    result = run_batch_import(_make_config(tmp_path), dry_run=True)
    assert isinstance(result.qa, QACollector)


def test_qa_info_emitted_for_dry_run(tmp_path):
    """QA INFO records are emitted for each file in dry_run mode."""
    d = tmp_path / "workbooks"
    d.mkdir()
    for name in ["a.xlsx", "b.xlsx"]:
        (d / name).write_bytes(b"")
    result = run_batch_import(_make_config(tmp_path, workbook_dir=d), dry_run=True)
    info_cats = [r.category for r in result.qa.records if r.severity == "INFO"]
    assert "batch_dry_run" in info_cats
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_batch_import.py -q
```

Expected: `ImportError` — `autogis.core.envmon.batch_import` does not exist yet.

- [ ] **Step 3: Create `autogis/core/envmon/batch_import.py`**

```python
"""Batch workbook-to-GDB import orchestration (Tool 2.2).

Arcpy-free at module level: arcpy is only reached via
``import_to_gdb.run_import``, which is called inside function bodies and
never executed in ``dry_run`` mode.
"""
from __future__ import annotations

import dataclasses
import tempfile
from pathlib import Path
from typing import List, Optional

from ..common.logging import get_logger
from ..common.qa import QACollector, SEV_ERROR, SEV_INFO, SEV_WARNING

LOG = get_logger(__name__)

# Minimal YAML that load_analyte_dictionary / load_screening_levels parse as {}
_EMPTY_YAML: bytes = b"{}\n"


@dataclasses.dataclass
class BatchImportConfig:
    """All settings for a batch workbook-to-GDB import run."""
    workbook_dir: Path
    gdb_path: Path
    profile_path: Path
    site_config_path: Path
    glob_pattern: str = "*.xlsx"
    stop_on_error: bool = False
    mode: str = "append"
    analyte_dict_path: Optional[Path] = None
    screening_levels_path: Optional[Path] = None
    qa_output_dir: Optional[Path] = None


@dataclasses.dataclass
class BatchImportResult:
    """Aggregate result of a batch import run."""
    attempted: int   # files actually attempted (not skipped)
    succeeded: int   # files that imported without exception and passed QA
    failed: int      # files that raised or returned BLOCKED_BY_QA
    skipped: int     # files not attempted due to stop_on_error
    qa: QACollector  # aggregate collector across all files
    per_file: List[dict]  # one dict per matched file: filename/status/error_msg


def run_batch_import(
    config: BatchImportConfig,
    *,
    dry_run: bool = False,
) -> BatchImportResult:
    """Glob workbooks in *config.workbook_dir* and import each to the GDB.

    Parameters
    ----------
    config:
        Paths and behaviour settings for the run.
    dry_run:
        When ``True``, list matched workbooks and emit QA INFO records without
        writing to the GDB.  Safe to call without arcpy.

    Returns
    -------
    :class:`BatchImportResult` with per-file outcomes and an aggregate
    :class:`QACollector`.
    """
    workbook_dir = Path(config.workbook_dir)
    workbooks = sorted(workbook_dir.glob(config.glob_pattern))
    qa = QACollector()
    per_file: List[dict] = []

    if not workbooks:
        qa.add(SEV_INFO, "batch_no_files",
               f"No files matching {config.glob_pattern!r} found in {workbook_dir}.")
        return BatchImportResult(
            attempted=0, succeeded=0, failed=0, skipped=0,
            qa=qa, per_file=per_file,
        )

    # ── dry-run path (arcpy never touched) ───────────────────────────────────
    if dry_run:
        for wb in workbooks:
            qa.add(SEV_INFO, "batch_dry_run",
                   f"Would import: {wb.name}", source_workbook=str(wb))
            per_file.append({"filename": wb.name, "status": "dry_run", "error_msg": ""})
        return BatchImportResult(
            attempted=len(workbooks), succeeded=0, failed=0, skipped=0,
            qa=qa, per_file=per_file,
        )

    # ── live import path (arcpy reached via run_import) ──────────────────────
    # Lazy imports so the module stays importable without arcpy.
    from ..common.config import ParserProfile, SiteConfig  # noqa: PLC0415

    profile = ParserProfile.load(Path(config.profile_path))
    site_config = SiteConfig.load(Path(config.site_config_path))
    qa_out = (
        Path(config.qa_output_dir)
        if config.qa_output_dir
        else Path(config.workbook_dir) / "qa_reports"
    )

    attempted = succeeded = failed = skipped = 0
    stopped = False

    # run_import requires non-None Paths for analyte_dict and screening_levels.
    # When omitted, write a temporary empty-YAML sentinel and remove it after
    # the loop.
    _tmp_files: List[Path] = []
    analyte_dict_path = config.analyte_dict_path
    screening_levels_path = config.screening_levels_path
    if analyte_dict_path is None:
        tf = tempfile.NamedTemporaryFile(suffix=".yaml", delete=False)
        tf.write(_EMPTY_YAML)
        tf.flush()
        tf.close()
        analyte_dict_path = Path(tf.name)
        _tmp_files.append(analyte_dict_path)
    if screening_levels_path is None:
        tf = tempfile.NamedTemporaryFile(suffix=".yaml", delete=False)
        tf.write(_EMPTY_YAML)
        tf.flush()
        tf.close()
        screening_levels_path = Path(tf.name)
        _tmp_files.append(screening_levels_path)

    try:
        for wb in workbooks:
            if stopped:
                per_file.append({"filename": wb.name, "status": "skipped", "error_msg": ""})
                skipped += 1
                continue

            attempted += 1
            try:
                from .import_to_gdb import run_import  # noqa: PLC0415

                summary = run_import(
                    workbook=wb,
                    gdb=Path(config.gdb_path),
                    site_config=site_config,
                    profile=profile,
                    analyte_dictionary_path=analyte_dict_path,
                    screening_levels_path=screening_levels_path,
                    qa_output_dir=qa_out / wb.stem,
                    mode=config.mode,
                )
                qa_status: str = summary.get("qa_status", "PASS")
                if qa_status == "FAIL" or "BLOCKED" in qa_status:
                    failed += 1
                    err = (
                        f"Blocked by QA ({qa_status}): "
                        f"{summary.get('qa_counts', '')}"
                    )
                    per_file.append({"filename": wb.name, "status": "failed",
                                     "error_msg": err})
                    qa.add(SEV_WARNING, "batch_workbook_blocked",
                           f"{wb.name}: {err}", source_workbook=str(wb))
                    if config.stop_on_error:
                        stopped = True
                else:
                    succeeded += 1
                    per_file.append({"filename": wb.name, "status": "ok",
                                     "error_msg": ""})
                    qa.add(SEV_INFO, "batch_workbook_ok",
                           f"{wb.name}: imported successfully.",
                           source_workbook=str(wb))
            except Exception as exc:
                failed += 1
                err_msg = str(exc)
                per_file.append({"filename": wb.name, "status": "failed",
                                 "error_msg": err_msg})
                qa.add(SEV_ERROR, "batch_workbook_error",
                       f"{wb.name}: {err_msg}", source_workbook=str(wb))
                LOG.error("batch_import: %s failed: %s", wb.name, exc)
                if config.stop_on_error:
                    stopped = True
    finally:
        for p in _tmp_files:
            try:
                p.unlink()
            except OSError:
                pass

    qa.add(SEV_INFO, "batch_import_complete",
           f"Batch complete: {succeeded} ok, {failed} failed, {skipped} skipped "
           f"(of {len(workbooks)} total).")
    return BatchImportResult(
        attempted=attempted, succeeded=succeeded, failed=failed, skipped=skipped,
        qa=qa, per_file=per_file,
    )
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_batch_import.py -q
```

Expected: all tests pass; zero arcpy imports occur.

- [ ] **Step 5: Full suite + commit**

```
python -m pytest -q
git add autogis/core/envmon/batch_import.py tests/envmon/test_batch_import.py
git commit -m "feat(envmon): batch_import — BatchImportConfig/Result + run_batch_import core (arcpy-free, tool 2.2)"
```

---

### Task 2: CLI command

- [ ] **Step 1: Register `batch-import-gdb` in `capabilities.py`**

In `autogis/runtime/capabilities.py`, add to the `TOOLS` dict (keep LOCAL entries together):

```python
"batch-import-gdb": Runtime.LOCAL,   # tool 2.2
```

This must land **before** Task 2 Step 2 so `_guard("batch-import-gdb")` does not raise `KeyError`.

- [ ] **Step 2: Add to `cli.py`**

Insert the following command in `cli.py` inside the LOCAL tools section (after `import-gdb`, before `build-event`):

```python
@envmon.command("batch-import-gdb")
@click.option("--workbook-dir", required=True, type=click.Path(exists=True),
              help="Directory containing Excel workbooks to import.")
@click.option("--gdb", "gdb_path", required=True, type=click.Path(),
              help="Target file geodatabase (.gdb).")
@click.option("--profile", "profile_path", required=True,
              type=click.Path(exists=True),
              help="Parser profile YAML shared by all workbooks.")
@click.option("--site-config", "site_config_path", required=True,
              type=click.Path(exists=True),
              help="Site configuration YAML.")
@click.option("--pattern", default="*.xlsx", show_default=True,
              help="Glob pattern for workbooks inside --workbook-dir.")
@click.option("--dry-run", is_flag=True, default=False,
              help="List matched workbooks without writing to the GDB.")
@click.option("--stop-on-error", is_flag=True, default=False,
              help="Abort after the first failed workbook.")
@click.option("--report", default=None, type=click.Path(),
              help="Write aggregate QA report to PATH (.md/.json/.csv).")
def batch_import_gdb_cmd(workbook_dir, gdb_path, profile_path, site_config_path,
                          pattern, dry_run, stop_on_error, report):
    """Tool 2.2: batch import a directory of workbooks into the GDB (LOCAL)."""
    _guard("batch-import-gdb")
    from autogis.core.envmon.batch_import import BatchImportConfig, run_batch_import

    config = BatchImportConfig(
        workbook_dir=Path(workbook_dir),
        gdb_path=Path(gdb_path),
        profile_path=Path(profile_path),
        site_config_path=Path(site_config_path),
        glob_pattern=pattern,
        stop_on_error=stop_on_error,
    )
    result = run_batch_import(config, dry_run=dry_run)

    if dry_run:
        click.echo(f"Dry run — {result.attempted} workbook(s) matched:")
        for entry in result.per_file:
            click.echo(f"  {entry['filename']}")
    else:
        click.echo(
            f"Batch complete: {result.succeeded} ok, {result.failed} failed, "
            f"{result.skipped} skipped "
            f"(of {result.attempted + result.skipped} total)."
        )
        for entry in result.per_file:
            if entry["status"] != "ok":
                suffix = f": {entry['error_msg']}" if entry["error_msg"] else ""
                click.echo(
                    f"  [{entry['status'].upper()}] {entry['filename']}{suffix}"
                )

    _render_qa(result.qa, report, "error")
```

- [ ] **Step 3: Help test + commit**

Append to `tests/envmon/test_batch_import.py`:

```python
def test_batch_import_gdb_in_help():
    """'batch-import-gdb' appears in `autogis envmon --help`."""
    from click.testing import CliRunner
    from autogis.adapters.cli import autogis
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "batch-import-gdb" in result.output
```

Then verify and commit:

```
python -m pytest tests/envmon/test_batch_import.py -q
python -m pytest -q
git add autogis/adapters/cli.py autogis/runtime/capabilities.py tests/envmon/test_batch_import.py
git commit -m "feat(envmon): batch-import-gdb CLI command + capabilities entry (LOCAL, tool 2.2)"
```
