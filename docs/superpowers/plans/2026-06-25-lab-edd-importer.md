# Lab EDD Importer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `ImportLabEDD` (Tool 2.3) — reads lab EDD CSV/XLSX files, maps columns via a per-lab YAML profile, and writes normalized `SampleRecord` + `AnalyticalResultRecord` rows to a GDB.

**Architecture:** `LabEDDProfile` holds per-lab column mappings; `normalize_edd_rows()` is an arcpy-free core that produces `gdb_schema` records; `run_edd_import()` orchestrates the full lifecycle via existing `import_to_gdb.py` functions; CLI command `autogis envmon import-edd` is the entry point.

**Tech Stack:** Python 3.10+, stdlib `csv`, `openpyxl` (already in project), `PyYAML` (already in project). No new packages.

## Global Constraints

- No `arcpy` imports in `edd_profile.py` or `edd_importer.py` — arcpy only in `import_to_gdb.py` which is called from `run_edd_import`
- All unit tests run with `python -m pytest -q` arcpy-free — `normalize_edd_rows` takes plain dicts, no GDB
- `from __future__ import annotations` at top of every new module
- Output record types are `gdb_schema.SampleRecord` and `gdb_schema.AnalyticalResultRecord` — NOT `schema/envmon.EnvSample` (which has no callers)
- `import_to_gdb.py` is NOT modified — only called from `run_edd_import`
- `result_parser._apply_qualifiers` is exposed as `apply_qualifiers` via a public alias (Task 1) — the private name stays to avoid breaking internal callers
- `--gdb` is required in the CLI for this iteration (no dry-run mode yet)

---

## File Map

**Created:**
- `autogis/core/envmon/edd_profile.py` — `LabEDDProfile` dataclass + `validate_edd_profile`
- `autogis/core/envmon/edd_importer.py` — `read_edd_file`, `normalize_edd_rows`, `run_edd_import`
- `autogis/config/lab_profiles/testamerica.yaml` — reference profile for TestAmerica
- `tests/envmon/test_edd_profile.py`
- `tests/envmon/test_edd_importer.py`
- `tests/envmon/fixtures/edd/testamerica_simple.csv`

**Modified:**
- `autogis/core/envmon/result_parser.py` — add `apply_qualifiers = _apply_qualifiers` public alias
- `autogis/adapters/cli.py` — add `import-edd` command to `envmon` group

---

## Task 1: Expose `apply_qualifiers` in `result_parser.py`

**Files:**
- Modify: `autogis/core/envmon/result_parser.py` (after `_apply_qualifiers` definition, ~line 104)
- Test: `tests/envmon/test_result_parser.py` (add one test to existing file)

**Interfaces:**
- Produces: `apply_qualifiers(parsed: ParsedResult, qual_text: str) -> None` — public alias imported by Task 3

- [ ] **Step 1: Write the failing test**

Add to `tests/envmon/test_result_parser.py` (at the end of the existing file):

```python
def test_apply_qualifiers_public_alias():
    from autogis.core.envmon.result_parser import apply_qualifiers, ParsedResult
    p = ParsedResult(raw_text="0.5")
    apply_qualifiers(p, "U")
    assert p.is_nondetect is True
    assert p.qualifier == "U"
```

- [ ] **Step 2: Run test to confirm it fails**

```
python -m pytest tests/envmon/test_result_parser.py::test_apply_qualifiers_public_alias -v
```
Expected: `ImportError: cannot import name 'apply_qualifiers'`

- [ ] **Step 3: Add public alias to `result_parser.py`**

Open `autogis/core/envmon/result_parser.py`. Find the line immediately after the `_apply_qualifiers` function definition (around line 103). Add:

```python
#: Public alias — EDD importer uses this; internal callers keep _apply_qualifiers.
apply_qualifiers = _apply_qualifiers
```

- [ ] **Step 4: Run test to confirm it passes**

```
python -m pytest tests/envmon/test_result_parser.py::test_apply_qualifiers_public_alias -v
```
Expected: PASS

- [ ] **Step 5: Run full suite — no regressions**

```
python -m pytest -q
```
Expected: All tests pass.

- [ ] **Step 6: Commit**

```
git add autogis/core/envmon/result_parser.py tests/envmon/test_result_parser.py
git commit -m "feat(result_parser): expose apply_qualifiers as public alias for EDD importer"
```

---

## Task 2: `edd_profile.py` + `testamerica.yaml`

**Files:**
- Create: `autogis/core/envmon/edd_profile.py`
- Create: `autogis/config/lab_profiles/testamerica.yaml`
- Create: `tests/envmon/test_edd_profile.py`

**Interfaces:**
- Consumes: `autogis.core.common.config.load_config` (existing)
- Produces:
  - `LabEDDProfile(profile_id, lab_name, format, date_format, encoding, columns, matrix_map, nondetect_qualifiers, sample_sheet, result_sheet, path)`
  - `LabEDDProfile.load(path: Path) -> LabEDDProfile`
  - `LabEDDProfile.resolve_column(row: dict, field: str) -> str | None`
  - `validate_edd_profile(profile: LabEDDProfile, qa: QACollector) -> None`

- [ ] **Step 1: Write the failing tests**

Create `tests/envmon/test_edd_profile.py`:

```python
from __future__ import annotations
import textwrap
from pathlib import Path
import pytest
from autogis.core.envmon.edd_profile import LabEDDProfile, validate_edd_profile
from autogis.core.common.qa import QACollector, SEV_ERROR


def _write_yaml(tmp_path, content: str) -> Path:
    p = tmp_path / "test.yaml"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


MINIMAL_YAML = """
    profile_id: test_lab
    lab_name: Test Lab
    format: flat_csv
    date_format: "%m/%d/%Y"
    encoding: utf-8
    columns:
      sample_id: SampleID
      location_id: LocationID
      event_date: CollDate
      matrix: Medium
      analyte: Chemical
      result: Result
      units: Unit
      qualifier: Qual
      reporting_limit: RL
    matrix_map:
      WS: GW
    nondetect_qualifiers:
      - U
      - UJ
"""


def test_load_returns_profile(tmp_path):
    p = _write_yaml(tmp_path, MINIMAL_YAML)
    profile = LabEDDProfile.load(p)
    assert profile.profile_id == "test_lab"
    assert profile.lab_name == "Test Lab"
    assert profile.format == "flat_csv"
    assert profile.date_format == "%m/%d/%Y"
    assert profile.encoding == "utf-8"
    assert profile.matrix_map == {"WS": "GW"}
    assert profile.nondetect_qualifiers == ["U", "UJ"]
    assert profile.path == p


def test_load_defaults_for_xlsx_sheets(tmp_path):
    p = _write_yaml(tmp_path, MINIMAL_YAML)
    profile = LabEDDProfile.load(p)
    assert profile.sample_sheet == "Samples"
    assert profile.result_sheet == "Results"


def test_load_overrides_xlsx_sheets(tmp_path):
    yaml = MINIMAL_YAML + "\nsample_sheet: SampleData\nresult_sheet: ResultData\n"
    p = _write_yaml(tmp_path, yaml)
    profile = LabEDDProfile.load(p)
    assert profile.sample_sheet == "SampleData"
    assert profile.result_sheet == "ResultData"


def test_resolve_column_string_match(tmp_path):
    p = _write_yaml(tmp_path, MINIMAL_YAML)
    profile = LabEDDProfile.load(p)
    row = {"SampleID": "S-001", "LocationID": "MW-1"}
    assert profile.resolve_column(row, "sample_id") == "S-001"


def test_resolve_column_list_first_match(tmp_path):
    yaml = MINIMAL_YAML.replace("sample_id: SampleID",
                                "sample_id:\n      - SampleRef\n      - SampleID")
    p = _write_yaml(tmp_path, yaml)
    profile = LabEDDProfile.load(p)
    # "SampleRef" not present, falls back to "SampleID"
    row = {"SampleID": "S-001"}
    assert profile.resolve_column(row, "sample_id") == "S-001"


def test_resolve_column_list_prefers_first(tmp_path):
    yaml = MINIMAL_YAML.replace("sample_id: SampleID",
                                "sample_id:\n      - SampleRef\n      - SampleID")
    p = _write_yaml(tmp_path, yaml)
    profile = LabEDDProfile.load(p)
    row = {"SampleRef": "primary", "SampleID": "fallback"}
    assert profile.resolve_column(row, "sample_id") == "primary"


def test_resolve_column_missing_field_returns_none(tmp_path):
    p = _write_yaml(tmp_path, MINIMAL_YAML)
    profile = LabEDDProfile.load(p)
    row = {"SampleID": "S-001"}
    # "depth_top_ft" not in columns
    assert profile.resolve_column(row, "depth_top_ft") is None


def test_resolve_column_missing_value_returns_none(tmp_path):
    p = _write_yaml(tmp_path, MINIMAL_YAML)
    profile = LabEDDProfile.load(p)
    row = {}   # SampleID column not present in row
    assert profile.resolve_column(row, "sample_id") is None


def test_validate_edd_profile_happy_path(tmp_path):
    p = _write_yaml(tmp_path, MINIMAL_YAML)
    profile = LabEDDProfile.load(p)
    qa = QACollector()
    validate_edd_profile(profile, qa)
    assert not any(r.severity == SEV_ERROR for r in qa.records)


def test_validate_edd_profile_bad_format(tmp_path):
    yaml = MINIMAL_YAML.replace("format: flat_csv", "format: excel_grid")
    p = _write_yaml(tmp_path, yaml)
    profile = LabEDDProfile.load(p)
    qa = QACollector()
    validate_edd_profile(profile, qa)
    assert any(r.severity == SEV_ERROR and "format" in r.message for r in qa.records)


def test_validate_edd_profile_missing_required_column(tmp_path):
    yaml = MINIMAL_YAML.replace("sample_id: SampleID\n", "")
    p = _write_yaml(tmp_path, yaml)
    profile = LabEDDProfile.load(p)
    qa = QACollector()
    validate_edd_profile(profile, qa)
    assert any(r.severity == SEV_ERROR and "sample_id" in r.message for r in qa.records)
```

- [ ] **Step 2: Run tests to confirm they fail**

```
python -m pytest tests/envmon/test_edd_profile.py -q
```
Expected: `ImportError: No module named 'autogis.core.envmon.edd_profile'`

- [ ] **Step 3: Create `autogis/config/lab_profiles/testamerica.yaml`**

```yaml
# autogis/config/lab_profiles/testamerica.yaml
# Reference profile for TestAmerica laboratories.
profile_id: testamerica
lab_name: "TestAmerica"
format: flat_csv
date_format: "%m/%d/%Y"
encoding: "utf-8-sig"

columns:
  sample_id:       "LabID"
  location_id:     "SysLocCode"
  event_date:      "CollDate"
  matrix:          "Medium"
  analyte:         "Chemical"
  result:          "Result"
  units:           "Unit"
  qualifier:       "Qualifier"
  reporting_limit: "RL"
  method:          "AnalytMeth"
  lab_sample_id:   "LabID"
  depth_top_ft:    "TopDepth"
  depth_bot_ft:    "BotDepth"

matrix_map:
  WS: GW
  WG: GW
  SO: SOIL
  SB: SOIL

nondetect_qualifiers: ["U", "UJ"]
```

- [ ] **Step 4: Implement `autogis/core/envmon/edd_profile.py`**

```python
# autogis/core/envmon/edd_profile.py
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from autogis.core.common.config import load_config
from autogis.core.common.qa import QACollector, SEV_ERROR

_REQUIRED_COLUMNS = {
    "sample_id", "location_id", "event_date", "matrix",
    "analyte", "result", "units", "qualifier", "reporting_limit",
}
_VALID_FORMATS = {"flat_csv", "two_tab_xlsx"}


@dataclass
class LabEDDProfile:
    profile_id: str
    lab_name: str
    format: str                              # "flat_csv" | "two_tab_xlsx"
    date_format: str
    encoding: str
    columns: dict[str, str | list[str]]     # field_name → col_name(s)
    matrix_map: dict[str, str]
    nondetect_qualifiers: list[str]
    sample_sheet: str = "Samples"            # two_tab_xlsx only
    result_sheet: str = "Results"            # two_tab_xlsx only
    path: Optional[Path] = field(default=None, compare=False)

    @classmethod
    def load(cls, path: Path) -> "LabEDDProfile":
        path = Path(path)
        data = load_config(path)
        return cls(
            profile_id=data["profile_id"],
            lab_name=data.get("lab_name", data["profile_id"]),
            format=data.get("format", "flat_csv"),
            date_format=data.get("date_format", "%m/%d/%Y"),
            encoding=data.get("encoding", "utf-8"),
            columns=data.get("columns", {}),
            matrix_map=data.get("matrix_map", {}),
            nondetect_qualifiers=data.get("nondetect_qualifiers", ["U", "UJ"]),
            sample_sheet=data.get("sample_sheet", "Samples"),
            result_sheet=data.get("result_sheet", "Results"),
            path=path,
        )

    def resolve_column(self, row: dict, field: str) -> str | None:
        """Return the row value for a canonical field, or None if not found.

        Tries each alternate column name in order. Caller emits QA on None."""
        spec = self.columns.get(field)
        if spec is None:
            return None
        names = [spec] if isinstance(spec, str) else spec
        for name in names:
            val = row.get(name)
            if val is not None:
                return str(val) if val != "" else None
        return None


def validate_edd_profile(profile: LabEDDProfile, qa: QACollector) -> None:
    if profile.format not in _VALID_FORMATS:
        qa.add(SEV_ERROR, "edd_profile_bad_format",
               f"Unknown format '{profile.format}'; expected one of "
               f"{sorted(_VALID_FORMATS)}")
    for req in sorted(_REQUIRED_COLUMNS):
        if req not in profile.columns:
            qa.add(SEV_ERROR, "edd_profile_missing_column",
                   f"Required column mapping '{req}' not defined in profile "
                   f"'{profile.profile_id}'")
```

