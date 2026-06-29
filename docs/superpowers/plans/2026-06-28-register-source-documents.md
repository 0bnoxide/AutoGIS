# RegisterSourceDocuments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Implement `RegisterSourceDocuments` — an append-only CSV source-document registry that records which files were ingested, their SHA-256 hash, event/site context, and producing tool, enabling full auditability of the "which workbook produced which records?" question.
See spec: `docs/envmon-feature-roadmap.md` §2.5 (Attachment and Source-Document Registrar).

**Architecture:**
- New: `autogis/core/envmon/source_registry.py`
- Modify: `autogis/adapters/cli.py` — add `register-source-doc` command (CLOUD)
- Modify: `autogis/runtime/capabilities.py` — register `"register-source-doc": Runtime.CLOUD`
- New: `tests/envmon/test_source_registry.py`

## Global Constraints

- Arcpy-free. stdlib only: `csv`, `hashlib`, `pathlib`, `dataclasses`, `datetime`.
- Append-only CSV; header written only when the file is created (same pattern as `RunHistory` in `autogis/core/common/run_history.py`).
- CSV column names must exactly match `SourceDocRecord` field names.
- Run tests with `python -m pytest -q`.
- CLI command goes in `autogis/adapters/cli.py` under the `envmon` group.
- `register-source-doc` is CLOUD (headless, no arcpy); add to `TOOLS` dict in `autogis/runtime/capabilities.py`.

---

### Task 1: Core `source_registry.py`

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_source_registry.py`:

```python
"""Tests for autogis/core/envmon/source_registry.py."""
from pathlib import Path

import pytest

from autogis.core.envmon.source_registry import (
    SourceDocRecord,
    SourceRegistry,
    compute_sha256,
)


def _make_record(**kw) -> SourceDocRecord:
    defaults = dict(
        registered_at="2026-06-28T10:00:00",
        file_path="/data/H281/Q2-2026-lab.xlsx",
        sha256="abc123def456" * 4,  # 48 chars (short stand-in)
        file_size_bytes=20480,
        site_id="H281",
        event_id="2026-Q2",
        tool="import-edd",
        notes="",
    )
    defaults.update(kw)
    return SourceDocRecord(**defaults)


def test_register_and_list_two_records(tmp_path):
    reg = SourceRegistry(tmp_path / "source_docs.csv")
    reg.register(_make_record(file_path="/data/a.xlsx", sha256="aaa" + "0" * 61))
    reg.register(_make_record(file_path="/data/b.xlsx", sha256="bbb" + "0" * 61))
    records = reg.list_records()
    assert len(records) == 2
    paths = {r.file_path for r in records}
    assert "/data/a.xlsx" in paths
    assert "/data/b.xlsx" in paths


def test_is_registered_true_after_register(tmp_path):
    reg = SourceRegistry(tmp_path / "source_docs.csv")
    sha = "c" * 64
    reg.register(_make_record(file_path="/data/c.xlsx", sha256=sha))
    assert reg.is_registered("/data/c.xlsx", sha) is True


def test_is_registered_false_before_register(tmp_path):
    reg = SourceRegistry(tmp_path / "source_docs.csv")
    assert reg.is_registered("/data/never.xlsx", "d" * 64) is False


def test_filter_by_site_id(tmp_path):
    reg = SourceRegistry(tmp_path / "source_docs.csv")
    reg.register(_make_record(site_id="H281", sha256="e" * 64))
    reg.register(_make_record(site_id="LMFW", sha256="f" * 64))
    h281_records = reg.list_records(site_id="H281")
    assert len(h281_records) == 1
    assert h281_records[0].site_id == "H281"


def test_filter_by_event_id(tmp_path):
    reg = SourceRegistry(tmp_path / "source_docs.csv")
    reg.register(_make_record(event_id="2026-Q1", sha256="1" * 64))
    reg.register(_make_record(event_id="2026-Q2", sha256="2" * 64))
    q1 = reg.list_records(event_id="2026-Q1")
    assert len(q1) == 1
    assert q1[0].event_id == "2026-Q1"


def test_re_register_same_hash_is_registered(tmp_path):
    reg = SourceRegistry(tmp_path / "source_docs.csv")
    sha = "g" * 64
    reg.register(_make_record(file_path="/data/dup.xlsx", sha256=sha))
    # Register again (caller may choose to call is_registered first; registry itself
    # does not block duplicates — that's the CLI's --skip-if-registered job).
    # But is_registered must return True after the first registration.
    assert reg.is_registered("/data/dup.xlsx", sha) is True


def test_compute_sha256_consistent(tmp_path):
    f = tmp_path / "sample.txt"
    f.write_bytes(b"hello autogis")
    h1 = compute_sha256(f)
    h2 = compute_sha256(f)
    assert h1 == h2
    assert len(h1) == 64


