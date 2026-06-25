# Phase B — ReconcileSampleLocations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Prerequisite:** Phase A (`docs/superpowers/plans/2026-06-24-phase-a-config-integrity.md`) must be merged first — Task 5 reuses the `_render_qa(qa, report, fail_on)` helper added to `cli.py` in Phase A.

**Goal:** Add `ReconcileSampleLocations` — a standalone, read-only pre-flight tool that reports whether a workbook's location IDs match the monitoring-well feature class, with fuzzy suggestions for typos, before import.

**Architecture:** A headless core module `core/envmon/reconcile_locations.py` with a pure `reconcile(workbook_ids, well_ids, threshold)` algorithm (stdlib `difflib`, no new deps), plus helpers to extract workbook IDs through a `ProfileWorkbookReader` and to read well IDs from CSV. A new headless `envmon reconcile-locations` CLI command serves the `--wells-csv` path; the production `--gdb` path is wrapped by a new `.pyt` tool that reads well IDs via arcpy `SearchCursor` and calls the same core.

**Tech Stack:** Python 3, `click`, `openpyxl` (already present), stdlib `difflib`/`csv`, `pytest`. The core and CLI import no arcpy; only the `.pyt` tool touches arcpy.

## Global Constraints

- `core/` and `adapters/cli.py` import with neither `arcpy` nor `arcgis` present (ADR-002). The `reconcile` algorithm never imports arcpy.
- Reuse `core/common/qa.py` (`QACollector`, `QARecord`, `SEV_ERROR`, `SEV_WARNING`, `SEV_INFO`).
- ID normalization for matching: uppercase, strip, then remove all `-`, `_`, and space characters. Used for both exact-match and fuzzy comparison.
- Fuzzy matching: `difflib.SequenceMatcher(None, norm_a, norm_b).ratio()`; default threshold `0.8`. No new dependency.
- Severities: unmatched workbook ID **with** a suggestion ≥ threshold → WARNING (`location_id_typo`); unmatched workbook ID **without** suggestion → ERROR (`location_id_unmatched`); well ID present in layer but absent from workbook → INFO (`well_not_sampled`).
- Read-only: the tool suggests, never modifies the workbook or the feature class.
- `.pyt` files are never imported by the test suite (top-level `import arcpy`). The `.pyt` task is verified structurally, not by unit test.
- Tests headless under `tests/envmon/`; run `python -m pytest -q`.
- Exit codes mirror Phase A: `0` PASS / `1` FAIL via `QACollector.status`, `--fail-on error|warning` (default `error`).

---

### Task 1: Normalization + core `reconcile()`

**Files:**
- Create: `autogis/core/envmon/reconcile_locations.py`
- Test: `tests/envmon/test_reconcile_locations.py`

**Interfaces:**
- Produces:
  - `normalize_id(value: str) -> str`
  - `@dataclass Suggestion(workbook_id: str, suggestion: Optional[str], score: float)`
  - `@dataclass ReconcileResult(matches: list[str], unmatched_workbook: list[Suggestion], unmatched_wells: list[str])`
  - `reconcile(workbook_ids: list[str], well_ids: list[str], threshold: float = 0.8) -> ReconcileResult`

- [ ] **Step 1: Write the failing test**

```python
# tests/envmon/test_reconcile_locations.py
from autogis.core.envmon.reconcile_locations import normalize_id, reconcile


def test_normalize_id_collapses_separators_and_case():
    assert normalize_id(" mw-07a ") == "MW07A"
    assert normalize_id("MW_07A") == "MW07A"


def test_reconcile_exact_typo_nomatch_and_extra_well():
    workbook = ["MW-1", "MW-7A", "ZZZ-99"]
    wells = ["MW-1", "MW-07A", "MW-2"]
    result = reconcile(workbook, wells, threshold=0.8)

    # MW-1 matches exactly (after normalization both are MW1)
    assert "MW-1" in result.matches
    # MW-7A -> suggestion MW-07A (close), score >= 0.8
    typo = {s.workbook_id: s for s in result.unmatched_workbook}["MW-7A"]
    assert typo.suggestion == "MW-07A" and typo.score >= 0.8
    # ZZZ-99 -> no suggestion above threshold
    nomatch = {s.workbook_id: s for s in result.unmatched_workbook}["ZZZ-99"]
    assert nomatch.suggestion is None
    # MW-2 is a well never sampled in the workbook
    assert "MW-2" in result.unmatched_wells


def test_reconcile_threshold_boundary_excludes_weak_suggestion():
    result = reconcile(["AB"], ["XY"], threshold=0.8)
    assert result.unmatched_workbook[0].suggestion is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/envmon/test_reconcile_locations.py -q`
