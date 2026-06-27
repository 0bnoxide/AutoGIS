# ManageScreeningLevels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Implement `ManageScreeningLevels` — a headless read-only validator for
`screening_levels.yaml`. See spec: `docs/superpowers/specs/2026-06-27-manage-screening-levels-design.md`.

**Architecture:**
- New: `autogis/core/envmon/manage_screening_levels.py`
- Modify: `autogis/adapters/cli.py` — add `manage-screening-levels` command
- New: `tests/envmon/test_manage_screening_levels.py`

## Global Constraints

- Branch: `feat/gdb-schema-upgrade`
- Arcpy-free.
- Reuse `load_screening_levels()` from `core/common/config.py` for the YAML load.
- Run tests with `python -m pytest -q`.

---

### Task 1: Core module + tests

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_manage_screening_levels.py`:

```python
from pathlib import Path
import pytest

from autogis.core.envmon.manage_screening_levels import (
    ScreeningEntry, check_screening_levels, load_screening_entries,
)

# Minimal valid YAML for tests
_VALID_YAML = """\
screening_levels:
  GW:
    Benzene: {value: 5.0, units: ug/L, source: "MDEQ RBSL 2024"}
  SOIL:
    Benzene: {value: 0.1, units: mg/kg, source: "MDEQ RBSL 2024"}
"""

_NULL_YAML = """\
screening_levels:
  GW:
    Benzene: {value: null, units: ug/L, source: "_TODO MDEQ RBSL"}
"""

_BAD_YAML = """\
screening_levels:
  GW:
    Benzene: {value: "not-a-number", source: "MDEQ"}
"""

_ANALYTES_YAML = """\
Benzene:
  canonical_name: Benzene
  default_units_by_matrix: {GW: ug/L, SOIL: mg/kg}
Toluene:
  canonical_name: Toluene
  default_units_by_matrix: {GW: ug/L}
"""


def test_valid_entry_passes(tmp_path):
    f = tmp_path / "sl.yaml"
    f.write_text(_VALID_YAML, encoding="utf-8")
    qa = check_screening_levels(f)
    assert qa.counts_by_severity().get("ERROR", 0) == 0


def test_null_value_warns(tmp_path):
    f = tmp_path / "sl.yaml"
    f.write_text(_NULL_YAML, encoding="utf-8")
    qa = check_screening_levels(f)
    cats = [r.category for r in qa.records]
    assert "null_value" in cats


def test_todo_source_warns(tmp_path):
    f = tmp_path / "sl.yaml"
    f.write_text(_NULL_YAML, encoding="utf-8")
    qa = check_screening_levels(f)
    assert any("placeholder_source" == r.category for r in qa.records)


def test_missing_units_errors(tmp_path):
    f = tmp_path / "sl.yaml"
    f.write_text(_BAD_YAML, encoding="utf-8")
    qa = check_screening_levels(f)
    cats = [r.category for r in qa.records]
    assert "missing_entry_key" in cats


def test_load_screening_entries_flat(tmp_path):
    f = tmp_path / "sl.yaml"
    f.write_text(_VALID_YAML, encoding="utf-8")
    entries = load_screening_entries(f)
    assert len(entries) == 2
    analytes = {e.analyte for e in entries}
    assert "Benzene" in analytes


def test_analyte_coverage_check_flags_missing(tmp_path):
    sl = tmp_path / "sl.yaml"
    sl.write_text(_VALID_YAML, encoding="utf-8")   # only Benzene, not Toluene
    al = tmp_path / "an.yaml"
    al.write_text(_ANALYTES_YAML, encoding="utf-8")
    qa = check_screening_levels(sl, analytes_path=al)
    # Toluene is in analytes dict but not in screening levels → warning
    assert any(r.category == "analyte_not_covered" for r in qa.records)


def test_analyte_coverage_skipped_without_analytes_path(tmp_path):
    sl = tmp_path / "sl.yaml"
    sl.write_text(_VALID_YAML, encoding="utf-8")
    qa = check_screening_levels(sl)
    assert not any(r.category == "analyte_not_covered" for r in qa.records)


