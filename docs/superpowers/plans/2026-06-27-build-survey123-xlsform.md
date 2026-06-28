# BuildSurvey123XLSFormFromConfig Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Implement `BuildSurvey123XLSFormFromConfig` — a headless openpyxl tool that
generates an XLSForm `.xlsx` file from site config + event config + analyte dictionary.
See ADR: `docs/adr/0021-survey123-xlsform-builder-headless-openpyxl.md`.

**Architecture:**
- New: `autogis/core/envmon/survey123_form_builder.py`
- New: `autogis/config/event_configs/event_config.example.yaml`
- Modify: `autogis/adapters/cli.py` — add `build-survey-form` command (headless)
- New: `tests/envmon/test_survey123_form_builder.py`

## Global Constraints

- Branch: `feat/gdb-schema-upgrade`
- No arcpy imports anywhere in `survey123_form_builder.py`.
- openpyxl is already a project dependency — no new packages.
- XLSForm output must have sheets: `survey`, `choices`, `settings`.
- Run tests with `python -m pytest -q`.

---

### Task 1: `Survey123FormConfig` dataclass + `event_config.example.yaml`

**Files:**
- Create: `autogis/core/envmon/survey123_form_builder.py` (stub)
- Create: `autogis/config/event_configs/event_config.example.yaml`

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_survey123_form_builder.py`:

```python
import pytest
from pathlib import Path
from autogis.core.envmon.survey123_form_builder import (
    Survey123FormConfig, load_event_config, build_xlsform,
)

_EVENT_YAML = """\
event_id: "2026Q2"
matrices: [GW]
crew_list: [Alice, Bob]
coc_prefix: "H281"
analyte_groups:
  Volatiles: [Benzene, Toluene]
  Metals: [Arsenic, Lead]
"""

_ANALYTES = {
    "Benzene": {"canonical_name": "Benzene", "abbreviation": "BNZ",
                "default_units_by_matrix": {"GW": "ug/L"}},
    "Toluene": {"canonical_name": "Toluene", "abbreviation": "TOL",
                "default_units_by_matrix": {"GW": "ug/L"}},
    "Arsenic": {"canonical_name": "Arsenic", "abbreviation": "As",
                "default_units_by_matrix": {"GW": "ug/L"}},
    "Lead": {"canonical_name": "Lead", "abbreviation": "Pb",
             "default_units_by_matrix": {"GW": "ug/L"}},
}


def test_load_event_config(tmp_path):
    f = tmp_path / "event.yaml"
    f.write_text(_EVENT_YAML, encoding="utf-8")
    cfg = load_event_config(f)
    assert cfg.event_id == "2026Q2"
    assert "Volatiles" in cfg.analyte_groups
    assert "Alice" in cfg.crew_list


def test_build_xlsform_creates_xlsx(tmp_path):
    f = tmp_path / "event.yaml"
    f.write_text(_EVENT_YAML, encoding="utf-8")
    cfg = load_event_config(f)
    out = tmp_path / "form.xlsx"
    build_xlsform(cfg, _ANALYTES, out)
    assert out.exists()


def test_build_xlsform_has_three_sheets(tmp_path):
    import openpyxl
    f = tmp_path / "event.yaml"
    f.write_text(_EVENT_YAML, encoding="utf-8")
    cfg = load_event_config(f)
    out = tmp_path / "form.xlsx"
    build_xlsform(cfg, _ANALYTES, out)
    wb = openpyxl.load_workbook(out)
    assert set(wb.sheetnames) == {"survey", "choices", "settings"}


def test_survey_sheet_has_wellid_question(tmp_path):
    import openpyxl
    f = tmp_path / "event.yaml"
    f.write_text(_EVENT_YAML, encoding="utf-8")
    cfg = load_event_config(f)
    out = tmp_path / "form.xlsx"
    build_xlsform(cfg, _ANALYTES, out)
    wb = openpyxl.load_workbook(out)
    ws = wb["survey"]
    names = [ws.cell(row=r, column=2).value for r in range(1, ws.max_row + 1)]
    assert "WellID" in names