def test_csv_header_written_once(tmp_path):
    csv_path = tmp_path / "source_docs.csv"
    reg = SourceRegistry(csv_path)
    reg.register(_make_record(sha256="h" * 64))
    reg.register(_make_record(sha256="i" * 64))
    lines = csv_path.read_text(encoding="utf-8").splitlines()
    # First line is header; exactly one header line
    assert lines[0].startswith("registered_at")
    header_count = sum(1 for ln in lines if ln.startswith("registered_at"))
    assert header_count == 1


def test_list_records_empty_file(tmp_path):
    reg = SourceRegistry(tmp_path / "source_docs.csv")
    assert reg.list_records() == []
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_source_registry.py -v
```

Expected: `ModuleNotFoundError` (module does not exist yet).

- [ ] **Step 3: Create `autogis/core/envmon/source_registry.py`**

```python
"""source_registry.py — append-only CSV registry of ingested source documents.

Tracks which files were processed by which tool, their SHA-256 hash, and
site/event context. Follows the RunHistory pattern in
autogis/core/common/run_history.py.
"""
from __future__ import annotations

import csv
import hashlib
import logging
from dataclasses import astuple, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_FIELDS = [
    "registered_at",
    "file_path",
    "sha256",
    "file_size_bytes",
    "site_id",
    "event_id",
    "tool",
    "notes",
]


class SourceRegistryError(Exception):
    pass


@dataclass
class SourceDocRecord:
    registered_at: str      # ISO-8601 datetime string
    file_path: str
    sha256: str             # hex digest, 64 chars
    file_size_bytes: int
    site_id: str
    event_id: str
    tool: str
    notes: str


def compute_sha256(path: Path) -> str:
    """Return the hex SHA-256 digest of *path* (reads in 64 KiB chunks)."""
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _encode(record: SourceDocRecord) -> dict:
    return {
        "registered_at": record.registered_at,
        "file_path": record.file_path,
        "sha256": record.sha256,
        "file_size_bytes": str(record.file_size_bytes),
        "site_id": record.site_id,
        "event_id": record.event_id,
        "tool": record.tool,
        "notes": record.notes,
    }


def _decode(row: dict) -> SourceDocRecord:
    return SourceDocRecord(
        registered_at=row["registered_at"],
        file_path=row["file_path"],
        sha256=row["sha256"],
        file_size_bytes=int(row["file_size_bytes"]),
        site_id=row["site_id"],
        event_id=row["event_id"],
        tool=row["tool"],
        notes=row.get("notes", ""),
    )


class SourceRegistry:
    """Thin wrapper around an append-only CSV source-document registry.

    The registry CSV columns are exactly the fields of :class:`SourceDocRecord`.
    A header row is written only when the file is first created.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    def register(self, record: SourceDocRecord) -> None:
        """Append *record* to the registry CSV, creating the file if needed."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            exists = self._path.exists()
            with self._path.open("a", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=_FIELDS)
                if not exists:
                    writer.writeheader()
                writer.writerow(_encode(record))
        except Exception as exc:
            log.warning("SourceRegistry.register failed: %s", exc)
            raise

    def _load(self) -> list[SourceDocRecord]:
        if not self._path.exists():
            return []
        try:
            with self._path.open(newline="", encoding="utf-8") as fh:
                return [_decode(row) for row in csv.DictReader(fh)]
        except Exception as exc:
            raise SourceRegistryError(
                f"Cannot read source registry at {self._path}: {exc}"
            ) from exc

    def list_records(
        self,
        site_id: Optional[str] = None,
        event_id: Optional[str] = None,
    ) -> list[SourceDocRecord]:
        """Return all records, optionally filtered by *site_id* and/or *event_id*."""
        records = self._load()
        if site_id is not None:
            records = [r for r in records if r.site_id == site_id]
        if event_id is not None:
            records = [r for r in records if r.event_id == event_id]
        return records

    def is_registered(self, file_path: str, sha256: str) -> bool:
        """Return True if a record with matching *file_path* and *sha256* exists."""
        for r in self._load():
            if r.file_path == file_path and r.sha256 == sha256:
                return True
        return False
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_source_registry.py -v
```

Expected: all 9 PASS.

- [ ] **Step 5: Commit**

```bash
git add autogis/core/envmon/source_registry.py \
        tests/envmon/test_source_registry.py
