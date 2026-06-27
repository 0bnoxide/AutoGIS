# ExportEventDatabaseSnapshot (Tool 9.2) — Implementation Plan

**Goal:** Add a headless `envmon export-snapshot` CLI command + core module that reads
a directory of existing CSV exports (or generates them from in-memory records) for a
given site/event and packages them into a single ZIP archive with a manifest. Provides
a portable, auditable snapshot of the envmon data state for archiving and hand-off.

**Architecture:** New pure-core module `autogis/core/envmon/export_snapshot.py` with
`build_snapshot(source_dir, *, site_id, event_label, output_zip, qa) -> Path`. The
command collects CSVs matching envmon table names from `source_dir`, writes a
`manifest.json` (file list, row counts, SHA-256 checksums, snapshot timestamp), and
bundles everything into a ZIP. No arcpy, no openpyxl.

**Tech stack:** Python 3.14, `click`, stdlib `csv`/`zipfile`/`hashlib`/`json`/
`datetime`, `pytest`. Reuses: `QACollector` (`common/qa.py`), `_render_qa` (`cli.py`).

## Global constraints

- `core/` and `adapters/` import without arcpy. Headless — no `_guard`.
- Command name exactly `export-snapshot`. Register as `Runtime.CLOUD`.
- SHA-256 checksums are computed per file before zipping; stored in `manifest.json`.
- The manifest includes: `snapshot_id` (UUID4), `site_id`, `event_label`,
  `created_at` (ISO), `tool_version` (from package `__version__` or `"dev"`),
  `files`: list of `{name, rows, sha256}`.
- `--include-pattern` glob filter on filenames (default `"*.csv"`).
- `--overwrite` flag: if the output ZIP exists, overwrite; else error.

---

### Task 1: Core module `export_snapshot.py` + unit tests

**Files:**
- Create: `autogis/core/envmon/export_snapshot.py`
- Create: `tests/test_export_snapshot.py`

**Complete code:**

```python
"""Package envmon CSVs into a portable ZIP snapshot (Tool 9.2)."""
from __future__ import annotations
import csv
import hashlib
import json
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from ..common.qa import QACollector, SEV_INFO, SEV_WARNING, SEV_ERROR


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _row_count(path: Path) -> int:
    with path.open(newline="", encoding="utf-8") as fh:
        return max(0, sum(1 for _ in csv.reader(fh)) - 1)  # exclude header


def build_snapshot(
    source_dir: Path,
    *,
    site_id: str,
    event_label: str,
    output_zip: Path,
    include_pattern: str = "*.csv",
    overwrite: bool = False,
    qa: QACollector,
) -> Path:
    """Bundle CSVs from source_dir into a ZIP snapshot with manifest."""
    source_dir = Path(source_dir)
    output_zip = Path(output_zip)
    if output_zip.exists() and not overwrite:
        qa.add(SEV_ERROR, "snapshot_exists",
               f"Output ZIP already exists: {output_zip}. "
               f"Use overwrite=True to replace.")
        return output_zip

    files = sorted(source_dir.glob(include_pattern))
    if not files:
        qa.add(SEV_WARNING, "no_files_found",
               f"No files matching {include_pattern!r} in {source_dir}")

    manifest_entries = []
    for f in files:
        sha = _sha256(f)
        rows = _row_count(f)
        manifest_entries.append({"name": f.name, "rows": rows, "sha256": sha})

    snapshot_id = str(uuid.uuid4())
    manifest = {
        "snapshot_id": snapshot_id,
        "site_id": site_id,
        "event_label": event_label,
        "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "tool_version": _tool_version(),
        "files": manifest_entries,
    }

    output_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, arcname=f.name)
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))

    qa.add(SEV_INFO, "snapshot_complete",
           f"Snapshot {snapshot_id} written to {output_zip} "
           f"({len(files)} file(s), {sum(e['rows'] for e in manifest_entries)} rows)")
    return output_zip


def _tool_version() -> str:
    try:
        from importlib.metadata import version
        return version("autogis")
    except Exception:
        return "dev"
```

**Test file `tests/test_export_snapshot.py`:**

```python
"""Unit tests for export_snapshot (Tool 9.2)."""
import csv
import json
import zipfile
from pathlib import Path

import pytest

from autogis.core.common.qa import QACollector
from autogis.core.envmon.export_snapshot import build_snapshot


def _make_csv(path, rows=3):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["id", "val"])
        for i in range(rows):
            w.writerow([i, i * 10])


def test_basic_snapshot(tmp_path):
    src = tmp_path / "src"
    _make_csv(src / "Env_AnalyticalResults.csv", rows=5)
    _make_csv(src / "Env_Samples.csv", rows=2)
    out = tmp_path / "snap.zip"
    qa = QACollector()
    result = build_snapshot(src, site_id="H281", event_label="2026Q2",
                             output_zip=out, qa=qa)
    assert result == out
    assert out.exists()
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
    assert "manifest.json" in names
    assert "Env_AnalyticalResults.csv" in names
    assert "Env_Samples.csv" in names


def test_manifest_content(tmp_path):
    src = tmp_path / "src"
    _make_csv(src / "results.csv", rows=3)
    out = tmp_path / "snap.zip"
    qa = QACollector()
    build_snapshot(src, site_id="H281", event_label="2026Q2", output_zip=out, qa=qa)
    with zipfile.ZipFile(out) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    assert manifest["site_id"] == "H281"
    assert manifest["event_label"] == "2026Q2"
    assert any(e["name"] == "results.csv" and e["rows"] == 3
               for e in manifest["files"])


def test_overwrite_false_errors(tmp_path):
    src = tmp_path / "src"
    _make_csv(src / "r.csv")
    out = tmp_path / "snap.zip"
    out.write_bytes(b"existing")
    qa = QACollector()
    build_snapshot(src, site_id="S", event_label="E", output_zip=out,
                   overwrite=False, qa=qa)
    assert any(r.category == "snapshot_exists" for r in qa.records)


def test_no_files_warns(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    out = tmp_path / "snap.zip"
    qa = QACollector()
    build_snapshot(src, site_id="S", event_label="E", output_zip=out, qa=qa)
    assert any(r.category == "no_files_found" for r in qa.records)
```

**Steps:**
- [ ] Write test file, verify ImportError.
- [ ] Implement `export_snapshot.py`.
- [ ] Run unit tests, verify pass.

---

### Task 2: Wire CLI + register

```python
@envmon.command("export-snapshot")
@click.option("--source-dir", required=True, type=click.Path(exists=True))
@click.option("--output", required=True, type=click.Path())
@click.option("--site-id", required=True)
@click.option("--event-label", required=True)
@click.option("--include-pattern", default="*.csv")
@click.option("--overwrite", is_flag=True, default=False)
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error")
def export_snapshot_cmd(...):
    """Tool 9.2: bundle envmon CSVs into a portable ZIP snapshot."""
    ...
```

`capabilities.py`: `"export-snapshot": Runtime.CLOUD`

**Steps:**
- [ ] Write failing CLI test, verify fail.
- [ ] Add command, update capabilities.
- [ ] Full suite, commit: `feat(envmon): export-snapshot — ZIP-archive event CSV bundle with manifest (Tool 9.2)`