Expected: FAIL — module `reconcile_locations` not found.

- [ ] **Step 3: Write minimal implementation**

```python
# autogis/core/envmon/reconcile_locations.py
"""ReconcileSampleLocations — pre-flight check that workbook location IDs match
the monitoring-well feature class (headless core, arcpy-free).

The core compares two lists of IDs and reports exact matches, unmatched
workbook IDs (with a fuzzy suggestion where one scores above threshold), and
wells that were never sampled. Read-only: it suggests, never modifies.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import List, Optional

_SEP = re.compile(r"[-_ ]+")


def normalize_id(value: str) -> str:
    return _SEP.sub("", str(value).strip().upper())


@dataclass
class Suggestion:
    workbook_id: str
    suggestion: Optional[str]
    score: float


@dataclass
class ReconcileResult:
    matches: List[str] = field(default_factory=list)
    unmatched_workbook: List[Suggestion] = field(default_factory=list)
    unmatched_wells: List[str] = field(default_factory=list)


def _best_match(target_norm: str, candidates: List[str]):
    best, score = None, 0.0
    for cand in candidates:
        ratio = difflib.SequenceMatcher(None, target_norm,
                                        normalize_id(cand)).ratio()
        if ratio > score:
            best, score = cand, ratio
    return best, score


def reconcile(workbook_ids: List[str], well_ids: List[str],
              threshold: float = 0.8) -> ReconcileResult:
    result = ReconcileResult()
    well_norms = {normalize_id(w) for w in well_ids}
    workbook_norms = set()

    seen = set()
    for wb in workbook_ids:
        nb = normalize_id(wb)
        workbook_norms.add(nb)
        if nb in seen:
            continue
        seen.add(nb)
        if nb in well_norms:
            result.matches.append(wb)
            continue
        best, score = _best_match(nb, well_ids)
        result.unmatched_workbook.append(
            Suggestion(workbook_id=wb,
                       suggestion=best if score >= threshold else None,
                       score=round(score, 3)))

    for w in well_ids:
        if normalize_id(w) not in workbook_norms:
            result.unmatched_wells.append(w)
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/envmon/test_reconcile_locations.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add autogis/core/envmon/reconcile_locations.py tests/envmon/test_reconcile_locations.py
git commit -m "feat(envmon): reconcile-locations core (normalize + fuzzy reconcile)"
```

---

### Task 2: `reconcile_to_qa()` — result → QARecords

**Files:**
- Modify: `autogis/core/envmon/reconcile_locations.py`
- Test: `tests/envmon/test_reconcile_locations.py`

**Interfaces:**
- Consumes: `ReconcileResult` (Task 1); `QACollector`, `QARecord`.
- Produces: `reconcile_to_qa(result: ReconcileResult) -> QACollector`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/envmon/test_reconcile_locations.py
from autogis.core.common.qa import SEV_ERROR, SEV_INFO, SEV_WARNING
from autogis.core.envmon.reconcile_locations import reconcile_to_qa


def test_reconcile_to_qa_severities():
    result = reconcile(["MW-1", "MW-7A", "ZZZ-99"], ["MW-1", "MW-07A", "MW-2"],
                       threshold=0.8)
    qa = reconcile_to_qa(result)
    cats = {(r.severity, r.category) for r in qa.records}
    assert (SEV_WARNING, "location_id_typo") in cats        # MW-7A -> MW-07A
    assert (SEV_ERROR, "location_id_unmatched") in cats      # ZZZ-99
    assert (SEV_INFO, "well_not_sampled") in cats            # MW-2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/envmon/test_reconcile_locations.py -k to_qa -q`
Expected: FAIL — `reconcile_to_qa` undefined.

- [ ] **Step 3: Write minimal implementation**