def test_valid_entry_no_analyte_not_covered(tmp_path):
    sl = tmp_path / "sl.yaml"
    sl.write_text(_VALID_YAML, encoding="utf-8")
    al = tmp_path / "an.yaml"
    # Analytes dict only has Benzene (which IS in sl.yaml)
    al.write_text("Benzene:\n  canonical_name: Benzene\n  default_units_by_matrix: {GW: ug/L, SOIL: mg/kg}\n",
                  encoding="utf-8")
    qa = check_screening_levels(sl, analytes_path=al)
    assert not any(r.category == "analyte_not_covered" for r in qa.records)
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_manage_screening_levels.py -v
```

- [ ] **Step 3: Create `autogis/core/envmon/manage_screening_levels.py`**

```python
"""manage_screening_levels.py — validate screening_levels.yaml (headless)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..common.config import load_config
from ..common.qa import QACollector, QARecord, SEV_ERROR, SEV_WARNING


@dataclass
class ScreeningEntry:
    analyte: str
    matrix: str
    value: Optional[float]
    units: str
    source: str


def load_screening_entries(path: Path) -> list[ScreeningEntry]:
    data = load_config(path)
    sl = data.get("screening_levels", {})
    out: list[ScreeningEntry] = []
    for matrix, analytes in sl.items():
        for analyte, entry in (analytes or {}).items():
            v = entry.get("value") if isinstance(entry, dict) else None
            u = entry.get("units", "") if isinstance(entry, dict) else ""
            s = entry.get("source", "") if isinstance(entry, dict) else ""
            out.append(ScreeningEntry(analyte=analyte, matrix=matrix,
                                      value=v, units=u, source=s))
    return out


def check_screening_levels(
    screening_path: Path,
    analytes_path: Optional[Path] = None,
) -> QACollector:
    qa = QACollector()
    data = load_config(screening_path)
    sl = data.get("screening_levels", {})

    # --- per-entry checks ---
    for matrix, analytes in sl.items():
        for analyte, entry in (analytes or {}).items():
            ctx = f"{matrix}/{analyte}"
            if not isinstance(entry, dict):
                qa.add(QARecord(SEV_ERROR, "invalid_entry",
                                f"{ctx}: expected a mapping, got {type(entry).__name__}"))
                continue
            for key in ("value", "units", "source"):
                if key not in entry:
                    qa.add(QARecord(SEV_ERROR, "missing_entry_key",
                                    f"{ctx}: missing required key '{key}'"))
            units = entry.get("units", "")
            source = entry.get("source", "")
            value = entry.get("value")
            if value is None:
                qa.add(QARecord(SEV_WARNING, "null_value",
                                f"{ctx}: value is null (pre-production stub)"))
            if "_TODO" in str(source):
                qa.add(QARecord(SEV_WARNING, "placeholder_source",
                                f"{ctx}: source contains _TODO: {source!r}",
                                recommended_action="Replace with citation before production use"))

    # --- analyte coverage check (optional) ---
    if analytes_path is not None:
        analytes_data = load_config(analytes_path)
        covered: set[tuple[str, str]] = set()
        for matrix, ents in sl.items():
            for analyte in (ents or {}):
                covered.add((analyte, matrix))
        for analyte, info in analytes_data.items():
            matrices = info.get("default_units_by_matrix", {}) if isinstance(info, dict) else {}
            for matrix in matrices:
                if (analyte, matrix) not in covered:
                    qa.add(QARecord(SEV_WARNING, "analyte_not_covered",
                                    f"Analyte {analyte!r} has no screening level for matrix {matrix}",
                                    recommended_action="Add entry to screening_levels.yaml or mark null"))

    counts = qa.counts_by_severity()
    qa.add(QARecord(SEV_WARNING if counts.get("ERROR") else "INFO",
                    "validation_complete",
                    f"Screening levels check: {counts.get('ERROR',0)} error(s), "
                    f"{counts.get('WARNING',0)} warning(s)"))
    return qa
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_manage_screening_levels.py -v
```

Expected: all 8 PASS.

- [ ] **Step 5: Full suite**

```
python -m pytest -q
```

- [ ] **Step 6: Commit**

```bash
git add autogis/core/envmon/manage_screening_levels.py tests/envmon/test_manage_screening_levels.py
git commit -m "feat(envmon): manage_screening_levels — check_screening_levels + ScreeningEntry"
```

---

### Task 2: CLI command

- [ ] **Step 1: Add to `cli.py`** (after `manage-analyte-dict` block)

```python
@envmon.command("manage-screening-levels")
@click.argument("screening", type=click.Path(exists=True))
@click.option("--analytes", default=None, type=click.Path(exists=True))
@click.option("--list", "do_list", is_flag=True, default=False,
              help="Print analyte/matrix/value table.")
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error")
def manage_screening_levels_cmd(screening, analytes, do_list, report, fail_on):
    """Validate and inspect the screening levels YAML (headless)."""
    from autogis.core.envmon.manage_screening_levels import (
        check_screening_levels, load_screening_entries)
    if do_list:
        entries = load_screening_entries(Path(screening))
        click.echo(f"{'analyte':<28} {'matrix':<6} {'value':>10}  units")
        for e in sorted(entries, key=lambda x: (x.matrix, x.analyte)):
            v = str(e.value) if e.value is not None else "null"
            click.echo(f"{e.analyte:<28} {e.matrix:<6} {v:>10}  {e.units}")
        if not analytes:
            return
    qa = check_screening_levels(Path(screening),
                                Path(analytes) if analytes else None)
    _render_qa(qa, report, fail_on)
```

- [ ] **Step 2: Smoke test**

```python
# Append to tests/envmon/test_manage_screening_levels.py
from click.testing import CliRunner
from autogis.adapters.cli import autogis

def test_manage_screening_levels_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "manage-screening-levels" in result.output
```

- [ ] **Step 3: Run tests + full suite, commit**

```bash
git add autogis/adapters/cli.py tests/envmon/test_manage_screening_levels.py
git commit -m "feat(cli): add manage-screening-levels command"
```