- [ ] **Step 5: Run tests to confirm they pass**

```
python -m pytest tests/envmon/test_edd_profile.py -q
```
Expected: All tests pass.

- [ ] **Step 6: Run full suite — no regressions**

```
python -m pytest -q
```

- [ ] **Step 7: Commit**

```
git add autogis/core/envmon/edd_profile.py autogis/config/lab_profiles/ tests/envmon/test_edd_profile.py
git commit -m "feat(edd_profile): LabEDDProfile YAML loader + validate_edd_profile"
```

---

## Task 3: `edd_importer.py` — file reading + `normalize_edd_rows`

**Files:**
- Create: `autogis/core/envmon/edd_importer.py` (Tasks 3 and 4 both build this file — Task 3 adds the arcpy-free core; Task 4 adds the orchestrator on top)
- Create: `tests/envmon/fixtures/edd/testamerica_simple.csv`
- Create: `tests/envmon/test_edd_importer.py`

**Interfaces:**
- Consumes:
  - `LabEDDProfile` from Task 2
  - `apply_qualifiers(parsed, qual_text)` from Task 1
  - `parse_result_value(raw_value) -> ParsedResult` from `result_parser`
  - `parse_excel_date(value) -> Optional[date]` from `result_parser`
  - `normalize_analyte_name(raw_name, analyte_dictionary) -> Optional[str]` from `result_parser`
  - `evaluate_screening(parsed, screening_level) -> Optional[bool]` from `result_parser`
  - `classify_display(parsed, exceeds) -> str` from `result_parser`
  - `screening_for(screening_levels, matrix, canonical) -> Optional[dict]` from `config`
  - `SampleRecord`, `AnalyticalResultRecord` from `gdb_schema`
  - `QACollector`, `SEV_ERROR`, `SEV_WARNING` from `qa`
- Produces:
  - `read_edd_file(path: Path, profile: LabEDDProfile) -> list[dict]`
  - `normalize_edd_rows(rows, profile, site_id, batch_id, analyte_dictionary, screening_levels, qa, event_date_override) -> tuple[list[SampleRecord], list[AnalyticalResultRecord]]`

- [ ] **Step 1: Create fixture CSV**

Create `tests/envmon/fixtures/edd/testamerica_simple.csv`:

```
SysLocCode,CollDate,Medium,LabID,Chemical,Result,Qualifier,RL,Unit,AnalytMeth
MW-1,06/01/2026,WS,H281-MW1-001,Benzene,0.5,U,0.5,ug/L,EPA 8260B
MW-1,06/01/2026,WS,H281-MW1-001,Toluene,12.3,,0.5,ug/L,EPA 8260B
MW-2,06/01/2026,WS,H281-MW2-001,Benzene,,,0.5,ug/L,EPA 8260B
MW-3,06/01/2026,SO,H281-MW3-001,Benzene,5.0,,0.5,mg/kg,EPA 8260B
```

- [ ] **Step 2: Write the failing tests**

Create `tests/envmon/test_edd_importer.py`:

```python
from __future__ import annotations
import textwrap
from datetime import date
from pathlib import Path

import pytest

from autogis.core.envmon.edd_profile import LabEDDProfile
from autogis.core.envmon.edd_importer import read_edd_file, normalize_edd_rows
from autogis.core.common.qa import QACollector, SEV_ERROR, SEV_WARNING

# Minimal profile matching the fixture CSV columns
_PROFILE_YAML = textwrap.dedent("""
    profile_id: test_lab
    lab_name: Test Lab
    format: flat_csv
    date_format: "%m/%d/%Y"
    encoding: utf-8
    columns:
      sample_id:       SysLocCode
      location_id:     SysLocCode
      event_date:      CollDate
      matrix:          Medium
      analyte:         Chemical
      result:          Result
      units:           Unit
      qualifier:       Qualifier
      reporting_limit: RL
      method:          AnalytMeth
      lab_sample_id:   LabID
    matrix_map:
      WS: GW
      SO: SOIL
    nondetect_qualifiers:
      - U
      - UJ
""")

ANALYTES = {
    "Benzene": {
        "aliases": ["benzene"],
        "abbreviation": "BNZ",
        "analytical_group": "VOC",
        "method_group": "EPA8260",
        "default_units_by_matrix": {"GW": "ug/L"},
    },
    "Toluene": {
        "aliases": ["toluene"],
        "abbreviation": "TOL",
        "analytical_group": "VOC",
        "method_group": "EPA8260",
    },
}

SCREENING = {
    "GW": {
        "Benzene": {"value": 1.0, "units": "ug/L", "source": "USEPA MCL"},
    }
}

FIXTURE_CSV = Path(__file__).parent / "fixtures" / "edd" / "testamerica_simple.csv"


def _make_profile(tmp_path) -> LabEDDProfile:
    p = tmp_path / "profile.yaml"
    p.write_text(_PROFILE_YAML, encoding="utf-8")
    return LabEDDProfile.load(p)


def _rows(profile, site_id="H281", batch_id="B-001", analytes=None,
          screening=None, override=None) -> tuple:
    qa = QACollector()
    s, r = normalize_edd_rows(
        list(read_edd_file(FIXTURE_CSV, profile)),
        profile=profile,
        site_id=site_id,
        batch_id=batch_id,
        analyte_dictionary=analytes or ANALYTES,
        screening_levels=screening or SCREENING,
        qa=qa,
        event_date_override=override,
    )
    return s, r, qa


def test_read_edd_file_returns_rows(tmp_path):
    profile = _make_profile(tmp_path)
    rows = list(read_edd_file(FIXTURE_CSV, profile))
    assert len(rows) == 4
    assert "SysLocCode" in rows[0]


def test_nondetect_qualifier_u(tmp_path):
    profile = _make_profile(tmp_path)
    s, r, qa = _rows(profile)
    # Benzene MW-1 has qualifier U
    benzene_mw1 = [x for x in r if x.LocationID == "MW-1"
                   and x.AnalyteName == "Benzene"][0]
    assert benzene_mw1.IsNonDetect == 1
    assert benzene_mw1.IsDetected == 0
    assert benzene_mw1.Qualifier == "U"


def test_detected_value(tmp_path):
    profile = _make_profile(tmp_path)
    s, r, qa = _rows(profile)
    toluene = [x for x in r if x.AnalyteName == "Toluene"][0]
    assert toluene.IsDetected == 1
    assert toluene.IsNonDetect == 0
    assert toluene.ResultNumeric == pytest.approx(12.3)


def test_blank_result_is_not_detected(tmp_path):
    profile = _make_profile(tmp_path)
    s, r, qa = _rows(profile)
    benzene_mw2 = [x for x in r if x.LocationID == "MW-2"
                   and x.AnalyteName == "Benzene"][0]
    assert benzene_mw2.IsDetected == 0
    assert benzene_mw2.ResultNumeric is None


def test_sample_deduplication(tmp_path):
    profile = _make_profile(tmp_path)
    s, r, qa = _rows(profile)
    # MW-1 has two results (Benzene + Toluene) — should produce exactly 1 SampleRecord
    mw1_samples = [x for x in s if x.LocationID == "MW-1"]
    assert len(mw1_samples) == 1
    # But two AnalyticalResultRecords
    mw1_results = [x for x in r if x.LocationID == "MW-1"]
    assert len(mw1_results) == 2


def test_matrix_mapping(tmp_path):
    profile = _make_profile(tmp_path)
    s, r, qa = _rows(profile)
    # MW-3 has Medium="SO" → should map to "SOIL"
    mw3_sample = [x for x in s if x.LocationID == "MW-3"][0]
    assert mw3_sample.Matrix == "SOIL"


def test_unknown_matrix_emits_warning(tmp_path):
    profile = _make_profile(tmp_path)
    # Inject a row with unknown matrix "XX"
    rows = [{"SysLocCode": "MW-X", "CollDate": "06/01/2026", "Medium": "XX",
             "LabID": "X-001", "Chemical": "Benzene", "Result": "1.0",
             "Qualifier": "", "RL": "0.5", "Unit": "ug/L", "AnalytMeth": ""}]
    qa = QACollector()
    s, r = normalize_edd_rows(rows, profile=profile, site_id="H281",
                               batch_id="B", analyte_dictionary=ANALYTES,
                               screening_levels=SCREENING, qa=qa)
    assert any(r.severity == SEV_WARNING and "matrix" in r.message.lower()
               for r in qa.records)


def test_unknown_analyte_emits_warning(tmp_path):
    profile = _make_profile(tmp_path)
    rows = [{"SysLocCode": "MW-1", "CollDate": "06/01/2026", "Medium": "WS",
             "LabID": "X-001", "Chemical": "Dibromochloromethane",
             "Result": "1.0", "Qualifier": "", "RL": "0.5",
             "Unit": "ug/L", "AnalytMeth": ""}]
    qa = QACollector()
    s, r = normalize_edd_rows(rows, profile=profile, site_id="H281",
                               batch_id="B", analyte_dictionary=ANALYTES,
                               screening_levels=SCREENING, qa=qa)
    assert any(rec.severity == SEV_WARNING and "analyte" in rec.message.lower()
               for rec in qa.records)


def test_missing_required_column_emits_error(tmp_path):
    profile = _make_profile(tmp_path)
    # Row missing "SysLocCode" (mapped to both sample_id and location_id)
    rows = [{"CollDate": "06/01/2026", "Medium": "WS", "LabID": "X-001",
             "Chemical": "Benzene", "Result": "1.0", "Qualifier": "",
             "RL": "0.5", "Unit": "ug/L", "AnalytMeth": ""}]
    qa = QACollector()
    s, r = normalize_edd_rows(rows, profile=profile, site_id="H281",
                               batch_id="B", analyte_dictionary=ANALYTES,
                               screening_levels=SCREENING, qa=qa)
    assert len(s) == 0
    assert len(r) == 0
    assert any(rec.severity == SEV_ERROR for rec in qa.records)


def test_event_date_override(tmp_path):
    profile = _make_profile(tmp_path)
    override = date(2026, 3, 15)
    s, r, qa = _rows(profile, override=override)
    for sample in s:
        assert sample.SampleDate == override


def test_exceeds_screening_level(tmp_path):
    profile = _make_profile(tmp_path)
    # Toluene MW-1: 12.3 ug/L — no SL for Toluene → ExceedsScreeningLevel is None
    toluene = [x for x in _rows(profile)[1] if x.AnalyteName == "Toluene"][0]
    assert toluene.ExceedsScreeningLevel is None
    # Benzene MW-3 in SOIL matrix — no SL for SOIL Benzene → None
    benzene_soil = [x for x in _rows(profile)[1]
                    if x.LocationID == "MW-3" and x.AnalyteName == "Benzene"][0]
    assert benzene_soil.ExceedsScreeningLevel is None
```

- [ ] **Step 3: Run tests to confirm they fail**

```
python -m pytest tests/envmon/test_edd_importer.py -q
```
Expected: `ImportError: No module named 'autogis.core.envmon.edd_importer'`

- [ ] **Step 4: Create `tests/envmon/fixtures/edd/` and the CSV fixture**

Create the directory and write the file as specified in Step 1. The CSV content is:
```
SysLocCode,CollDate,Medium,LabID,Chemical,Result,Qualifier,RL,Unit,AnalytMeth
MW-1,06/01/2026,WS,H281-MW1-001,Benzene,0.5,U,0.5,ug/L,EPA 8260B
MW-1,06/01/2026,WS,H281-MW1-001,Toluene,12.3,,0.5,ug/L,EPA 8260B
MW-2,06/01/2026,WS,H281-MW2-001,Benzene,,,0.5,ug/L,EPA 8260B
MW-3,06/01/2026,SO,H281-MW3-001,Benzene,5.0,,0.5,mg/kg,EPA 8260B
```

- [ ] **Step 5: Implement `autogis/core/envmon/edd_importer.py` (arcpy-free core)**

