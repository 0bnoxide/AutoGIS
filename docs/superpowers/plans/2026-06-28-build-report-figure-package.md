# BuildReportFigurePackage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Implement `BuildReportFigurePackage` — assemble a standardized deliverable folder from a YAML spec, copying files into `figures/`, `data/`, `qa/` subfolders with SHA-256 manifest and README.
See spec: `docs/superpowers/specs/2026-06-28-build-report-figure-package-design.md`.

**Architecture:**
- New: `autogis/core/envmon/report_figure_package.py`
- Modify: `autogis/adapters/cli.py` — add `build-report-package` command (headless)
- New: `tests/envmon/test_report_figure_package.py`

## Global Constraints

- Arcpy-free. stdlib only: `shutil`, `hashlib`, `csv`, `yaml`.
- Files are copied (not moved). Missing source → WARNING, not error.
- Run tests with `python -m pytest -q`.

---

### Task 1: Core `report_figure_package.py`

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_report_figure_package.py`:

```python
from pathlib import Path
import csv
import pytest
from autogis.core.envmon.report_figure_package import (
    DeliverableFile, FigurePackageResult,
    load_deliverable_spec, assemble_figure_package,
    write_package_manifest, DELIVERABLE_ROLES,
)


def _make_spec_yaml(tmp_path: Path, files: list[dict]) -> Path:
    import yaml
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.dump({"files": files}), encoding="utf-8")
    return spec_path


def test_load_deliverable_spec(tmp_path):
    spec = _make_spec_yaml(tmp_path, [{"path": "fig.pdf", "role": "figure_pdf"}])
    entries = load_deliverable_spec(spec)
    assert len(entries) == 1
    assert entries[0]["role"] == "figure_pdf"


def test_copy_existing_file(tmp_path):
    src = tmp_path / "Fig-1A.pdf"
    src.write_bytes(b"PDF content")
    spec = _make_spec_yaml(tmp_path, [{"path": str(src), "role": "figure_pdf"}])
    out_dir = tmp_path / "deliverable"
    result = assemble_figure_package(load_deliverable_spec(spec), out_dir)
    assert result.copied_count == 1
    assert (out_dir / "figures" / "Fig-1A.pdf").exists()


def test_figure_in_figures_subdir(tmp_path):
    src = tmp_path / "fig.pdf"
    src.write_bytes(b"x")
    spec = _make_spec_yaml(tmp_path, [{"path": str(src), "role": "figure_pdf"}])
    out_dir = tmp_path / "deliverable"
    assemble_figure_package(load_deliverable_spec(spec), out_dir)
    assert (out_dir / "figures").is_dir()


def test_data_csv_in_data_subdir(tmp_path):
    src = tmp_path / "results.csv"
    src.write_text("a,b\n1,2")
    spec = _make_spec_yaml(tmp_path, [{"path": str(src), "role": "data_csv"}])
    out_dir = tmp_path / "deliverable"
    assemble_figure_package(load_deliverable_spec(spec), out_dir)
    assert (out_dir / "data" / "results.csv").exists()


def test_missing_file_warning(tmp_path):
    spec = _make_spec_yaml(tmp_path, [{"path": "nonexistent.pdf", "role": "figure_pdf"}])
    out_dir = tmp_path / "deliverable"
    result = assemble_figure_package(load_deliverable_spec(spec), out_dir)
    assert result.missing_count == 1
    assert any(r.severity == "WARNING" for r in result.qa.records)


def test_manifest_written(tmp_path):
    src = tmp_path / "fig.pdf"
    src.write_bytes(b"x")
    spec = _make_spec_yaml(tmp_path, [{"path": str(src), "role": "figure_pdf"}])
    out_dir = tmp_path / "deliverable"
    result = assemble_figure_package(load_deliverable_spec(spec), out_dir)
    manifest = result.manifest_path
    assert manifest.exists()
    with manifest.open() as fh:
        rows = list(csv.DictReader(fh))
    assert "sha256" in rows[0]


def test_readme_written(tmp_path):
    spec = _make_spec_yaml(tmp_path, [])
    out_dir = tmp_path / "deliverable"
    assemble_figure_package(load_deliverable_spec(spec), out_dir)
    assert (out_dir / "README.txt").exists()


def test_copied_plus_missing_equals_total(tmp_path):
    src = tmp_path / "real.pdf"
    src.write_bytes(b"x")
    spec = _make_spec_yaml(tmp_path, [
        {"path": str(src), "role": "figure_pdf"},
        {"path": "ghost.pdf", "role": "figure_pdf"},
    ])
    out_dir = tmp_path / "deliverable"
    result = assemble_figure_package(load_deliverable_spec(spec), out_dir)
    assert result.copied_count + result.missing_count == len(load_deliverable_spec(spec))
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_report_figure_package.py -v
```

- [ ] **Step 3: Create `autogis/core/envmon/report_figure_package.py`**

```python
"""report_figure_package.py — deliverable folder assembler with manifest."""
from __future__ import annotations

import csv
import hashlib
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..common.qa import QACollector, QARecord, SEV_INFO, SEV_WARNING