```python
# append to autogis/core/envmon/reconcile_locations.py
from ..common.qa import QACollector, QARecord, SEV_ERROR, SEV_INFO, SEV_WARNING


def reconcile_to_qa(result: ReconcileResult) -> QACollector:
    qa = QACollector()
    for s in result.unmatched_workbook:
        if s.suggestion is not None:
            qa.add(QARecord(
                severity=SEV_WARNING, category="location_id_typo",
                message=(f"workbook location {s.workbook_id!r} has no exact "
                         f"well match"),
                recommended_action=(f"did you mean {s.suggestion!r}? "
                                    f"(similarity {s.score:.2f})"),
                location_id=str(s.workbook_id)))
        else:
            qa.add(QARecord(
                severity=SEV_ERROR, category="location_id_unmatched",
                message=(f"workbook location {s.workbook_id!r} matches no well "
                         f"(best similarity {s.score:.2f})"),
                recommended_action="add the well to the feature class or fix the "
                                   "workbook ID",
                location_id=str(s.workbook_id)))
    for w in result.unmatched_wells:
        qa.add(QARecord(severity=SEV_INFO, category="well_not_sampled",
                        message=f"well {w!r} has no sample in the workbook",
                        location_id=str(w)))
    qa.add(QARecord(
        severity=SEV_INFO, category="reconcile_complete",
        message=(f"Reconcile finished: {len(result.matches)} matched, "
                 f"{len(result.unmatched_workbook)} unmatched workbook ID(s), "
                 f"{len(result.unmatched_wells)} unsampled well(s).")))
    return qa
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/envmon/test_reconcile_locations.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add autogis/core/envmon/reconcile_locations.py tests/envmon/test_reconcile_locations.py
git commit -m "feat(envmon): map reconcile result to QA records"
```

---

### Task 3: Extract workbook location IDs via the parser profile

**Files:**
- Modify: `autogis/core/envmon/reconcile_locations.py`
- Test: `tests/envmon/test_reconcile_locations.py`

**Interfaces:**
- Consumes: any `WorkbookReaderProtocol` (`ProfileWorkbookReader` or test `InMemoryWorkbookReader`); `ParserProfile`/`SheetProfile`.
- Produces: `extract_location_ids(reader, profile) -> list[str]` — ordered, de-duplicated location IDs read from each sheet's `id_column` (falling back to `sample_id_column`).

- [ ] **Step 1: Write the failing test**

```python
# append to tests/envmon/test_reconcile_locations.py
from autogis.core.common.config import ParserProfile, SheetProfile
from autogis.core.envmon.reconcile_locations import extract_location_ids
from tests.envmon.conftest import InMemoryWorkbookReader


def test_extract_location_ids_reads_id_column_dedup():
    sp = SheetProfile.from_dict({"sheet_name": "S", "data_type": "METALS",
                                 "data_start_row": 2, "id_column": "A"})
    profile = ParserProfile(profile_id="P", data={}, sheets={"S": sp})
    cells = {("S", 2, 1): "MW-1", ("S", 3, 1): "MW-2", ("S", 4, 1): "MW-1"}
    reader = InMemoryWorkbookReader(cells)
    assert extract_location_ids(reader, profile) == ["MW-1", "MW-2"]
```

> Note: `InMemoryWorkbookReader` lives in `tests/envmon/conftest.py`; importing it directly (rather than via fixture) is fine for a focused unit test.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/envmon/test_reconcile_locations.py -k extract -q`
Expected: FAIL — `extract_location_ids` undefined.

- [ ] **Step 3: Write minimal implementation**

```python
# append to autogis/core/envmon/reconcile_locations.py
def extract_location_ids(reader, profile) -> List[str]:
    """Ordered, de-duplicated location IDs from every sheet's id_column."""
    ordered: List[str] = []
    seen = set()
    for sheet_profile in profile.sheets.values():
        col = sheet_profile.id_column or sheet_profile.sample_id_column
        if not col:
            continue
        if not reader.require_sheet(sheet_profile):
            continue
        for row in reader.iter_data_rows(sheet_profile):
            text = reader.cell(sheet_profile.sheet_name, row, col).raw_text.strip()
            if text and text not in seen:
                seen.add(text)
                ordered.append(text)
    return ordered
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/envmon/test_reconcile_locations.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add autogis/core/envmon/reconcile_locations.py tests/envmon/test_reconcile_locations.py
git commit -m "feat(envmon): extract workbook location IDs through parser profile"
```

---

### Task 4: Read well IDs from CSV

**Files:**
- Modify: `autogis/core/envmon/reconcile_locations.py`
- Test: `tests/envmon/test_reconcile_locations.py`

**Interfaces:**
- Produces: `read_well_ids_csv(path: Path) -> list[str]` — if the header row contains a `LocationID` column (case-insensitive), read that; otherwise read the first column. Skips blanks.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/envmon/test_reconcile_locations.py
from autogis.core.envmon.reconcile_locations import read_well_ids_csv


def test_read_well_ids_csv_named_column(tmp_path):
    p = tmp_path / "wells.csv"
    p.write_text("SiteID,LocationID\nH281,MW-1\nH281,MW-2\n", encoding="utf-8")
    assert read_well_ids_csv(p) == ["MW-1", "MW-2"]


def test_read_well_ids_csv_first_column_fallback(tmp_path):
    p = tmp_path / "wells.csv"
    p.write_text("MW-1\nMW-2\n\n", encoding="utf-8")
    assert read_well_ids_csv(p) == ["MW-1", "MW-2"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/envmon/test_reconcile_locations.py -k csv -q`