```python
# autogis/core/envmon/edd_importer.py
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Optional

from autogis.core.common.config import load_config, screening_for
from autogis.core.common.qa import QACollector, SEV_ERROR, SEV_WARNING
from autogis.core.envmon.edd_profile import LabEDDProfile
from autogis.core.envmon.gdb_schema import SampleRecord, AnalyticalResultRecord
from autogis.core.envmon.result_parser import (
    apply_qualifiers, classify_display, evaluate_screening,
    normalize_analyte_name, parse_excel_date, parse_result_value,
)


# ---------------------------------------------------------------------------
# File reading
# ---------------------------------------------------------------------------

def read_edd_file(path: Path, profile: LabEDDProfile) -> list[dict]:
    """Read EDD file and return a flat list of row dicts.

    For two_tab_xlsx, sample-sheet metadata is merged onto each result row
    before returning, so the output is the same shape regardless of format.
    """
    path = Path(path)
    if profile.format == "flat_csv":
        return _read_flat_csv(path, profile)
    if profile.format == "two_tab_xlsx":
        return _read_two_tab_xlsx(path, profile)
    raise ValueError(f"Unknown EDD format '{profile.format}'")


def _read_flat_csv(path: Path, profile: LabEDDProfile) -> list[dict]:
    with path.open(newline="", encoding=profile.encoding) as fh:
        return list(csv.DictReader(fh))


def _read_two_tab_xlsx(path: Path, profile: LabEDDProfile) -> list[dict]:
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)

    def _sheet_to_dicts(ws) -> list[dict]:
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        headers = [str(h) if h is not None else "" for h in rows[0]]
        return [dict(zip(headers, row)) for row in rows[1:]]

    sample_rows = _sheet_to_dicts(wb[profile.sample_sheet])
    result_rows = _sheet_to_dicts(wb[profile.result_sheet])

    # Build sample metadata index keyed by lab sample id
    sample_col = (profile.columns.get("sample_id") or "")
    if isinstance(sample_col, list):
        sample_col = sample_col[0]
    sample_index = {str(r.get(sample_col, "")): r for r in sample_rows}

    merged = []
    for result in result_rows:
        key = str(result.get(sample_col, ""))
        base = dict(sample_index.get(key, {}))
        base.update(result)   # result columns win on collision
        merged.append(base)
    return merged


# ---------------------------------------------------------------------------
# Normalizer (arcpy-free)
# ---------------------------------------------------------------------------

_REQUIRED = ("sample_id", "location_id", "event_date", "matrix",
             "analyte", "result", "units")


def normalize_edd_rows(
    rows: list[dict],
    profile: LabEDDProfile,
    site_id: str,
    batch_id: str,
    analyte_dictionary: dict,
    screening_levels: dict,
    qa: QACollector,
    event_date_override: Optional[date] = None,
) -> tuple[list[SampleRecord], list[AnalyticalResultRecord]]:
    """Convert flat EDD row dicts to SampleRecord + AnalyticalResultRecord lists.

    Rows with missing required fields are skipped with SEV_ERROR QA records.
    All other errors are warnings — the row is still processed."""
    source_name = profile.profile_id

    samples: list[SampleRecord] = []
    results: list[AnalyticalResultRecord] = []
    seen_sample_keys: set[tuple] = set()

    for row_num, row in enumerate(rows, start=2):  # 2 = data starts after header

        # --- extract required fields ---
        sample_id   = profile.resolve_column(row, "sample_id")
        location_id = profile.resolve_column(row, "location_id")
        date_raw    = profile.resolve_column(row, "event_date") or ""
        matrix_raw  = profile.resolve_column(row, "matrix") or ""
        analyte_raw = profile.resolve_column(row, "analyte") or ""
        result_raw  = profile.resolve_column(row, "result")
        units_raw   = profile.resolve_column(row, "units") or ""

        missing = [f for f, v in [("sample_id", sample_id),
                                   ("location_id", location_id),
                                   ("analyte", analyte_raw or None)]
                   if not v]
        if missing:
            qa.add(SEV_ERROR, "edd_missing_required_field",
                   f"Row {row_num}: missing required field(s): "
                   f"{', '.join(missing)} — row skipped",
                   site_id=site_id, import_batch_id=batch_id,
                   source_sheet=source_name, source_row=row_num)
            continue

        # --- date ---
        if event_date_override is not None:
            sample_date = event_date_override
        else:
            sample_date = parse_excel_date(date_raw)
            if sample_date is None:
                qa.add(SEV_WARNING, "edd_bad_date",
                       f"Row {row_num}: cannot parse date '{date_raw}'; "
                       f"row will have no event date",
                       site_id=site_id, location_id=location_id,
                       sample_id=sample_id, import_batch_id=batch_id,
                       source_sheet=source_name, source_row=row_num)

        # --- matrix ---
        matrix = profile.matrix_map.get(matrix_raw, matrix_raw)
        if matrix_raw and matrix_raw not in profile.matrix_map and matrix_raw != matrix:
            pass  # mapped successfully
        elif matrix_raw and matrix_raw not in profile.matrix_map:
            qa.add(SEV_WARNING, "edd_unknown_matrix",
                   f"Row {row_num}: matrix '{matrix_raw}' not in profile "
                   f"matrix_map; using as-is",
                   site_id=site_id, location_id=location_id,
                   sample_id=sample_id, import_batch_id=batch_id,
                   source_sheet=source_name, source_row=row_num)

        # --- result parsing ---
        parsed = parse_result_value(result_raw)

        # apply separate qualifier column (EDD-specific: separate from result)
        qualifier_raw = profile.resolve_column(row, "qualifier") or ""
        if qualifier_raw.strip():
            apply_qualifiers(parsed, qualifier_raw)

        # force nondetect for known ND qualifiers even when not in qualifier_raw
        if any(q in (parsed.qualifier_list or [])
               for q in profile.nondetect_qualifiers):
            parsed.is_nondetect = True
            parsed.is_detected = False

        # --- analyte resolution ---
        canonical = normalize_analyte_name(analyte_raw, analyte_dictionary)
        if canonical is None:
            qa.add(SEV_WARNING, "edd_unknown_analyte",
                   f"Row {row_num}: analyte '{analyte_raw}' not found in "
                   f"analyte dictionary; using raw name",
                   site_id=site_id, location_id=location_id,
                   sample_id=sample_id, import_batch_id=batch_id,
                   source_sheet=source_name, source_row=row_num)
            canonical = analyte_raw

        # --- optional fields ---
        rl_raw   = profile.resolve_column(row, "reporting_limit")
        method   = profile.resolve_column(row, "method") or ""
        lab_sid  = profile.resolve_column(row, "lab_sample_id") or ""
        try:
            dt = float(profile.resolve_column(row, "depth_top_ft") or "")
        except (ValueError, TypeError):
            dt = None
        try:
            db = float(profile.resolve_column(row, "depth_bot_ft") or "")
        except (ValueError, TypeError):
            db = None
        depth_text = f"{dt}'-{db}'" if dt is not None and db is not None else ""

        # reporting limit from profile column overrides any parsed from result
        if rl_raw:
            try:
                parsed.reporting_limit = float(rl_raw.replace(",", ""))
            except (ValueError, AttributeError):
                pass

        # --- analyte dictionary entry ---
        entry = ({k: v for k, v in analyte_dictionary.items()
                  if not k.startswith("_")}.get(canonical) or {})

        # --- screening ---
        sl_entry = screening_for(screening_levels, matrix, canonical)
        sl_value = sl_entry["value"] if sl_entry and "value" in sl_entry else None
        sl_source = sl_entry.get("source", "") if sl_entry else ""
        exceeds = evaluate_screening(parsed, sl_value)
        display_class = classify_display(parsed, exceeds)

        # --- SampleRecord (deduplicated) ---
        sample_key = (site_id, location_id, sample_id,
                      str(sample_date), matrix)
        if sample_key not in seen_sample_keys:
            seen_sample_keys.add(sample_key)
            samples.append(SampleRecord(
                ImportBatchID=batch_id,
                SiteID=site_id,
                Matrix=matrix,
                LocationID=location_id,
                SampleID=sample_id,
                ParentSampleID="",
                SampleDate=sample_date,
                SampleDateRaw=date_raw,
                DepthTop_ft=dt,
                DepthBottom_ft=db,
                DepthIntervalText=depth_text,
                IsDuplicate=0,
                DuplicateType="",
                LabSampleID=lab_sid,
                SourceWorkbook=source_name,
                SourceSheet=profile.format,
                SourceRow=row_num,
            ))

        # --- AnalyticalResultRecord ---
        results.append(AnalyticalResultRecord(
            ImportBatchID=batch_id,
            SiteID=site_id,
            Matrix=matrix,
            LocationID=location_id,
            SampleID=sample_id,
            ParentSampleID="",
            SampleDate=sample_date,
            DepthTop_ft=dt,
            DepthBottom_ft=db,
            DepthIntervalText=depth_text,
            AnalyticalGroup=entry.get("analytical_group", ""),
            MethodGroup=entry.get("method_group", ""),
            AnalyteName=analyte_raw,
            AnalyteCanonicalName=canonical,
            AnalyteAbbreviation=entry.get("abbreviation", analyte_raw[:12]),
            ResultRawText=parsed.raw_text,
            ResultNumeric=parsed.result_numeric,
            ReportingLimit=parsed.reporting_limit,
            DetectionLimit=parsed.detection_limit,
            Units=units_raw or entry.get("default_units_by_matrix",
                                         {}).get(matrix, ""),
            Qualifier=parsed.qualifier,
            IsNonDetect=int(parsed.is_nondetect),
            IsDetected=int(parsed.is_detected),
            IsEstimated=int(parsed.is_estimated),
            IsDiluted=int(parsed.is_diluted),
            IsNotAnalyzed=int(parsed.is_not_analyzed or parsed.is_blank),
            IsNotSampled=int(parsed.is_not_sampled),
            IsNotMeasured=int(parsed.is_not_measured or parsed.is_dry),
            ScreeningLevel=sl_value,
            ScreeningLevelSource=sl_source,
            ExceedsScreeningLevel=None if exceeds is None else int(exceeds),
            DisplayText=parsed.display_text,
            DisplayColorClass=display_class,
            SourceWorkbook=source_name,
            SourceSheet=profile.format,
            SourceRow=row_num,
            SourceColumn="",
            SourceCell="",
        ))

    return samples, results
```

