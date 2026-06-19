# Attachment Harvester Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a runtime-agnostic core plus a CLI adapter that bulk-downloads attachments from an ArcGIS Online / Survey123 feature layer, organized into attribute-grouped folders, idempotent and resilient, with a CSV+JSON manifest per run.

**Architecture:** Core-plus-adapters. A pure-Python `autogis.core` package holds all harvest logic and receives an already-connected `arcgis.gis.GIS` object plus a `HarvestConfig`. A thin `autogis.adapters.cli` builds the `GIS` (stored profile, falling back to env-var username/password) and a `HarvestConfig`, then calls the core. The core never imports `arcpy` and never assumes how it was invoked, so Pro-toolbox and Notebook adapters can be added later without touching it.

**Tech Stack:** Python 3.x, `arcgis` (ArcGIS API for Python), `PyYAML`, `click`, `pytest`. Tests mock the `arcgis`/`GIS` layer — no network or live credentials.

## Global Constraints

- Core (`autogis/core/**`) MUST NOT import `arcpy` or anything CLI-specific; it receives a connected `GIS` and a `HarvestConfig` only.
- Secrets never appear in config files or command-line arguments — only a profile name, or env vars `AGOL_USER` / `AGOL_PASS`.
- Default `where` clause is `1=1`. Default options: `skip_existing: true`, `incremental: false`, `retries: 3`, `backoff_seconds: 2`.
- Filename templates must include a feature-level identifier (e.g. `OBJECTID`) since attribute-grouping places many features in one folder.
- Missing/null template fields substitute the literal token `_unknown` rather than raising.
- Filesystem sanitization: strip characters `<>:"/\|?*`, collapse whitespace runs to a single `_`, strip leading/trailing dots and spaces.
- Manifest is written as BOTH `manifest.csv` and `manifest.json` per run.
- Per-attachment status vocabulary: `downloaded`, `skipped`, `failed`.
- All dev tooling runs via `pytest` from the repo root. Python package import root is the repo root (`autogis` is an importable package).
- Every task is TDD: failing test first, minimal implementation, passing test, commit.

---

### Task 1: Project scaffolding, data models, and dependency setup

**Files:**
- Create: `pyproject.toml`
- Create: `autogis/__init__.py`
- Create: `autogis/core/__init__.py`
- Create: `autogis/adapters/__init__.py`
- Create: `autogis/core/models.py`
- Create: `tests/__init__.py`
- Create: `tests/test_models.py`
- Create: `.gitignore`

**Interfaces:**
- Consumes: nothing (first task).
- Produces:
  - `autogis.core.models.HarvestConfig` — frozen-ish dataclass with fields:
    `item_id: str | None`, `url: str | None`, `where: str = "1=1"`,
    `directory: str`, `group_template: str`, `filename_template: str`,
    `incremental: bool = False`, `skip_existing: bool = True`,
    `retries: int = 3`, `backoff_seconds: float = 2`.
    Method `layer_ref() -> str` returns `url` if set else `item_id`; raises `ValueError` if both are None.
  - `autogis.core.models.AttachmentResult` — dataclass:
    `objectid: int`, `attachment_id: int`, `original_name: str`,
    `saved_path: str | None`, `size: int | None`, `status: str`, `error: str | None = None`.
  - `autogis.core.models.RunSummary` — dataclass:
    `downloaded: int = 0`, `skipped: int = 0`, `failed: int = 0`.
    Method `record(status: str) -> None` increments the matching counter; raises `ValueError` on unknown status.

- [ ] **Step 1: Write `.gitignore`**

```
__pycache__/
*.pyc
.pytest_cache/
*.egg-info/
.venv/
harvest/
.superpowers/
```

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[project]
name = "autogis"
version = "0.1.0"
description = "Automation tools for ArcGIS Pro and ArcGIS Online / Survey123"
requires-python = ">=3.9"
dependencies = ["arcgis", "PyYAML", "click"]

[project.optional-dependencies]
dev = ["pytest"]

[project.scripts]
autogis-harvest = "autogis.adapters.cli:main"