git commit -m "feat(envmon): source_registry — append-only CSV source-document registry"
```

---

### Task 2: CLI command and capabilities registration

- [ ] **Step 1: Add `register-source-doc` command to `autogis/adapters/cli.py`**

Add the following command inside the `envmon` Click group (after existing commands):

```python
@envmon.command("register-source-doc")
@click.option(
    "--file", "file_path", required=True, type=click.Path(exists=True),
    help="Path to the source file to register.",
)
@click.option("--site", "site_id", required=True, help="Site ID (e.g. H281).")
@click.option("--event", "event_id", required=True, help="Event ID (e.g. 2026-Q2).")
@click.option("--tool", "tool_name", required=True, help="Tool that ingested the file.")
@click.option(
    "--registry", "registry_path",
    default="source_docs.csv", show_default=True,
    type=click.Path(),
    help="Path to the source-document registry CSV.",
)
@click.option("--notes", default="", help="Optional free-text notes.")
@click.option(
    "--skip-if-registered", is_flag=True, default=False,
    help="Exit cleanly without writing if the file hash is already registered.",
)
def register_source_doc_cmd(
    file_path, site_id, event_id, tool_name, registry_path, notes, skip_if_registered
):
    """Register a source document in the append-only source-document registry (headless)."""
    from datetime import datetime, timezone
    from autogis.core.envmon.source_registry import (
        SourceDocRecord, SourceRegistry, compute_sha256,
    )

    p = Path(file_path)
    sha = compute_sha256(p)
    reg = SourceRegistry(Path(registry_path))

    if skip_if_registered and reg.is_registered(str(p), sha):
        click.echo("Already registered, skipped.")
        return

    record = SourceDocRecord(
        registered_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        file_path=str(p),
        sha256=sha,
        file_size_bytes=p.stat().st_size,
        site_id=site_id,
        event_id=event_id,
        tool=tool_name,
        notes=notes,
    )
    reg.register(record)
    click.echo(f"Registered: {sha[:8]} {p.name}")
```

- [ ] **Step 2: Register capability**

In `autogis/runtime/capabilities.py`, add to the `TOOLS` dict:

```python
"register-source-doc": Runtime.CLOUD,  # tool 2.5
```

- [ ] **Step 3: Write CLI tests**

Add to `tests/envmon/test_source_registry.py` (or a separate `tests/test_cli_register_source_doc.py`):

```python
"""CLI tests for envmon register-source-doc command."""
from pathlib import Path

import pytest
from click.testing import CliRunner

from autogis.adapters.cli import autogis


def _make_file(tmp_path: Path, name: str = "lab.xlsx", content: bytes = b"data") -> Path:
    f = tmp_path / name
    f.write_bytes(content)
    return f


def test_register_source_doc_basic(tmp_path):
    f = _make_file(tmp_path)
    reg = tmp_path / "source_docs.csv"
    result = CliRunner().invoke(autogis, [
        "envmon", "register-source-doc",
        "--file", str(f),
        "--site", "H281",
        "--event", "2026-Q2",
        "--tool", "import-edd",
        "--registry", str(reg),
    ])
    assert result.exit_code == 0, result.output
    assert "Registered:" in result.output
    assert "lab.xlsx" in result.output
    assert reg.exists()


def test_register_source_doc_skip_if_registered(tmp_path):
    f = _make_file(tmp_path)
    reg = tmp_path / "source_docs.csv"
    runner = CliRunner()
    args = [
        "envmon", "register-source-doc",
        "--file", str(f),
        "--site", "H281",
        "--event", "2026-Q2",
        "--tool", "import-edd",
        "--registry", str(reg),
        "--skip-if-registered",
    ]
    r1 = runner.invoke(autogis, args)
    assert r1.exit_code == 0
    assert "Registered:" in r1.output

    r2 = runner.invoke(autogis, args)
    assert r2.exit_code == 0
    assert "Already registered, skipped." in r2.output

    # CSV must still have exactly one data row
    lines = reg.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2  # header + 1 record


def test_register_source_doc_without_skip_allows_duplicate(tmp_path):
    f = _make_file(tmp_path)
    reg = tmp_path / "source_docs.csv"
    runner = CliRunner()
    args = [
        "envmon", "register-source-doc",
        "--file", str(f),
        "--site", "H281",
        "--event", "2026-Q2",
        "--tool", "import-edd",
        "--registry", str(reg),
    ]
    runner.invoke(autogis, args)
    runner.invoke(autogis, args)
    lines = reg.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3  # header + 2 records


def test_register_source_doc_with_notes(tmp_path):
    f = _make_file(tmp_path)
    reg = tmp_path / "source_docs.csv"
    result = CliRunner().invoke(autogis, [
        "envmon", "register-source-doc",
        "--file", str(f),
        "--site", "H281",
        "--event", "2026-Q2",
        "--tool", "import-edd",
        "--registry", str(reg),
        "--notes", "manual re-import after QA correction",
    ])
    assert result.exit_code == 0
    content = reg.read_text(encoding="utf-8")
    assert "manual re-import" in content


def test_register_source_doc_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "register-source-doc" in result.output
```

- [ ] **Step 4: Run CLI tests**

```
python -m pytest tests/envmon/test_source_registry.py tests/test_cli_register_source_doc.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Full suite**

```
python -m pytest -q
```

Expected: full suite PASS with no regressions.

- [ ] **Step 6: Commit**

```bash
git add autogis/adapters/cli.py \
        autogis/runtime/capabilities.py \
        tests/test_cli_register_source_doc.py
git commit -m "feat(envmon): register-source-doc CLI — source document registry command (CLOUD)"
```

---

## Run commands

```bash
# Task 1 — core module tests (expect failure before implementation)
python -m pytest tests/envmon/test_source_registry.py -v

# Task 1 — after implementation
python -m pytest tests/envmon/test_source_registry.py -v

# Task 2 — CLI tests
python -m pytest tests/test_cli_register_source_doc.py -v

# Final full suite
python -m pytest -q
```