Expected: FAIL — `read_well_ids_csv` undefined.

- [ ] **Step 3: Write minimal implementation**

```python
# append to autogis/core/envmon/reconcile_locations.py
import csv
from pathlib import Path


def read_well_ids_csv(path: Path) -> List[str]:
    rows = list(csv.reader(Path(path).open(newline="", encoding="utf-8")))
    if not rows:
        return []
    header = [h.strip() for h in rows[0]]
    loc_idx = next((i for i, h in enumerate(header)
                    if h.lower() == "locationid"), None)
    if loc_idx is not None:
        data_rows, idx = rows[1:], loc_idx
    else:
        data_rows, idx = rows, 0          # no header match: treat all as data, col 0
    out: List[str] = []
    for r in data_rows:
        if len(r) > idx and r[idx].strip():
            out.append(r[idx].strip())
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/envmon/test_reconcile_locations.py -q`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add autogis/core/envmon/reconcile_locations.py tests/envmon/test_reconcile_locations.py
git commit -m "feat(envmon): read well IDs from CSV (named column or first column)"
```

---

### Task 5: `reconcile-locations` CLI command

**Files:**
- Modify: `autogis/adapters/cli.py` (headless section, after the Phase A `manage-analyte-dict` command)
- Test: `tests/envmon/test_cli_reconcile_locations.py`

**Interfaces:**
- Consumes: `ParserProfile.load`, `ProfileWorkbookReader`, `extract_location_ids`, `read_well_ids_csv`, `reconcile`, `reconcile_to_qa`; `_render_qa` (Phase A Task 5); `_guard` (existing).
- Produces: CLI `autogis envmon reconcile-locations SITE WORKBOOK --profile P [--wells-csv W | --gdb] [--threshold 0.8] [--report OUT] [--fail-on error|warning]`. The `--wells-csv` path is fully headless; `--gdb` raises a clean redirect to the `.pyt` tool (mirrors Tools 2–8).

- [ ] **Step 1: Write the failing test**

```python
# tests/envmon/test_cli_reconcile_locations.py
import openpyxl
import yaml
from click.testing import CliRunner

from autogis.adapters.cli import autogis


def _profile(tmp_path):
    data = {"profile_id": "P", "sheets": [
        {"sheet_name": "S", "data_type": "METALS", "data_start_row": 2,
         "id_column": "A"}]}
    p = tmp_path / "profile.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return str(p)