- [ ] **Step 6: Run tests to confirm they pass**

```
python -m pytest tests/envmon/test_edd_importer.py -q
```
Expected: All tests pass.

- [ ] **Step 7: Run full suite — no regressions**

```
python -m pytest -q
```

- [ ] **Step 8: Commit**

```
git add autogis/core/envmon/edd_importer.py tests/envmon/test_edd_importer.py tests/envmon/fixtures/edd/
git commit -m "feat(edd_importer): read_edd_file + normalize_edd_rows (arcpy-free core)"
```

---

## Task 4: `edd_importer.py` — `run_edd_import` orchestrator

**Files:**
- Modify: `autogis/core/envmon/edd_importer.py` (append `run_edd_import` function)
- Modify: `tests/envmon/test_edd_importer.py` (append orchestrator test)

**Interfaces:**
- Consumes:
  - `create_import_batch` from `autogis.core.envmon.import_to_gdb`
  - `finalize_batch` from `autogis.core.envmon.import_to_gdb`
  - `append_records_idempotent` from `autogis.core.envmon.import_to_gdb`
  - `write_qa_to_gdb` from `autogis.core.envmon.import_to_gdb`
  - `normalize_edd_rows` + `read_edd_file` from this module (Task 3)
- Produces: `run_edd_import(edd_path, profile, gdb_path, site_id, analyte_dictionary, screening_levels, event_date_override, batch_id) -> str`

- [ ] **Step 1: Write the failing test**

Append to `tests/envmon/test_edd_importer.py`:

```python
def test_run_edd_import_calls_lifecycle(tmp_path, monkeypatch):
    """Verify run_edd_import calls import_to_gdb lifecycle in order."""
    import autogis.core.envmon.edd_importer as mod

    calls = []

    def fake_create(gdb_path, site_id, source_workbook, **kw):
        calls.append("create")
        return "BATCH-001"

    def fake_append(gdb_path, table_name, records):
        calls.append(f"append:{table_name}")

    def fake_finalize(gdb_path, batch_id, **kw):
        calls.append("finalize")

    def fake_write_qa(gdb_path, qa, batch_id):
        calls.append("write_qa")

    monkeypatch.setattr(mod, "create_import_batch", fake_create)
    monkeypatch.setattr(mod, "append_records_idempotent", fake_append)
    monkeypatch.setattr(mod, "finalize_batch", fake_finalize)
    monkeypatch.setattr(mod, "write_qa_to_gdb", fake_write_qa)

    profile = _make_profile(tmp_path)
    gdb = tmp_path / "test.gdb"

    batch_id = mod.run_edd_import(
        edd_path=FIXTURE_CSV,
        profile=profile,
        gdb_path=gdb,
        site_id="H281",
        analyte_dictionary=ANALYTES,
        screening_levels=SCREENING,
    )

    assert batch_id == "BATCH-001"
    assert calls[0] == "create"
    assert "append:Env_Samples" in calls
    assert "append:Env_AnalyticalResults" in calls
    assert "finalize" in calls
    assert "write_qa" in calls
    # finalize must come after appends
    assert calls.index("finalize") > calls.index("append:Env_Samples")
```