def test_choices_sheet_has_crew_options(tmp_path):
    import openpyxl
    f = tmp_path / "event.yaml"
    f.write_text(_EVENT_YAML, encoding="utf-8")
    cfg = load_event_config(f)
    out = tmp_path / "form.xlsx"
    build_xlsform(cfg, _ANALYTES, out)
    wb = openpyxl.load_workbook(out)
    ws = wb["choices"]
    names = [ws.cell(row=r, column=3).value for r in range(1, ws.max_row + 1)]
    assert "Alice" in names


def test_analyte_field_label_includes_units(tmp_path):
    import openpyxl
    f = tmp_path / "event.yaml"
    f.write_text(_EVENT_YAML, encoding="utf-8")
    cfg = load_event_config(f)
    out = tmp_path / "form.xlsx"
    build_xlsform(cfg, _ANALYTES, out)
    wb = openpyxl.load_workbook(out)
    ws = wb["survey"]
    labels = [ws.cell(row=r, column=4).value for r in range(1, ws.max_row + 1)
              if ws.cell(row=r, column=4).value]
    assert any("ug/L" in str(lbl) for lbl in labels)
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_survey123_form_builder.py -v
```

- [ ] **Step 3: Create example event config**

```yaml
# autogis/config/event_configs/event_config.example.yaml
event_id: "2026Q2"
matrices: [GW]
crew_list: [Field Crew A, Field Crew B]
coc_prefix: "H281-2026Q2"
analyte_groups:
  Volatiles (VPH/EPH):
    - Benzene
    - Toluene
    - Xylenes
  Priority Metals:
    - Arsenic
    - Lead