def _workbook(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "S"
    ws["A1"] = "Well ID"
    ws["A2"] = "MW-1"
    ws["A3"] = "MW-7A"   # typo vs MW-07A
    p = tmp_path / "wb.xlsx"
    wb.save(p)
    return str(p)


def _site(tmp_path):
    p = tmp_path / "site.yaml"
    p.write_text(yaml.safe_dump({"site_id": "H281",
                                 "monitoring_wells_fc": "MonitoringWells"}),
                 encoding="utf-8")
    return str(p)


def test_reconcile_locations_cli_reports_typo_and_unmatched(tmp_path):
    wells = tmp_path / "wells.csv"
    wells.write_text("LocationID\nMW-1\nMW-07A\n", encoding="utf-8")
    r = CliRunner().invoke(autogis, [
        "envmon", "reconcile-locations", _site(tmp_path), _workbook(tmp_path),
        "--profile", _profile(tmp_path), "--wells-csv", str(wells)])
    # MW-7A -> WARNING typo only; no ERROR -> default --fail-on error => PASS (exit 0)
    assert r.exit_code == 0
    assert "location_id_typo" in r.output


def test_reconcile_locations_cli_gdb_path_redirects(tmp_path):
    r = CliRunner().invoke(autogis, [
        "envmon", "reconcile-locations", _site(tmp_path), _workbook(tmp_path),
        "--profile", _profile(tmp_path), "--gdb"])
    assert r.exit_code != 0
    assert "ArcGIS Pro" in r.output or "toolbox" in r.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/envmon/test_cli_reconcile_locations.py -q`
Expected: FAIL — no such command `reconcile-locations`.

- [ ] **Step 3: Write minimal implementation**

```python
# autogis/adapters/cli.py — add after manage_analyte_dict_cmd
@envmon.command("reconcile-locations")
@click.argument("site_config", type=click.Path(exists=True))
@click.argument("workbook", type=click.Path(exists=True))
@click.option("--profile", "profile_path", required=True,
              type=click.Path(exists=True), help="Parser profile for the workbook.")
@click.option("--wells-csv", default=None, type=click.Path(exists=True),
              help="CSV of well IDs (headless). Mutually exclusive with --gdb.")
@click.option("--gdb", is_flag=True, default=False,
              help="Read wells from the site GDB (ArcGIS Pro only; use the .pyt).")
@click.option("--threshold", type=float, default=0.8, show_default=True)
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error")
def reconcile_locations_cmd(site_config, workbook, profile_path, wells_csv, gdb,
                            threshold, report, fail_on):
    """Tool: pre-flight check that workbook location IDs match the well layer."""
    from autogis.core.common.config import ParserProfile
    from autogis.core.envmon.excel_profile_reader import ProfileWorkbookReader
    from autogis.core.envmon.reconcile_locations import (
        extract_location_ids, read_well_ids_csv, reconcile, reconcile_to_qa)

    if gdb:
        _guard("reconcile-locations")
        raise click.ClickException(
            "reconcile-locations --gdb runs inside ArcGIS Pro only. Use the "
            "ReconcileSampleLocations tool in the .pyt toolbox, or pass "
            "--wells-csv for a headless check.")
    if not wells_csv:
        raise click.ClickException("provide --wells-csv PATH (headless) or "
                                   "--gdb (ArcGIS Pro).")

    profile = ParserProfile.load(Path(profile_path))
    reader = ProfileWorkbookReader(Path(workbook), profile)
    workbook_ids = extract_location_ids(reader, profile)
    well_ids = read_well_ids_csv(Path(wells_csv))

    result = reconcile(workbook_ids, well_ids, threshold=threshold)
    qa = reconcile_to_qa(result)
    _render_qa(qa, report, fail_on)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/envmon/test_cli_reconcile_locations.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add autogis/adapters/cli.py tests/envmon/test_cli_reconcile_locations.py
git commit -m "feat(cli): envmon reconcile-locations command (headless --wells-csv path)"
```

---

### Task 6: `.pyt` ReconcileSampleLocations tool (production `--gdb` path)

**Files:**
- Modify: `autogis/adapters/toolbox.pyt` (add tool class + register in `Toolbox.tools`)

**Interfaces:**
- Consumes: `ParserProfile`, `load_config`, `QACollector`; `reconcile`, `reconcile_to_qa`, `extract_location_ids`; `require_runtime`; arcpy `SearchCursor`.
- Produces: a `ReconcileSampleLocations` `.pyt` tool reading well IDs from `monitoring_wells_fc.LocationID` in the site GDB.

> Not unit-tested: `.pyt` imports `arcpy` at module top level and is excluded from the suite. Verify structurally (Step 3) and by an import-smoke check of the core call path (Step 2).

- [ ] **Step 1: Add the tool class and register it**

Add to `autogis/adapters/toolbox.pyt`, in the headless/LOCAL tool section, and add `ReconcileSampleLocations` to the `Toolbox.__init__` `self.tools` list (after `ValidateDatabase`):

```python
class ReconcileSampleLocations(object):
    """Pre-flight: do workbook location IDs match the well feature class?

    Reads well LocationIDs from the site GDB via arcpy, extracts workbook
    location IDs through the parser profile (openpyxl), and reports matches /
    typos / unsampled wells. Read-only.
    """
    def __init__(self):
        self.label = "Reconcile Sample Locations"
        self.description = ("Compare workbook location IDs against the "
                            "monitoring-well feature class (read-only).")
        self.canRunInBackground = False

    def getParameterInfo(self):
        return [
            _param("site_config", "Site config (YAML/JSON)", "DEFile"),
            _param("workbook", "Workbook (.xlsx)", "DEFile"),
            _param("profile", "Parser profile (YAML/JSON)", "DEFile"),
            _param("gdb", "Geodatabase", "DEWorkspace"),
            _param("threshold", "Fuzzy match threshold", "GPDouble",
                   required=False, default=0.8),
        ]

    def execute(self, parameters, messages):
        from autogis.runtime.sessions import arcpy_env
        from autogis.core.envmon.reconcile_locations import (
            extract_location_ids, reconcile, reconcile_to_qa)
        from autogis.core.envmon.excel_profile_reader import ProfileWorkbookReader

        p = {q.name: q for q in parameters}
        site = load_config(Path(p["site_config"].valueAsText))
        well_fc = site.get("monitoring_wells_fc", "MonitoringWells")
        gdb = Path(p["gdb"].valueAsText)
        threshold = float(p["threshold"].value or 0.8)

        profile = ParserProfile.load(Path(p["profile"].valueAsText))
        reader = ProfileWorkbookReader(Path(p["workbook"].valueAsText), profile)
        workbook_ids = extract_location_ids(reader, profile)

        arcpy = arcpy_env()
        well_ids = []
        with arcpy.da.SearchCursor(str(gdb / well_fc), ["LocationID"]) as cur:
            for (loc,) in cur:
                if loc is not None:
                    well_ids.append(str(loc))

        result = reconcile(workbook_ids, well_ids, threshold=threshold)
        qa = reconcile_to_qa(result)
        messages.addMessage(
            f"{len(result.matches)} matched, "
            f"{len(result.unmatched_workbook)} unmatched workbook ID(s), "
            f"{len(result.unmatched_wells)} unsampled well(s).")
        _msg(messages, qa)
```

- [ ] **Step 2: Import-smoke the core call path (no arcpy)**

Confirm the non-arcpy pieces the tool relies on import and run headlessly:

Run: `python -c "from autogis.core.envmon.reconcile_locations import extract_location_ids, reconcile, reconcile_to_qa; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 3: Structurally verify the `.pyt` registration**

Run: `python -c "import ast,io; src=open('autogis/adapters/toolbox.pyt',encoding='utf-8').read(); t=ast.parse(src); names=[n.name for n in ast.walk(t) if isinstance(n, ast.ClassDef)]; assert 'ReconcileSampleLocations' in names, names; assert 'ReconcileSampleLocations' in src.split('self.tools')[1].split(']')[0]; print('registered ok')"`
Expected: prints `registered ok` (class exists and appears in the `self.tools` list).

- [ ] **Step 4: Run the full suite + commit**

```bash
python -m pytest -q
git add autogis/adapters/toolbox.pyt
git commit -m "feat(pyt): ReconcileSampleLocations toolbox tool (GDB well-ID read)"
```

Expected: full suite green (Phase B adds ~9 tests; `.pyt` not collected).

---

## Self-Review

**Spec coverage:**
- Standalone pre-flight, read-only → Tasks 1–6 (separate command + `.pyt`; never modifies). ✓
- Headless core `reconcile(workbook_ids, well_ids, threshold)` → Task 1. ✓
- Normalization (uppercase/strip/collapse `-_<space>`) → `normalize_id` Task 1. ✓
- `difflib` fuzzy, threshold 0.8, no new dep → Task 1. ✓
- Severities (typo WARNING / unmatched ERROR / unsampled INFO) → Task 2. ✓
- Workbook IDs via parser profile; well IDs via `--wells-csv` (headless) or `--gdb` (arcpy) → Tasks 3, 4, 5, 6. ✓
- `.pyt` wraps the `--gdb` path; algorithm stays arcpy-free → Task 6. ✓
- Report contract + exit codes + `--fail-on` (reused `_render_qa`) → Task 5. ✓

**Placeholder scan:** Every code step is complete. Task 6 is explicitly structural (documented) because `.pyt` is outside the test suite by codebase convention; its core path is import-smoked in Step 2 and registration is AST-checked in Step 3.

**Type consistency:** `reconcile(...) -> ReconcileResult`; `reconcile_to_qa(ReconcileResult) -> QACollector`; `extract_location_ids(reader, profile) -> list[str]`; `read_well_ids_csv(path) -> list[str]`. CLI and `.pyt` consume exactly these. `_render_qa(qa, report, fail_on)` matches the Phase A signature. `ProfileWorkbookReader(path, profile)` and `.raw_text` match `excel_profile_reader.py`. ✓

**Cross-phase dependency:** Task 5 requires `_render_qa` from Phase A Task 5 — called out in the header and Global Constraints.