- [ ] **Step 2: Run test to confirm it fails**

```
python -m pytest tests/envmon/test_edd_importer.py::test_run_edd_import_calls_lifecycle -v
```
Expected: `AttributeError: module has no attribute 'run_edd_import'`

- [ ] **Step 3: Add `run_edd_import` to `edd_importer.py`**

Append to the bottom of `autogis/core/envmon/edd_importer.py`:

```python
# ---------------------------------------------------------------------------
# Orchestrator (calls import_to_gdb — arcpy required for GDB writes)
# ---------------------------------------------------------------------------

def run_edd_import(
    edd_path: Path,
    profile: LabEDDProfile,
    gdb_path: Path,
    site_id: str,
    analyte_dictionary: dict,
    screening_levels: dict,
    event_date_override: Optional[date] = None,
    batch_id: Optional[str] = None,
) -> str:
    """Run a full EDD import. Returns the import batch_id.

    Follows the same lifecycle as import_to_gdb.run_import():
      create_import_batch → normalize → append → finalize → write_qa
    """
    from autogis.core.envmon.import_to_gdb import (
        create_import_batch, append_records_idempotent,
        finalize_batch, write_qa_to_gdb,
    )

    edd_path = Path(edd_path)
    gdb_path = Path(gdb_path)

    batch_id = create_import_batch(
        gdb_path,
        site_id=site_id,
        source_workbook=edd_path.name,
        import_mode="EDD",
        parser_profile=profile.profile_id,
    )

    rows = read_edd_file(edd_path, profile)

    qa = QACollector()
    samples, results = normalize_edd_rows(
        rows=rows,
        profile=profile,
        site_id=site_id,
        batch_id=batch_id,
        analyte_dictionary=analyte_dictionary,
        screening_levels=screening_levels,
        qa=qa,
        event_date_override=event_date_override,
    )

    append_records_idempotent(gdb_path, "Env_Samples", samples)
    append_records_idempotent(gdb_path, "Env_AnalyticalResults", results)

    finalize_batch(
        gdb_path,
        batch_id=batch_id,
        analytical_count=len(results),
        warning_count=sum(1 for r in qa.records if r.severity == "WARNING"),
        error_count=sum(1 for r in qa.records if r.severity == "ERROR"),
        qa_status="ERROR" if qa.has_blocking() else "PASS",
    )

    write_qa_to_gdb(gdb_path, qa, batch_id)
    return batch_id
```

Also add these imports at the top of `edd_importer.py` (in the module-level imports section, not inside the function — they are imported lazily inside `run_edd_import` to keep the module arcpy-free at import time, so do NOT add them to the top-level imports):

The lazy import pattern inside `run_edd_import` (already shown above as `from autogis.core.envmon.import_to_gdb import ...`) means `edd_importer.py` can be imported without arcpy present. The `import_to_gdb` functions only run at call time, inside `run_edd_import`, which already requires arcpy to be available.

For the monkeypatch test to work, the test patches `mod.create_import_batch` etc. on the module. Since `run_edd_import` does a local `from ... import ...` inside itself, monkeypatching module-level attributes won't intercept them. Instead, add these lazy references at module level just below the `normalize_edd_rows` function so monkeypatching works:

```python
# Module-level references for monkeypatching in tests.
# Populated lazily to keep the module importable without arcpy.
def _lazy_import_to_gdb():
    from autogis.core.envmon import import_to_gdb
    return import_to_gdb
```

Then rewrite `run_edd_import` to call `_lazy_import_to_gdb()` once and pull from the returned module:

```python
def run_edd_import(
    edd_path: Path,
    profile: LabEDDProfile,
    gdb_path: Path,
    site_id: str,
    analyte_dictionary: dict,
    screening_levels: dict,
    event_date_override: Optional[date] = None,
    batch_id: Optional[str] = None,
) -> str:
    """Run a full EDD import. Returns the import batch_id."""
    edd_path = Path(edd_path)
    gdb_path = Path(gdb_path)

    batch_id = create_import_batch(
        gdb_path,
        site_id=site_id,
        source_workbook=edd_path.name,
        import_mode="EDD",
        parser_profile=profile.profile_id,
    )
    rows = read_edd_file(edd_path, profile)
    qa = QACollector()
    samples, results = normalize_edd_rows(
        rows=rows, profile=profile, site_id=site_id, batch_id=batch_id,
        analyte_dictionary=analyte_dictionary, screening_levels=screening_levels,
        qa=qa, event_date_override=event_date_override,
    )
    append_records_idempotent(gdb_path, "Env_Samples", samples)
    append_records_idempotent(gdb_path, "Env_AnalyticalResults", results)
    finalize_batch(
        gdb_path, batch_id=batch_id, analytical_count=len(results),
        warning_count=sum(1 for r in qa.records if r.severity == "WARNING"),
        error_count=sum(1 for r in qa.records if r.severity == "ERROR"),
        qa_status="ERROR" if qa.has_blocking() else "PASS",
    )
    write_qa_to_gdb(gdb_path, qa, batch_id)
    return batch_id
```

And add these **module-level** lazy stubs that monkeypatch can replace, immediately before `run_edd_import`:

```python
# These are replaced by monkeypatch in tests. They raise on call if arcpy absent.
def create_import_batch(gdb_path, **kw):  # pragma: no cover
    from autogis.core.envmon.import_to_gdb import create_import_batch as _f
    return _f(gdb_path, **kw)

def append_records_idempotent(gdb_path, table_name, records):  # pragma: no cover
    from autogis.core.envmon.import_to_gdb import append_records_idempotent as _f
    return _f(gdb_path, table_name, records)

def finalize_batch(gdb_path, **kw):  # pragma: no cover
    from autogis.core.envmon.import_to_gdb import finalize_batch as _f
    return _f(gdb_path, **kw)

def write_qa_to_gdb(gdb_path, qa, batch_id):  # pragma: no cover
    from autogis.core.envmon.import_to_gdb import write_qa_to_gdb as _f
    return _f(gdb_path, qa, batch_id)
```

- [ ] **Step 4: Run test to confirm it passes**

```
python -m pytest tests/envmon/test_edd_importer.py::test_run_edd_import_calls_lifecycle -v
```
Expected: PASS

- [ ] **Step 5: Run full suite — no regressions**

```
python -m pytest -q
```

- [ ] **Step 6: Commit**