DELIVERABLE_ROLES = (
    "figure_pdf", "figure_png", "data_csv",
    "qa_report", "compliance_table", "boring_log",
    "source_gdb", "coc", "other",
)

_ROLE_SUBDIR = {
    "figure_pdf": "figures", "figure_png": "figures",
    "data_csv": "data", "compliance_table": "data",
    "qa_report": "qa", "boring_log": "data",
    "source_gdb": "data", "coc": "data", "other": ".",
}

_MANIFEST_FIELDS = ["source_path", "dest_path", "role", "sha256", "status"]


@dataclass
class DeliverableFile:
    source_path: str
    dest_subdir: str
    role: str
    sha256: str
    status: str


@dataclass
class FigurePackageResult:
    out_dir: Path
    manifest_path: Path
    files: list
    copied_count: int
    missing_count: int
    qa: QACollector


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_deliverable_spec(spec_path: Path) -> list:
    import yaml
    data = yaml.safe_load(Path(spec_path).read_text(encoding="utf-8"))
    return data.get("files", [])


def assemble_figure_package(
    spec_entries: list,
    out_dir: Path,
    *,
    site_id: str = "",
    event_label: str = "",
    qa: Optional[QACollector] = None,
) -> FigurePackageResult:
    if qa is None:
        qa = QACollector()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    files: list[DeliverableFile] = []
    copied = missing = 0

    for entry in spec_entries:
        src_str = entry.get("path", "")
        role = entry.get("role", "other")
        subdir_name = _ROLE_SUBDIR.get(role, ".")
        src = Path(src_str)

        if not src.exists():
            qa.add(QARecord(SEV_WARNING, "missing_deliverable",
                            f"Source not found: {src_str}"))
            files.append(DeliverableFile(
                source_path=src_str, dest_subdir=subdir_name,
                role=role, sha256="", status="missing",
            ))
            missing += 1
            continue

        dest_dir = out_dir / subdir_name if subdir_name != "." else out_dir
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src.name
        shutil.copy2(str(src), str(dest))
        sha = _sha256_file(dest)
        files.append(DeliverableFile(
            source_path=src_str, dest_subdir=subdir_name,
            role=role, sha256=sha, status="copied",
        ))
        copied += 1

    # Write manifest
    manifest_path = out_dir / "manifest.csv"
    write_package_manifest(files, manifest_path)

    # Write README
    readme = out_dir / "README.txt"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    readme.write_text(
        f"Report Figure Package\n"
        f"Site: {site_id or '(not specified)'}\n"
        f"Event: {event_label or '(not specified)'}\n"
        f"Generated: {now}\n"
        f"Files: {copied} copied, {missing} missing\n"
        f"See manifest.csv for file inventory.\n",
        encoding="utf-8",
    )

    qa.add(QARecord(SEV_INFO, "package_assembled",
                    f"{copied} files copied, {missing} missing → {out_dir}"))

    return FigurePackageResult(
        out_dir=out_dir, manifest_path=manifest_path,
        files=files, copied_count=copied, missing_count=missing, qa=qa,
    )


def write_package_manifest(files: list, manifest_path: Path) -> None:
    with Path(manifest_path).open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=_MANIFEST_FIELDS)
        w.writeheader()
        for f in files:
            dest = str(Path(f.dest_subdir) / Path(f.source_path).name)
            w.writerow({
                "source_path": f.source_path, "dest_path": dest,
                "role": f.role, "sha256": f.sha256, "status": f.status,
            })
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_report_figure_package.py -v
```

Expected: all 8 PASS.

- [ ] **Step 5: Full suite + commit**

```bash
git add autogis/core/envmon/report_figure_package.py \
        tests/envmon/test_report_figure_package.py
git commit -m "feat(envmon): report_figure_package — deliverable folder assembler + manifest"
```

---

### Task 2: CLI command

- [ ] **Step 1: Add to `cli.py`**

```python
@envmon.command("build-report-package")
@click.option("--spec", "spec_path", required=True, type=click.Path(exists=True))
@click.option("--out-dir", required=True, type=click.Path())
@click.option("--site", "site_id", default="")
@click.option("--event-label", default="")
@click.option("--report", default=None, type=click.Path())
def build_report_package_cmd(spec_path, out_dir, site_id, event_label, report):
    """Assemble deliverable folder from YAML spec (headless)."""
    from autogis.core.envmon.report_figure_package import (
        load_deliverable_spec, assemble_figure_package)
    from autogis.core.common.qa import QACollector

    entries = load_deliverable_spec(Path(spec_path))
    qa = QACollector()
    result = assemble_figure_package(entries, Path(out_dir),
                                      site_id=site_id, event_label=event_label, qa=qa)
    click.echo(f"Copied: {result.copied_count}  Missing: {result.missing_count}  "
               f"Out: {out_dir}")
    _render_qa(qa, report, "warning")
```

- [ ] **Step 2: Help test + commit**

```python
def test_build_report_package_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "build-report-package" in result.output
```

```bash
git add autogis/adapters/cli.py tests/envmon/test_report_figure_package.py
git commit -m "feat(cli): add build-report-package command"
```