```

- [ ] **Step 4: Create `autogis/core/envmon/survey123_form_builder.py`**

```python
"""survey123_form_builder.py — generate XLSForm XLSX from site/event config.

Headless (no arcpy). openpyxl writes the output workbook.
XLSForm spec: survey/choices/settings sheets.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import openpyxl
from openpyxl.styles import Font

from ..common.config import load_config


@dataclass
class Survey123FormConfig:
    event_id: str
    matrices: list[str]
    crew_list: list[str]
    coc_prefix: str
    analyte_groups: dict[str, list[str]]   # group_name → [canonical analyte names]
    well_list: list[str] = field(default_factory=list)


def load_event_config(path: Path) -> Survey123FormConfig:
    data = load_config(path)
    return Survey123FormConfig(
        event_id=data.get("event_id", ""),
        matrices=data.get("matrices", ["GW"]),
        crew_list=data.get("crew_list", []),
        coc_prefix=data.get("coc_prefix", ""),
        analyte_groups=data.get("analyte_groups", {}),
        well_list=data.get("well_list", []),
    )


# ---------------------------------------------------------------------------
# XLSForm builder
# ---------------------------------------------------------------------------
_SURVEY_COLS = ["type", "name", "label", "hint", "required", "calculation",
                "appearance", "constraint", "constraint_message"]
_CHOICES_COLS = ["list_name", "name", "label"]
_SETTINGS_COLS = ["form_title", "form_id", "version"]


def _hrow(ws, cols: list[str]) -> None:
    for i, c in enumerate(cols, 1):
        cell = ws.cell(row=1, column=i, value=c)
        cell.font = Font(bold=True)


def build_xlsform(
    config: Survey123FormConfig,
    analyte_dictionary: dict,
    out_path: Path,
) -> None:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    survey = wb.create_sheet("survey")
    choices = wb.create_sheet("choices")
    settings = wb.create_sheet("settings")

    _hrow(survey, _SURVEY_COLS)
    _hrow(choices, _CHOICES_COLS)
    _hrow(settings, _SETTINGS_COLS)

    sr = 2  # survey row pointer
    cr = 2  # choices row pointer

    def s(*vals):
        nonlocal sr
        for i, v in enumerate(vals, 1):
            survey.cell(row=sr, column=i, value=v)
        sr += 1

    def c(list_name, name, label):
        nonlocal cr
        choices.cell(row=cr, column=1, value=list_name)
        choices.cell(row=cr, column=2, value=name)
        choices.cell(row=cr, column=3, value=label)
        cr += 1

    # --- WellID (select_one from well_list choice) ---
    for wid in (config.well_list or []):
        c("well_list", wid, wid)
    s("select_one well_list", "WellID", "Well ID", "", "yes")

    # --- SamplingDate ---
    s("date", "SamplingDate", "Sampling Date", "", "yes")

    # --- Matrix (select_one) ---
    for m in config.matrices:
        c("matrix_list", m, m)
    s("select_one matrix_list", "Matrix", "Sample Matrix", "", "yes")

    # --- SampleID (calculate) ---
    calc = "concat(${WellID}, \"-\", format-date(${SamplingDate}, \"%Y%m%d\"), \"-\", ${Matrix})"
    s("calculate", "SampleID", "Sample ID (auto)", "", "", calc)
    s("note", "SampleID_display", "${SampleID}")

    # --- SampledBy (select_one) ---
    for crew in config.crew_list:
        c("crew_list", crew.replace(" ", "_"), crew)
    s("select_one crew_list", "SampledBy", "Sampled By", "", "yes")

    # --- COCNumber ---
    s("text", "COCNumber", "COC Number", config.coc_prefix + "-")

    # --- Analyte groups ---
    for group_name, analytes in config.analyte_groups.items():
        s("begin_group", group_name.replace(" ", "_"), group_name)
        for analyte in analytes:
            info = analyte_dictionary.get(analyte, {})
            abbr = info.get("abbreviation", analyte)
            units_map = info.get("default_units_by_matrix", {})
            units_str = ", ".join(
                f"{m}: {u}" for m, u in units_map.items()
                if m in config.matrices) or ""
            label = f"{abbr} ({units_str})" if units_str else abbr
            safe_name = analyte.replace(" ", "_").replace(",", "").replace("/", "_")
            s("decimal", safe_name, label, "Enter result or ND")
        s("end_group", "", "")

    # --- DepthToWater_ft (GW hint) ---
    if "GW" in config.matrices:
        s("decimal", "DepthToWater_ft", "Depth to Water (ft)",
          "Measured before purging", "no")

    # --- Notes ---
    s("text", "Notes", "Notes / Observations")

    # --- settings ---
    settings.cell(row=2, column=1, value=f"AutoGIS Survey - {config.event_id}")
    settings.cell(row=2, column=2, value=f"autogis_{config.event_id}")
    settings.cell(row=2, column=3, value="1")

    wb.save(out_path)
```

- [ ] **Step 5: Run tests**

```
python -m pytest tests/envmon/test_survey123_form_builder.py -v
```

Expected: all 6 PASS.

- [ ] **Step 6: Full suite + commit**

```bash
git add autogis/core/envmon/survey123_form_builder.py \
        autogis/config/event_configs/event_config.example.yaml \
        tests/envmon/test_survey123_form_builder.py
git commit -m "feat(envmon): survey123_form_builder — headless XLSForm generator (ADR-021)"
```

---

### Task 2: CLI command

- [ ] **Step 1: Add to `cli.py`** (headless — no guard)

```python
@envmon.command("build-survey-form")
@click.option("--event", "event_path", required=True, type=click.Path(exists=True),
              help="event_config.yaml")
@click.option("--analytes", required=True, type=click.Path(exists=True))
@click.option("--out", "out_path", required=True, type=click.Path(),
              help="Output .xlsx path.")
def build_survey_form_cmd(event_path, analytes, out_path):
    """Generate a Survey123 XLSForm from event and analyte configs (headless)."""
    from autogis.core.common.config import load_analyte_dictionary
    from autogis.core.envmon.survey123_form_builder import (
        load_event_config, build_xlsform)
    cfg = load_event_config(Path(event_path))
    analyte_dict = load_analyte_dictionary(Path(analytes))
    build_xlsform(cfg, analyte_dict, Path(out_path))
    click.echo(f"XLSForm written: {out_path}")
```

- [ ] **Step 2: Help test + commit**

```python
def test_build_survey_form_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "build-survey-form" in result.output
```

```bash
git add autogis/adapters/cli.py tests/envmon/test_survey123_form_builder.py
git commit -m "feat(cli): add build-survey-form command (headless, ADR-021)"
```