```
git add autogis/core/envmon/edd_importer.py tests/envmon/test_edd_importer.py
git commit -m "feat(edd_importer): run_edd_import orchestrator (full import lifecycle)"
```

---

## Task 5: CLI `import-edd` command

**Files:**
- Modify: `autogis/adapters/cli.py`
- Modify: `tests/test_cli_envmon.py` (append CLI test)

**Interfaces:**
- Consumes: `run_edd_import`, `LabEDDProfile`, `load_config` from prior tasks

- [ ] **Step 1: Write the failing test**

Read `tests/test_cli_envmon.py` to find the existing CLI test pattern, then append:

```python
def test_import_edd_missing_gdb_exits_nonzero(tmp_path, cli_runner):
    """Passing a nonexistent GDB path should produce a click error, not a traceback."""
    from autogis.adapters.cli import autogis as cli

    profile_yaml = tmp_path / "lab_profiles" / "testlab.yaml"
    profile_yaml.parent.mkdir()
    profile_yaml.write_text(
        "profile_id: testlab\nlab_name: TestLab\nformat: flat_csv\n"
        "date_format: '%m/%d/%Y'\nencoding: utf-8\n"
        "columns:\n  sample_id: S\n  location_id: L\n  event_date: D\n"
        "  matrix: M\n  analyte: A\n  result: R\n  units: U\n"
        "  qualifier: Q\n  reporting_limit: RL\n"
        "matrix_map: {}\nnondetect_qualifiers: []\n",
        encoding="utf-8",
    )
    edd_csv = tmp_path / "test.csv"
    edd_csv.write_text("S,L,D,M,A,R,Q,RL,U\n", encoding="utf-8")

    result = cli_runner.invoke(cli, [
        "envmon", "import-edd",
        "--edd", str(edd_csv),
        "--profile-path", str(profile_yaml),
        "--site", "H281",
        "--gdb", str(tmp_path / "nonexistent.gdb"),
    ])
    # The command should fail cleanly — either click error or sys.exit(1)
    assert result.exit_code != 0
```

Check `tests/test_cli_envmon.py` for how `cli_runner` is defined (likely a `pytest.fixture` using `click.testing.CliRunner`). If no such fixture exists, add one:

```python
import pytest
from click.testing import CliRunner

@pytest.fixture
def cli_runner():
    return CliRunner()
```

- [ ] **Step 2: Run test to confirm it fails**

```
python -m pytest tests/test_cli_envmon.py::test_import_edd_missing_gdb_exits_nonzero -v
```
Expected: test fails (no `import-edd` command exists yet)

- [ ] **Step 3: Add `import-edd` command to `autogis/adapters/cli.py`**

After the last `@envmon.command` block (before the `if __name__` block if any), add:

```python
@envmon.command("import-edd")
@click.option("--edd", "edd_path", required=True, type=click.Path(exists=True),
              help="Path to EDD CSV or XLSX file.")
@click.option("--profile-path", required=True, type=click.Path(exists=True),
              help="Path to lab profile YAML.")
@click.option("--site", "site_id", required=True,
              help="Site ID (e.g. H281).")
@click.option("--gdb", "gdb_path", required=True, type=click.Path(),
              help="Path to target file GDB.")
@click.option("--analytes", default=None, type=click.Path(exists=True),
              help="Analyte dictionary YAML (optional; skips analyte resolution if absent).")
@click.option("--screening", default=None, type=click.Path(exists=True),
              help="Screening levels YAML (optional).")
@click.option("--event-date", default=None,
              help="Override event date ISO8601 (YYYY-MM-DD).")
def import_edd_cmd(edd_path, profile_path, site_id, gdb_path,
                   analytes, screening, event_date):
    """Tool 2.3: import a lab EDD CSV/XLSX into the envmon GDB (needs ArcGIS Pro)."""
    _guard("LOCAL")
    from autogis.core.envmon.edd_profile import LabEDDProfile
    from autogis.core.envmon.edd_importer import run_edd_import
    from autogis.core.common.config import load_config

    profile = LabEDDProfile.load(Path(profile_path))
    analyte_dictionary = load_config(Path(analytes)) if analytes else {}
    screening_levels = load_config(Path(screening)) if screening else {}

    override = None
    if event_date:
        from datetime import date as _date
        try:
            override = _date.fromisoformat(event_date)
        except ValueError:
            raise click.BadParameter(f"Invalid date '{event_date}'; use YYYY-MM-DD")

    batch_id = run_edd_import(
        edd_path=Path(edd_path),
        profile=profile,
        gdb_path=Path(gdb_path),
        site_id=site_id,
        analyte_dictionary=analyte_dictionary,
        screening_levels=screening_levels,
        event_date_override=override,
    )
    click.echo(f"Import complete. Batch ID: {batch_id}")
```

- [ ] **Step 4: Run test to confirm it passes**

```
python -m pytest tests/test_cli_envmon.py::test_import_edd_missing_gdb_exits_nonzero -v
```
Expected: PASS (command exists and errors cleanly on missing GDB)

- [ ] **Step 5: Run full suite — no regressions**

```
python -m pytest -q
```
Expected: All tests pass.

- [ ] **Step 6: Commit**

```
git add autogis/adapters/cli.py tests/test_cli_envmon.py
git commit -m "feat(cli): add envmon import-edd command (Tool 2.3)"
```

---

## Self-Review

**Spec coverage:**
- ✅ `LabEDDProfile` dataclass + `load()` + `resolve_column()` — Task 2
- ✅ `validate_edd_profile()` — Task 2
- ✅ `testamerica.yaml` reference profile — Task 2
- ✅ `read_edd_file()` flat_csv + two_tab_xlsx — Task 3
- ✅ `normalize_edd_rows()` full per-row pipeline — Task 3
- ✅ `apply_qualifiers` exposed — Task 1
- ✅ `run_edd_import()` full lifecycle — Task 4
- ✅ CLI `import-edd` command — Task 5
- ✅ All core tests arcpy-free
- ✅ `import_to_gdb.py` not modified — only called

**Placeholder scan:** No TBD/TODO. All code blocks are complete implementations.

**Type consistency:**
- `normalize_edd_rows` → `tuple[list[SampleRecord], list[AnalyticalResultRecord]]` — matches Task 4 monkeypatch test destructuring
- `LabEDDProfile.resolve_column` → `str | None` — matches all callers in Task 3
- `run_edd_import` → `str` (batch_id) — matches `assert batch_id == "BATCH-001"` in test
- `create_import_batch` stub signature: `(gdb_path, **kw)` — monkeypatch test passes `site_id`, `source_workbook` as kwargs ✅