[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["autogis*"]
```

- [ ] **Step 3: Create empty package init files**

Create `autogis/__init__.py`, `autogis/core/__init__.py`, `autogis/adapters/__init__.py`, `tests/__init__.py` — all empty.

- [ ] **Step 4: Write the failing test** in `tests/test_models.py`

```python
import pytest
from autogis.core.models import HarvestConfig, AttachmentResult, RunSummary


def test_layer_ref_prefers_url():
    cfg = HarvestConfig(item_id="abc", url="http://x/0", directory="d",
                         group_template="{S}", filename_template="{OBJECTID}")
    assert cfg.layer_ref() == "http://x/0"


def test_layer_ref_falls_back_to_item_id():
    cfg = HarvestConfig(item_id="abc", url=None, directory="d",
                        group_template="{S}", filename_template="{OBJECTID}")
    assert cfg.layer_ref() == "abc"


def test_layer_ref_raises_when_both_missing():
    cfg = HarvestConfig(item_id=None, url=None, directory="d",
                        group_template="{S}", filename_template="{OBJECTID}")
    with pytest.raises(ValueError):
        cfg.layer_ref()


def test_config_defaults():
    cfg = HarvestConfig(item_id="a", url=None, directory="d",
                        group_template="{S}", filename_template="{OBJECTID}")
    assert cfg.where == "1=1"
    assert cfg.skip_existing is True
    assert cfg.incremental is False
    assert cfg.retries == 3
    assert cfg.backoff_seconds == 2


def test_run_summary_record():
    s = RunSummary()
    s.record("downloaded")
    s.record("skipped")
    s.record("failed")
    s.record("failed")
    assert (s.downloaded, s.skipped, s.failed) == (1, 1, 2)


def test_run_summary_rejects_unknown_status():
    s = RunSummary()
    with pytest.raises(ValueError):
        s.record("bogus")


def test_attachment_result_fields():
    r = AttachmentResult(objectid=5, attachment_id=2, original_name="p.jpg",
                         saved_path="/tmp/p.jpg", size=10, status="downloaded")
    assert r.status == "downloaded"
    assert r.error is None
```

- [ ] **Step 5: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'autogis.core.models'`

- [ ] **Step 6: Write minimal implementation** in `autogis/core/models.py`

```python
from dataclasses import dataclass

VALID_STATUSES = ("downloaded", "skipped", "failed")


@dataclass
class HarvestConfig:
    directory: str
    group_template: str
    filename_template: str
    item_id: str | None = None
    url: str | None = None
    where: str = "1=1"
    incremental: bool = False
    skip_existing: bool = True
    retries: int = 3
    backoff_seconds: float = 2

    def layer_ref(self) -> str:
        if self.url:
            return self.url
        if self.item_id:
            return self.item_id
        raise ValueError("HarvestConfig requires either url or item_id")


@dataclass
class AttachmentResult:
    objectid: int
    attachment_id: int
    original_name: str
    saved_path: str | None
    size: int | None
    status: str
    error: str | None = None


@dataclass
class RunSummary:
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0

    def record(self, status: str) -> None:
        if status not in VALID_STATUSES:
            raise ValueError(f"unknown status: {status}")
        setattr(self, status, getattr(self, status) + 1)
```

Note: the test constructs `HarvestConfig` with keyword args, so field order does not affect tests. Keeping required fields first satisfies dataclass ordering.

- [ ] **Step 7: Run test to verify it passes**

Run: `pytest tests/test_models.py -v`
Expected: PASS (7 passed)

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml .gitignore autogis tests
git commit -m "feat: scaffold autogis package with core data models"
```

---

### Task 2: Template rendering and filesystem sanitization

**Files:**
- Create: `autogis/core/templates.py`
- Create: `tests/test_templates.py`

**Interfaces:**
- Consumes: nothing from core (pure string utilities).
- Produces:
  - `autogis.core.templates.sanitize(part: str) -> str` — sanitize a single path component per Global Constraints. Empty/blank result returns `_unknown`.
  - `autogis.core.templates.render(template: str, attributes: dict) -> str` —
    replace each `{Field}` with `str(attributes[Field])`; if `Field` is missing
    or its value is `None`, substitute `_unknown`. Returns the rendered string
    WITHOUT sanitization (caller sanitizes per path component).
  - `autogis.core.templates.render_path_component(template, attributes) -> str` —
    `sanitize(render(template, attributes))`.

- [ ] **Step 1: Write the failing test** in `tests/test_templates.py`

```python
from autogis.core.templates import sanitize, render, render_path_component


def test_sanitize_strips_illegal_chars():
    assert sanitize('a<b>c:d"e/f\\g|h?i*j') == "abcdefghij"


def test_sanitize_collapses_whitespace():
    assert sanitize("a   b\tc") == "a_b_c"


def test_sanitize_strips_edge_dots_and_spaces():
    assert sanitize("  .name.  ") == "name"


def test_sanitize_blank_becomes_unknown():
    assert sanitize("   ") == "_unknown"
    assert sanitize("") == "_unknown"


def test_render_substitutes_fields():
    out = render("{InspectionID}_{OBJECTID}_{name}",
                 {"InspectionID": "INS5", "OBJECTID": 12, "name": "photo.jpg"})
    assert out == "INS5_12_photo.jpg"


def test_render_missing_field_is_unknown():
    assert render("{Status}", {}) == "_unknown"


def test_render_none_value_is_unknown():
    assert render("{Status}", {"Status": None}) == "_unknown"


def test_render_path_component_sanitizes():
    out = render_path_component("{Status}", {"Status": "In/Progress"})
    assert out == "InProgress"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_templates.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'autogis.core.templates'`

- [ ] **Step 3: Write minimal implementation** in `autogis/core/templates.py`

```python
import re

_ILLEGAL = re.compile(r'[<>:"/\\|?*]')
_WS = re.compile(r"\s+")
_FIELD = re.compile(r"\{([^}]+)\}")
UNKNOWN = "_unknown"


def sanitize(part: str) -> str:
    cleaned = _ILLEGAL.sub("", part)
    cleaned = _WS.sub("_", cleaned)
    cleaned = cleaned.strip("._ ")
    return cleaned or UNKNOWN


def render(template: str, attributes: dict) -> str:
    def repl(match):
        field = match.group(1)
        value = attributes.get(field)
        if value is None:
            return UNKNOWN
        return str(value)
    return _FIELD.sub(repl, template)


def render_path_component(template: str, attributes: dict) -> str:
    return sanitize(render(template, attributes))
```

Note on `test_sanitize_collapses_whitespace`: `"a   b\tc"` → collapse to `a_b_c`, no edge stripping needed. For `"  .name.  "`: illegal-sub no-op, whitespace collapse yields `_.name._`, then `strip("._ ")` → `name`. Verify both in the run.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_templates.py -v`
Expected: PASS (8 passed). If `test_sanitize_collapses_whitespace` fails because edge underscores remain, note that `strip("._ ")` does not strip underscores — but this test has no edge whitespace so result is exactly `a_b_c`. Confirm green.

- [ ] **Step 5: Commit**

```bash
git add autogis/core/templates.py tests/test_templates.py
git commit -m "feat: add template rendering and path sanitization"
```

---

### Task 3: Manifest accumulation and CSV+JSON serialization

**Files:**
- Create: `autogis/core/manifest.py`
- Create: `tests/test_manifest.py`

**Interfaces:**
- Consumes: `autogis.core.models.AttachmentResult`.
- Produces:
  - `autogis.core.manifest.Manifest` class:
    - `add(result: AttachmentResult) -> None` — append a result.
    - `results -> list[AttachmentResult]` — accumulated results (attribute).
    - `write_csv(path: str) -> None` — write one row per result with header
      `objectid,attachment_id,original_name,saved_path,size,status,error`.
    - `write_json(path: str) -> None` — write a JSON array of objects with the
      same field names (dataclass field order).
    - `write(directory: str) -> tuple[str, str]` — write `manifest.csv` and
      `manifest.json` into `directory`, creating it if needed; return the two paths.

- [ ] **Step 1: Write the failing test** in `tests/test_manifest.py`

```python
import csv
import json
from autogis.core.models import AttachmentResult
from autogis.core.manifest import Manifest


def _sample():
    m = Manifest()
    m.add(AttachmentResult(1, 10, "a.jpg", "/out/G/a.jpg", 100, "downloaded"))
    m.add(AttachmentResult(2, 11, "b.jpg", None, None, "failed", "timeout"))
    return m


def test_write_csv(tmp_path):
    path = tmp_path / "manifest.csv"
    _sample().write_csv(str(path))
    rows = list(csv.DictReader(path.open()))
    assert rows[0]["objectid"] == "1"
    assert rows[0]["status"] == "downloaded"
    assert rows[1]["status"] == "failed"
    assert rows[1]["error"] == "timeout"


def test_write_json(tmp_path):
    path = tmp_path / "manifest.json"
    _sample().write_json(str(path))
    data = json.loads(path.read_text())
    assert len(data) == 2
    assert data[0]["attachment_id"] == 10
    assert data[1]["saved_path"] is None


def test_write_creates_both(tmp_path):
    out = tmp_path / "nested"
    csv_path, json_path = _sample().write(str(out))
    assert (out / "manifest.csv").exists()
    assert (out / "manifest.json").exists()
    assert csv_path.endswith("manifest.csv")
    assert json_path.endswith("manifest.json")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_manifest.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'autogis.core.manifest'`

- [ ] **Step 3: Write minimal implementation** in `autogis/core/manifest.py`

```python
import csv
import json
import os
from dataclasses import asdict, fields
from .models import AttachmentResult

_FIELDS = [f.name for f in fields(AttachmentResult)]


class Manifest:
    def __init__(self):
        self.results: list[AttachmentResult] = []

    def add(self, result: AttachmentResult) -> None:
        self.results.append(result)

    def write_csv(self, path: str) -> None:
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_FIELDS)
            writer.writeheader()
            for r in self.results:
                writer.writerow(asdict(r))

    def write_json(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump([asdict(r) for r in self.results], fh, indent=2)

    def write(self, directory: str) -> tuple[str, str]:
        os.makedirs(directory, exist_ok=True)
        csv_path = os.path.join(directory, "manifest.csv")
        json_path = os.path.join(directory, "manifest.json")
        self.write_csv(csv_path)
        self.write_json(json_path)
        return csv_path, json_path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_manifest.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add autogis/core/manifest.py tests/test_manifest.py
git commit -m "feat: add manifest accumulation with CSV and JSON output"
```

---

### Task 4: Incremental state file (last-run timestamp)

**Files:**
- Create: `autogis/core/state.py`
- Create: `tests/test_state.py`

**Interfaces:**
- Consumes: nothing from core.
- Produces:
  - `autogis.core.state.read_last_run(directory: str) -> int | None` — read
    epoch-milliseconds integer from `<directory>/.harvest_state.json` key
    `last_run_ms`; return `None` if the file or key is absent.
  - `autogis.core.state.write_last_run(directory: str, last_run_ms: int) -> None` —
    create `directory` if needed and write `{"last_run_ms": <int>}` to that file.

- [ ] **Step 1: Write the failing test** in `tests/test_state.py`

```python
from autogis.core.state import read_last_run, write_last_run


def test_read_missing_returns_none(tmp_path):
    assert read_last_run(str(tmp_path)) is None


def test_write_then_read(tmp_path):
    write_last_run(str(tmp_path), 1718000000000)
    assert read_last_run(str(tmp_path)) == 1718000000000


def test_write_creates_directory(tmp_path):
    nested = tmp_path / "deep" / "dir"
    write_last_run(str(nested), 42)
    assert read_last_run(str(nested)) == 42
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_state.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'autogis.core.state'`

- [ ] **Step 3: Write minimal implementation** in `autogis/core/state.py`

```python
import json
import os

_FILENAME = ".harvest_state.json"


def _path(directory: str) -> str:
    return os.path.join(directory, _FILENAME)


def read_last_run(directory: str) -> int | None:
    path = _path(directory)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    value = data.get("last_run_ms")
    return int(value) if value is not None else None


def write_last_run(directory: str, last_run_ms: int) -> None:
    os.makedirs(directory, exist_ok=True)
    with open(_path(directory), "w", encoding="utf-8") as fh:
        json.dump({"last_run_ms": int(last_run_ms)}, fh)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_state.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add autogis/core/state.py tests/test_state.py
git commit -m "feat: add incremental last-run state file"
```

---

### Task 5: Single-attachment download with retry/backoff

**Files:**
- Create: `autogis/core/download.py`
- Create: `tests/test_download.py`

**Interfaces:**
- Consumes: nothing from core (operates on a duck-typed feature-layer object).
- Produces:
  - `autogis.core.download.download_one(layer, objectid, attachment_id, dest_path, retries, backoff_seconds, sleep=time.sleep) -> None` —
    calls `layer.attachments.download(oid=objectid, attachment_id=attachment_id, save_path=<dir of dest_path>)`,
    which returns the path of the downloaded temp file; then moves/renames it to
    `dest_path`. Retries up to `retries` times on any exception, sleeping
    `backoff_seconds * attempt` between attempts via the injected `sleep`. Raises
    the last exception if all attempts fail. The `sleep` parameter is injectable so
    tests run instantly.

Note: the real `arcgis` `AttachmentManager.download` saves into a directory and
returns the saved file path (a list in some versions). The implementation must
normalize a list return to its first element before moving.

- [ ] **Step 1: Write the failing test** in `tests/test_download.py`

```python
import os
import pytest
from autogis.core.download import download_one


class FakeAttachments:
    def __init__(self, fail_times=0, returns_list=False):
        self.fail_times = fail_times
        self.calls = 0
        self.returns_list = returns_list

    def download(self, oid, attachment_id, save_path):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("network blip")
        tmp = os.path.join(save_path, f"raw_{attachment_id}.bin")
        with open(tmp, "wb") as fh:
            fh.write(b"data")
        return [tmp] if self.returns_list else tmp


class FakeLayer:
    def __init__(self, attachments):
        self.attachments = attachments


def test_download_success(tmp_path):
    layer = FakeLayer(FakeAttachments())
    dest = tmp_path / "G" / "final.jpg"
    download_one(layer, 1, 10, str(dest), retries=3, backoff_seconds=0,
                 sleep=lambda s: None)
    assert dest.exists()
    assert dest.read_bytes() == b"data"


def test_download_normalizes_list_return(tmp_path):
    layer = FakeLayer(FakeAttachments(returns_list=True))
    dest = tmp_path / "final.jpg"
    download_one(layer, 1, 10, str(dest), retries=3, backoff_seconds=0,
                 sleep=lambda s: None)
    assert dest.exists()


def test_download_retries_then_succeeds(tmp_path):
    attachments = FakeAttachments(fail_times=2)
    layer = FakeLayer(attachments)
    dest = tmp_path / "final.jpg"
    download_one(layer, 1, 10, str(dest), retries=3, backoff_seconds=0,
                 sleep=lambda s: None)
    assert dest.exists()
    assert attachments.calls == 3


def test_download_exhausts_retries_and_raises(tmp_path):
    attachments = FakeAttachments(fail_times=99)
    layer = FakeLayer(attachments)
    dest = tmp_path / "final.jpg"
    with pytest.raises(RuntimeError):
        download_one(layer, 1, 10, str(dest), retries=2, backoff_seconds=0,
                     sleep=lambda s: None)
    assert attachments.calls == 3  # initial + 2 retries
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_download.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'autogis.core.download'`

- [ ] **Step 3: Write minimal implementation** in `autogis/core/download.py`

```python
import os
import shutil
import time


def download_one(layer, objectid, attachment_id, dest_path, retries,
                 backoff_seconds, sleep=time.sleep):
    dest_dir = os.path.dirname(dest_path)
    os.makedirs(dest_dir, exist_ok=True)

    attempt = 0
    while True:
        try:
            saved = layer.attachments.download(
                oid=objectid, attachment_id=attachment_id, save_path=dest_dir)
            if isinstance(saved, (list, tuple)):
                saved = saved[0]
            if os.path.abspath(saved) != os.path.abspath(dest_path):
                shutil.move(saved, dest_path)
            return
        except Exception:
            if attempt >= retries:
                raise
            attempt += 1
            sleep(backoff_seconds * attempt)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_download.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add autogis/core/download.py tests/test_download.py
git commit -m "feat: add single-attachment download with retry and backoff"
```

---

### Task 6: Harvester orchestration (the core loop)

**Files:**
- Create: `autogis/core/harvester.py`
- Create: `tests/test_harvester.py`

**Interfaces:**
- Consumes: `HarvestConfig`, `AttachmentResult`, `RunSummary` (models),
  `Manifest` (manifest), `render_path_component` (templates),
  `download_one` (download), `read_last_run`/`write_last_run` (state).
- Produces:
  - `autogis.core.harvester.resolve_layer(gis, config) -> layer` — returns
    `gis.content.get(item_id).layers[0]` when `config.url` is unset, else a
    `FeatureLayer(config.url, gis)`. Raises `ValueError` with a clear message if
    the layer has no `attachments`-enabled property
    (`layer.properties.hasAttachments` is falsy).
  - `autogis.core.harvester.harvest(gis, config, *, layer=None, now_ms=None, sleep=...) -> RunSummary` —
    runs the full loop and returns the summary. `layer` may be injected for tests
    (skipping `resolve_layer`). Writes manifest + state as a side effect.
  - Module constant `FeatureLayer` import is wrapped so tests need not install `arcgis`.

**Behavior (per spec data flow):**
1. If `layer` is None, call `resolve_layer(gis, config)`.
2. Build the effective where clause: start from `config.where`; if
   `config.incremental`, read `last_run_ms = read_last_run(config.directory)` and,
   when not None, AND in `EditDate > <last_run_ms>` (epoch ms). Raise `ValueError`
   if `config.incremental` and `layer.properties.editingInfo` lacks
   `lastEditDate`/editor tracking — detected via missing `editorTrackingInfo`.
3. Query features: `layer.query(where=<effective_where>, out_fields="*", return_geometry=False)`;
   iterate `.features`, each a duck-typed object with `.attributes` dict.
4. For each feature, read `OBJECTID` from attributes (key `OBJECTID`), list
   attachments via `layer.attachments.get_list(oid=objectid)` → list of dicts with
   keys `id`, `name`, `size`.
5. For each attachment compute target:
   `group = render_path_component(config.group_template, attrs)`,
   `fname = render_path_component(config.filename_template, {**attrs, "name": att["name"]})`,
   `dest = os.path.join(config.directory, group, fname)`.
6. If `config.skip_existing` and `os.path.exists(dest)`: record `skipped`.
7. Else try `download_one(...)`; on success record `downloaded` with size; on
   exception record `failed` with `str(exc)` (never re-raise).
8. After all features: `manifest.write(config.directory)`. If `config.incremental`,
   `write_last_run(config.directory, now_ms or int(time.time()*1000))`.
9. Return `RunSummary`.

- [ ] **Step 1: Write the failing test** in `tests/test_harvester.py`

```python
import os
import pytest
from autogis.core.models import HarvestConfig
from autogis.core import harvester


class FakeFeature:
    def __init__(self, attributes):
        self.attributes = attributes


class FakeQueryResult:
    def __init__(self, features):
        self.features = features


class FakeAttachmentMgr:
    def __init__(self, listing, fail_ids=()):
        self.listing = listing          # {oid: [ {id,name,size}, ... ]}
        self.fail_ids = set(fail_ids)

    def get_list(self, oid):
        return self.listing.get(oid, [])

    def download(self, oid, attachment_id, save_path):
        if attachment_id in self.fail_ids:
            raise RuntimeError("boom")
        tmp = os.path.join(save_path, f"raw_{attachment_id}.bin")
        with open(tmp, "wb") as fh:
            fh.write(b"x")
        return tmp


class FakeProps(dict):
    __getattr__ = dict.get


class FakeLayer:
    def __init__(self, features, listing, fail_ids=(), props=None):
        self._features = features
        self.attachments = FakeAttachmentMgr(listing, fail_ids)
        self.properties = props if props is not None else {"hasAttachments": True}

    def query(self, where, out_fields, return_geometry):
        self.last_where = where
        return FakeQueryResult(self._features)


def _cfg(tmp_path, **kw):
    base = dict(item_id="x", url=None, directory=str(tmp_path),
                group_template="{Status}",
                filename_template="{OBJECTID}_{name}")
    base.update(kw)
    return HarvestConfig(**base)


def test_harvest_downloads_and_groups(tmp_path):
    features = [FakeFeature({"OBJECTID": 1, "Status": "Done"}),
                FakeFeature({"OBJECTID": 2, "Status": "Open"})]
    listing = {1: [{"id": 10, "name": "a.jpg", "size": 4}],
               2: [{"id": 20, "name": "b.jpg", "size": 5}]}
    layer = FakeLayer(features, listing)
    summary = harvester.harvest(None, _cfg(tmp_path), layer=layer,
                                now_ms=123, sleep=lambda s: None)
    assert summary.downloaded == 2
    assert (tmp_path / "Done" / "1_a.jpg").exists()
    assert (tmp_path / "Open" / "2_b.jpg").exists()
    assert (tmp_path / "manifest.csv").exists()
    assert (tmp_path / "manifest.json").exists()


def test_harvest_skips_existing(tmp_path):
    features = [FakeFeature({"OBJECTID": 1, "Status": "Done"})]
    listing = {1: [{"id": 10, "name": "a.jpg", "size": 4}]}
    layer = FakeLayer(features, listing)
    target = tmp_path / "Done" / "1_a.jpg"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old")
    summary = harvester.harvest(None, _cfg(tmp_path), layer=layer,
                                now_ms=1, sleep=lambda s: None)
    assert summary.skipped == 1
    assert summary.downloaded == 0
    assert target.read_bytes() == b"old"


def test_harvest_records_failure_and_continues(tmp_path):
    features = [FakeFeature({"OBJECTID": 1, "Status": "Done"}),
                FakeFeature({"OBJECTID": 2, "Status": "Done"})]
    listing = {1: [{"id": 10, "name": "a.jpg", "size": 4}],
               2: [{"id": 20, "name": "b.jpg", "size": 5}]}
    layer = FakeLayer(features, listing, fail_ids=(10,))
    summary = harvester.harvest(None, _cfg(tmp_path, retries=1), layer=layer,
                                now_ms=1, sleep=lambda s: None)
    assert summary.failed == 1
    assert summary.downloaded == 1
    assert (tmp_path / "Done" / "2_b.jpg").exists()


def test_resolve_layer_rejects_no_attachments(tmp_path):
    layer = FakeLayer([], {}, props={"hasAttachments": False})

    class FakeContent:
        def get(self, item_id):
            class Item:
                layers = [layer]
            return Item()

    class FakeGIS:
        content = FakeContent()

    with pytest.raises(ValueError):
        harvester.resolve_layer(FakeGIS(), _cfg(tmp_path))


def test_incremental_writes_state_and_filters(tmp_path):
    features = [FakeFeature({"OBJECTID": 1, "Status": "Done"})]
    listing = {1: [{"id": 10, "name": "a.jpg", "size": 4}]}
    props = {"hasAttachments": True,
             "editorTrackingInfo": {"enableEditorTracking": True}}
    layer = FakeLayer(features, listing, props=props)
    from autogis.core import state
    state.write_last_run(str(tmp_path), 500)
    summary = harvester.harvest(None, _cfg(tmp_path, incremental=True),
                                layer=layer, now_ms=999, sleep=lambda s: None)
    assert "EditDate > 500" in layer.last_where
    assert state.read_last_run(str(tmp_path)) == 999
    assert summary.downloaded == 1


def test_incremental_without_tracking_raises(tmp_path):
    layer = FakeLayer([], {}, props={"hasAttachments": True})
    with pytest.raises(ValueError):
        harvester.harvest(None, _cfg(tmp_path, incremental=True),
                          layer=layer, now_ms=1, sleep=lambda s: None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_harvester.py -v`
Expected: FAIL with `ModuleNotFoundError` / `AttributeError: module 'autogis.core.harvester' has no attribute 'harvest'`

- [ ] **Step 3: Write minimal implementation** in `autogis/core/harvester.py`

```python
import os
import time

from .models import AttachmentResult, RunSummary
from .manifest import Manifest
from .templates import render_path_component
from .download import download_one
from .state import read_last_run, write_last_run

try:  # arcgis is optional at import time (tests inject the layer)
    from arcgis.features import FeatureLayer
except Exception:  # pragma: no cover - exercised only without arcgis installed
    FeatureLayer = None


def _prop(props, key, default=None):
    if isinstance(props, dict):
        return props.get(key, default)
    return getattr(props, key, default)


def resolve_layer(gis, config):
    if config.url:
        if FeatureLayer is None:
            raise RuntimeError("arcgis is required to resolve a layer by URL")
        layer = FeatureLayer(config.url, gis)
    else:
        item = gis.content.get(config.item_id)
        layer = item.layers[0]
    if not _prop(layer.properties, "hasAttachments"):
        raise ValueError(
            f"Layer {config.layer_ref()} does not have attachments enabled")
    return layer


def _effective_where(config, layer):
    where = config.where
    if not config.incremental:
        return where
    if not _prop(layer.properties, "editorTrackingInfo"):
        raise ValueError(
            "Incremental run requires editor tracking, which this layer lacks")
    last = read_last_run(config.directory)
    if last is not None:
        clause = f"EditDate > {last}"
        where = clause if where in ("1=1", "", None) else f"({where}) AND {clause}"
    return where


def harvest(gis, config, *, layer=None, now_ms=None, sleep=time.sleep):
    if layer is None:
        layer = resolve_layer(gis, config)

    where = _effective_where(config, layer)
    summary = RunSummary()
    manifest = Manifest()

    result = layer.query(where=where, out_fields="*", return_geometry=False)
    for feature in result.features:
        attrs = feature.attributes
        objectid = attrs.get("OBJECTID")
        for att in layer.attachments.get_list(oid=objectid):
            att_id, name, size = att["id"], att["name"], att.get("size")
            group = render_path_component(config.group_template, attrs)
            fname = render_path_component(
                config.filename_template, {**attrs, "name": name})
            dest = os.path.join(config.directory, group, fname)

            if config.skip_existing and os.path.exists(dest):
                summary.record("skipped")
                manifest.add(AttachmentResult(
                    objectid, att_id, name, dest, size, "skipped"))
                continue
            try:
                download_one(layer, objectid, att_id, dest,
                             config.retries, config.backoff_seconds, sleep=sleep)
                summary.record("downloaded")
                manifest.add(AttachmentResult(
                    objectid, att_id, name, dest, size, "downloaded"))
            except Exception as exc:  # resilience: never kill the run
                summary.record("failed")
                manifest.add(AttachmentResult(
                    objectid, att_id, name, None, size, "failed", str(exc)))

    manifest.write(config.directory)
    if config.incremental:
        write_last_run(config.directory, now_ms or int(time.time() * 1000))
    return summary
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_harvester.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Run the whole suite**

Run: `pytest -v`
Expected: PASS (all tests from Tasks 1-6 green)

- [ ] **Step 6: Commit**

```bash
git add autogis/core/harvester.py tests/test_harvester.py
git commit -m "feat: add harvester orchestration loop"
```

---

### Task 7: GIS session builder (profile + env-var fallback)

**Files:**
- Create: `autogis/core/gis_session.py`
- Create: `tests/test_gis_session.py`

**Interfaces:**
- Consumes: nothing from core.
- Produces:
  - `autogis.core.gis_session.build_gis(profile=None, username=None, password=None, gis_factory=GIS) -> GIS` —
    if `profile` is set, return `gis_factory(profile=profile)`. Else if both
    `username` and `password` are set, return
    `gis_factory("https://www.arcgis.com", username, password)`. Else raise
    `ValueError("No credentials: set a profile or AGOL_USER/AGOL_PASS")`.
    `gis_factory` is injectable so tests avoid importing/calling real `arcgis`.
  - `autogis.core.gis_session.build_gis_from_env(profile, gis_factory=GIS) -> GIS` —
    convenience that reads `AGOL_USER`/`AGOL_PASS` from `os.environ` and calls
    `build_gis(profile=profile, username=..., password=..., gis_factory=...)`.

- [ ] **Step 1: Write the failing test** in `tests/test_gis_session.py`

```python
import pytest
from autogis.core import gis_session


def fake_factory(*args, **kwargs):
    return ("GIS", args, kwargs)


def test_build_gis_with_profile():
    out = gis_session.build_gis(profile="myprof", gis_factory=fake_factory)
    assert out == ("GIS", (), {"profile": "myprof"})


def test_build_gis_with_userpass():
    out = gis_session.build_gis(username="u", password="p",
                                gis_factory=fake_factory)
    assert out == ("GIS", ("https://www.arcgis.com", "u", "p"), {})


def test_build_gis_profile_wins_over_userpass():
    out = gis_session.build_gis(profile="myprof", username="u", password="p",
                                gis_factory=fake_factory)
    assert out == ("GIS", (), {"profile": "myprof"})


def test_build_gis_no_creds_raises():
    with pytest.raises(ValueError):
        gis_session.build_gis(gis_factory=fake_factory)


def test_build_gis_from_env(monkeypatch):
    monkeypatch.setenv("AGOL_USER", "envu")
    monkeypatch.setenv("AGOL_PASS", "envp")
    out = gis_session.build_gis_from_env(profile=None, gis_factory=fake_factory)
    assert out == ("GIS", ("https://www.arcgis.com", "envu", "envp"), {})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gis_session.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'autogis.core.gis_session'`

- [ ] **Step 3: Write minimal implementation** in `autogis/core/gis_session.py`

```python
import os

try:
    from arcgis.gis import GIS
except Exception:  # pragma: no cover
    GIS = None

AGOL_URL = "https://www.arcgis.com"


def build_gis(profile=None, username=None, password=None, gis_factory=GIS):
    if gis_factory is None:
        raise RuntimeError("arcgis is not installed; cannot build a GIS")
    if profile:
        return gis_factory(profile=profile)
    if username and password:
        return gis_factory(AGOL_URL, username, password)
    raise ValueError("No credentials: set a profile or AGOL_USER/AGOL_PASS")


def build_gis_from_env(profile, gis_factory=GIS):
    return build_gis(
        profile=profile,
        username=os.environ.get("AGOL_USER"),
        password=os.environ.get("AGOL_PASS"),
        gis_factory=gis_factory,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gis_session.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add autogis/core/gis_session.py tests/test_gis_session.py
git commit -m "feat: add GIS session builder with profile and env fallback"
```

---

### Task 8: Config loading (YAML + CLI override merge)

**Files:**
- Create: `autogis/adapters/config_loader.py`
- Create: `autogis/config/inspection-job.example.yaml`
- Create: `tests/test_config_loader.py`

**Interfaces:**
- Consumes: `HarvestConfig` (models).
- Produces:
  - `autogis.adapters.config_loader.load_config(path, overrides=None) -> tuple[HarvestConfig, str | None]` —
    parse the YAML structure (sections `connection`, `layer`, `output`,
    `options`), apply non-None `overrides` (flat dict with keys
    `where`, `directory`, `incremental`), construct and return
    `(HarvestConfig, profile_name)`. `profile_name` comes from
    `connection.profile` (may be None).
  - Override keys map to: `where`→`where`, `directory`→`directory`,
    `incremental`→`incremental`. Unset (None) overrides are ignored.

- [ ] **Step 1: Write the example config** `autogis/config/inspection-job.example.yaml`

```yaml
connection:
  profile: my_agol_profile        # primary; env vars AGOL_USER/AGOL_PASS are the fallback
layer:
  item_id: "abcd1234ef567890abcd1234ef567890"   # or set url instead
  url: null
  where: "Status = 'Complete'"    # optional; default 1=1
output:
  directory: "./harvest"
  group_template: "{Status}"
  filename_template: "{InspectionID}_{OBJECTID}_{name}"
options:
  incremental: false
  skip_existing: true
  retries: 3
  backoff_seconds: 2
```

- [ ] **Step 2: Write the failing test** in `tests/test_config_loader.py`

```python
import textwrap
from autogis.adapters.config_loader import load_config


def _write(tmp_path, body):
    p = tmp_path / "job.yaml"
    p.write_text(textwrap.dedent(body))
    return str(p)


def test_load_basic(tmp_path):
    path = _write(tmp_path, """
        connection:
          profile: prof1
        layer:
          item_id: "abc"
          where: "Status = 'Done'"
        output:
          directory: "./out"
          group_template: "{Status}"
          filename_template: "{OBJECTID}_{name}"
        options:
          retries: 5
    """)
    cfg, profile = load_config(path)
    assert profile == "prof1"
    assert cfg.item_id == "abc"
    assert cfg.where == "Status = 'Done'"
    assert cfg.directory == "./out"
    assert cfg.retries == 5
    assert cfg.skip_existing is True   # default applied


def test_defaults_when_options_absent(tmp_path):
    path = _write(tmp_path, """
        connection: {}
        layer:
          url: "http://x/0"
        output:
          directory: "./out"
          group_template: "{S}"
          filename_template: "{OBJECTID}"
    """)
    cfg, profile = load_config(path)
    assert profile is None
    assert cfg.where == "1=1"
    assert cfg.incremental is False
    assert cfg.retries == 3


def test_overrides_applied(tmp_path):
    path = _write(tmp_path, """
        connection:
          profile: prof1
        layer:
          item_id: "abc"
        output:
          directory: "./out"
          group_template: "{S}"
          filename_template: "{OBJECTID}"
    """)
    cfg, _ = load_config(path, overrides={
        "where": "OBJECTID < 100", "directory": "/tmp/o", "incremental": True})
    assert cfg.where == "OBJECTID < 100"
    assert cfg.directory == "/tmp/o"
    assert cfg.incremental is True


def test_none_overrides_ignored(tmp_path):
    path = _write(tmp_path, """
        connection:
          profile: prof1
        layer:
          item_id: "abc"
          where: "keep"
        output:
          directory: "./out"
          group_template: "{S}"
          filename_template: "{OBJECTID}"
    """)
    cfg, _ = load_config(path, overrides={
        "where": None, "directory": None, "incremental": None})
    assert cfg.where == "keep"
    assert cfg.directory == "./out"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_config_loader.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'autogis.adapters.config_loader'`

- [ ] **Step 4: Write minimal implementation** in `autogis/adapters/config_loader.py`

```python
import yaml
from autogis.core.models import HarvestConfig

_OVERRIDE_KEYS = ("where", "directory", "incremental")


def load_config(path, overrides=None):
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    connection = data.get("connection") or {}
    layer = data.get("layer") or {}
    output = data.get("output") or {}
    options = data.get("options") or {}

    profile = connection.get("profile")

    fields = dict(
        item_id=layer.get("item_id"),
        url=layer.get("url"),
        where=layer.get("where", "1=1"),
        directory=output["directory"],
        group_template=output["group_template"],
        filename_template=output["filename_template"],
        incremental=options.get("incremental", False),
        skip_existing=options.get("skip_existing", True),
        retries=options.get("retries", 3),
        backoff_seconds=options.get("backoff_seconds", 2),
    )

    if overrides:
        for key in _OVERRIDE_KEYS:
            if overrides.get(key) is not None:
                fields[key] = overrides[key]

    if fields["where"] is None:
        fields["where"] = "1=1"

    return HarvestConfig(**fields), profile
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_config_loader.py -v`
Expected: PASS (4 passed)

- [ ] **Step 6: Commit**

```bash
git add autogis/adapters/config_loader.py autogis/config/inspection-job.example.yaml tests/test_config_loader.py
git commit -m "feat: add YAML config loader with CLI override merge"
```

---

### Task 9: CLI adapter wiring it all together

**Files:**
- Create: `autogis/adapters/cli.py`
- Create: `tests/test_cli.py`

**Interfaces:**
- Consumes: `load_config` (config_loader), `build_gis_from_env` (gis_session),
  `harvest` (harvester).
- Produces:
  - `autogis.adapters.cli.main` — a `click` command. Options:
    `--config PATH` (required), `--where TEXT`, `--out PATH` (maps to directory
    override), `--incremental/--no-incremental` (default None — i.e. use a flag
    that only overrides when passed). Builds overrides dict, loads config, builds
    GIS via `build_gis_from_env(profile)`, calls `harvest`, prints the summary
    line `Downloaded: X  Skipped: Y  Failed: Z`.
  - For testability, factor the body into
    `run(config_path, where, out, incremental, *, gis_builder, harvest_fn, load_fn) -> RunSummary`
    so tests inject fakes; `main` calls `run` with the real functions.

**Note on the `--incremental` tri-state:** use `click.option("--incremental/--no-incremental", default=None)` so that when neither flag is passed the override is None (config value wins), and passing either flag overrides.

- [ ] **Step 1: Write the failing test** in `tests/test_cli.py`

```python
from autogis.core.models import HarvestConfig, RunSummary
from autogis.adapters import cli


def test_run_wires_components(tmp_path, capsys):
    captured = {}

    def fake_load(path, overrides=None):
        captured["overrides"] = overrides
        cfg = HarvestConfig(item_id="abc", url=None, directory=str(tmp_path),
                            group_template="{S}", filename_template="{OBJECTID}")
        return cfg, "prof1"

    def fake_gis_builder(profile):
        captured["profile"] = profile
        return "GIS_OBJ"

    def fake_harvest(gis, cfg):
        captured["gis"] = gis
        captured["cfg"] = cfg
        s = RunSummary(downloaded=3, skipped=1, failed=2)
        return s

    summary = cli.run("job.yaml", where="W", out="/o", incremental=True,
                      gis_builder=fake_gis_builder, harvest_fn=fake_harvest,
                      load_fn=fake_load)

    assert captured["overrides"] == {"where": "W", "directory": "/o",
                                     "incremental": True}
    assert captured["profile"] == "prof1"
    assert captured["gis"] == "GIS_OBJ"
    assert summary.downloaded == 3
    out = capsys.readouterr().out
    assert "Downloaded: 3" in out
    assert "Skipped: 1" in out
    assert "Failed: 2" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'autogis.adapters.cli'`

- [ ] **Step 3: Write minimal implementation** in `autogis/adapters/cli.py`

```python
import click

from autogis.adapters.config_loader import load_config
from autogis.core.gis_session import build_gis_from_env
from autogis.core.harvester import harvest


def run(config_path, where, out, incremental, *,
        gis_builder, harvest_fn, load_fn):
    overrides = {"where": where, "directory": out, "incremental": incremental}
    config, profile = load_fn(config_path, overrides=overrides)
    gis = gis_builder(profile)
    summary = harvest_fn(gis, config)
    click.echo(
        f"Downloaded: {summary.downloaded}  "
        f"Skipped: {summary.skipped}  Failed: {summary.failed}")
    return summary


@click.command()
@click.option("--config", "config_path", required=True,
              type=click.Path(exists=True), help="Path to harvest job YAML.")
@click.option("--where", default=None, help="Override the attribute where clause.")
@click.option("--out", default=None, help="Override the output directory.")
@click.option("--incremental/--no-incremental", default=None,
              help="Override incremental mode.")
def main(config_path, where, out, incremental):
    run(config_path, where, out, incremental,
        gis_builder=build_gis_from_env,
        harvest_fn=harvest,
        load_fn=load_config)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Run the full suite**

Run: `pytest -v`
Expected: PASS (all tests green across Tasks 1-9)

- [ ] **Step 6: Commit**

```bash
git add autogis/adapters/cli.py tests/test_cli.py
git commit -m "feat: add CLI adapter wiring config, auth, and harvester"
```

---

### Task 10: README usage documentation

**Files:**
- Modify: `README.md` (currently a stub)

**Interfaces:**
- Consumes: nothing (documentation only).
- Produces: usage docs. No tests (pure docs); verification is manual review.

- [ ] **Step 1: Replace `README.md` contents**

```markdown
# AutoGIS

Automation tools for ArcGIS Pro and ArcGIS Online / Survey123.

## Attachment Harvester

Bulk-download photos/attachments from a feature layer for field-inspection workflows.

### Install

```bash
pip install -e .
```

### Authenticate

Primary: create a stored ArcGIS profile once (cached in your OS keyring):

```python
from arcgis.gis import GIS
GIS(profile="my_agol_profile", username="you", password="…")  # one-time setup
```

Fallback: set environment variables instead of a profile:

```bash
export AGOL_USER=you
export AGOL_PASS=secret
```

Never put passwords in the config file or on the command line.

### Configure a harvest job

Copy `autogis/config/inspection-job.example.yaml` and edit it. Key fields:

- `connection.profile` — stored profile name (or leave null to use env vars)
- `layer.item_id` or `layer.url` — the feature layer to harvest
- `layer.where` — optional attribute filter (default `1=1`)
- `output.directory` — where files land
- `output.group_template` — subfolder per attribute, e.g. `{Status}`
- `output.filename_template` — must include a feature id, e.g. `{InspectionID}_{OBJECTID}_{name}`
- `options.incremental` — only fetch features edited since the last run (requires editor tracking)

### Run

```bash
autogis-harvest --config my-job.yaml
# overrides:
autogis-harvest --config my-job.yaml --where "Status = 'Complete'" --out ./batch --incremental
```

Each run writes the photos plus `manifest.csv` and `manifest.json` into the output
directory, and prints `Downloaded: X  Skipped: Y  Failed: Z`. Re-running skips files
already on disk, so failed downloads are retried cleanly on the next run.

## Development

```bash
pip install -e ".[dev]"
pytest -v
```
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add AutoGIS attachment harvester usage guide"
```

---

## Self-Review

**Spec coverage:**
- Core/adapter architecture, core never imports arcpy → Tasks 1-9 (core in `autogis/core`, CLI in `autogis/adapters`); harvester wraps `FeatureLayer` import defensively. ✓
- Auth: stored profile primary, env-var username/password fallback → Task 7. ✓
- Layer resolve by item_id or url + attachments-enabled check → Task 6 `resolve_layer`. ✓
- Where clause filter (default 1=1) → models default (Task 1), loader (Task 8), harvester (Task 6). ✓
- Attribute-grouped folders + configurable templates + feature-id collision avoidance → Tasks 2 & 6. ✓
- Missing/null field → `_unknown`; filesystem sanitization → Task 2. ✓
- Skip-existing default → Task 6. ✓
- Incremental by EditDate with state file + editor-tracking guard → Tasks 4 & 6. ✓
- Retry+backoff, continue on failure, never kill run → Tasks 5 & 6. ✓
- CSV + JSON manifest per run → Tasks 3 & 6. ✓
- Config file + CLI overrides, secrets excluded → Tasks 8 & 9. ✓
- Setup errors fail fast before downloads → Task 6 (`resolve_layer`, `_effective_where`). ✓
- Unit tests mock arcgis; one integration-style full-loop test incl. forced failure → Task 6 `test_harvest_records_failure_and_continues`. ✓
- Summary line output → Task 9. ✓

**Placeholder scan:** No TBD/TODO; every code step has complete code. ✓

**Type consistency:** `HarvestConfig`/`AttachmentResult`/`RunSummary` field names consistent across Tasks 1, 3, 6, 8, 9. `download_one` signature consistent between Tasks 5 and 6. `harvest`/`resolve_layer` signatures consistent between Tasks 6 and 9. `load_config` returns `(HarvestConfig, profile)` consistently used in Tasks 8 and 9. ✓

Plan is internally consistent and covers the spec.
