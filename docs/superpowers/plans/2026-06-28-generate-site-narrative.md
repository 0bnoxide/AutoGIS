# GenerateSiteNarrative Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Implement `GenerateSiteNarrative` — deterministic template-driven text narrative from envmon structured data; highest detections, exceedance changes, sampling completeness sections; outputs Markdown file.
See spec: `docs/superpowers/specs/2026-06-28-generate-site-narrative-design.md`.

**Architecture:**
- New: `autogis/core/envmon/site_narrative_generator.py`
- Modify: `autogis/adapters/cli.py` — add `generate-site-narrative` command (headless)
- New: `tests/envmon/test_site_narrative_generator.py`

## Global Constraints

- Arcpy-free. stdlib only: `csv`, `datetime`.
- No LLM integration. Deterministic templates only.
- Run tests with `python -m pytest -q`.

---

### Task 1: Core `site_narrative_generator.py`

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_site_narrative_generator.py`:

```python
from pathlib import Path
import pytest
from autogis.core.envmon.site_narrative_generator import (
    NarrativeSection, SiteNarrativeResult,
    build_highest_detections_section,
    build_exceedance_change_section,
    build_not_sampled_section,
    generate_site_narrative,
)

_MAX_RESULTS = [
    {"location_id": "MW-01", "analyte_name": "Benzene",
     "max_result_value": "12.0", "max_sample_date": "2026-06-15",
     "reported_units": "ug/L", "exceedance_ratio": "2.4", "has_exceedance": "True"},
    {"location_id": "MW-02", "analyte_name": "Toluene",
     "max_result_value": "85.0", "max_sample_date": "2026-06-15",
     "reported_units": "ug/L", "exceedance_ratio": "", "has_exceedance": "False"},
    {"location_id": "MW-03", "analyte_name": "Benzene",
     "max_result_value": "0.5", "max_sample_date": "2026-06-15",
     "reported_units": "ug/L", "exceedance_ratio": "0.1", "has_exceedance": "False"},
]

_CHANGE_LOG = [
    {"change_type": "exceedance_new", "location_id": "MW-04",
     "analyte_name": "Benzene", "new_value": "6.0", "old_value": "ND",
     "event_date": "2026-06-15"},
    {"change_type": "exceedance_resolved", "location_id": "MW-05",
     "analyte_name": "Arsenic", "new_value": "ND", "old_value": "12.0",
     "event_date": "2026-06-15"},
]

_PLAN = [
    {"SampleID": "S1", "LocationID": "MW-01"},
    {"SampleID": "S2", "LocationID": "MW-02"},
    {"SampleID": "S3", "LocationID": "MW-03"},
]
_RESULTS = [
    {"SampleID": "S1"}, {"SampleID": "S2"},
    # S3/MW-03 not in results
]


def test_highest_detections_top_n():
    section = build_highest_detections_section(_MAX_RESULTS, top_n=2)
    assert isinstance(section, NarrativeSection)
    assert "MW-01" in section.text
    assert "Benzene" in section.text


def test_highest_detections_exceedance_mentioned():
    section = build_highest_detections_section(_MAX_RESULTS, top_n=3,
                                               screening_levels={"Benzene": 5.0})
    assert "exceed" in section.text.lower() or "MCL" in section.text


def test_exceedance_change_new():
    section = build_exceedance_change_section(_CHANGE_LOG)
    assert "MW-04" in section.text
    assert "new exceedance" in section.text.lower() or "exceedance_new" in section.text.lower()


def test_exceedance_change_resolved():
    section = build_exceedance_change_section(_CHANGE_LOG)
    assert "MW-05" in section.text


def test_not_sampled_section():
    section = build_not_sampled_section(_PLAN, _RESULTS)
    assert "MW-03" in section.text


def test_all_sampled_no_missing():
    plan = [{"SampleID": "S1", "LocationID": "MW-01"}]
    results = [{"SampleID": "S1"}]
    section = build_not_sampled_section(plan, results)
    assert "all" in section.text.lower() or "0" in section.text


def test_generate_narrative_full_text(tmp_path):
    result = generate_site_narrative(
        "H281", "Q1-2026",
        max_result_rows=_MAX_RESULTS,
        change_log_rows=_CHANGE_LOG,
        plan_rows=_PLAN,
        result_rows=_RESULTS,
    )
    assert len(result.full_text) > 50
    assert "H281" in result.full_text or "Q1-2026" in result.full_text


def test_generate_narrative_max_only(tmp_path):
    result = generate_site_narrative(
        "H281", "Q1-2026",
        max_result_rows=_MAX_RESULTS,
    )
    assert result.full_text
    assert "MW-01" in result.full_text
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_site_narrative_generator.py -v
```

- [ ] **Step 3: Create `autogis/core/envmon/site_narrative_generator.py`**

```python
"""site_narrative_generator.py — deterministic template-driven site narrative."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..common.qa import QACollector, QARecord, SEV_INFO


@dataclass
class NarrativeSection:
    heading: str
    text: str
    data_rows: list = field(default_factory=list)


@dataclass
class SiteNarrativeResult:
    sections: list
    full_text: str
    site_id: str
    event_label: str
    qa: QACollector


def _parse_float(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def build_highest_detections_section(
    max_result_rows: list,
    *,
    top_n: int = 5,
    screening_levels: Optional[dict] = None,
) -> NarrativeSection:
    sl = screening_levels or {}

    # Sort by max_result_value desc
    sortable = []
    for r in max_result_rows:
        val = _parse_float(r.get("max_result_value", ""))
        if val is not None:
            sortable.append((val, r))
    sortable.sort(key=lambda x: -x[0])
    top = [r for _, r in sortable[:top_n]]

    if not top:
        text = "No detections were reported during this monitoring event.\n"
        return NarrativeSection("Highest Detections", text, [])

    lines = []
    for r in top:
        loc = r.get("location_id", "")
        analyte = r.get("analyte_name", "")
        val = r.get("max_result_value", "")
        units = r.get("reported_units", "ug/L")
        date = r.get("max_sample_date", "")
        ratio_str = r.get("exceedance_ratio", "")
        ratio = _parse_float(ratio_str)
        mcl = sl.get(analyte)
        if ratio and ratio >= 1.0 and mcl:
            exceed_clause = (f", which exceeded the MCL of {mcl} {units} "
                             f"({ratio:.1f}×)")
        else:
            exceed_clause = ""
        lines.append(
            f"The highest concentration of {analyte} was {val} {units} at "
            f"{loc} (sampled {date}){exceed_clause}."
        )

    text = "\n".join(lines) + "\n"
    return NarrativeSection("Highest Detections", text, top)


def build_exceedance_change_section(change_log_rows: list) -> NarrativeSection:
    new_exc = [r for r in change_log_rows
               if r.get("change_type", "") == "exceedance_new"]
    resolved = [r for r in change_log_rows
                if r.get("change_type", "") == "exceedance_resolved"]

    lines = []
    if new_exc:
        lines.append("The following new exceedances were identified this event:")
        for r in new_exc:
            lines.append(f"  - {r.get('analyte_name', '')} at "
                         f"{r.get('location_id', '')} "
                         f"({r.get('new_value', '')} vs. previous ND).")
    else:
        lines.append("No new exceedances were identified this event.")

    if resolved:
        lines.append("\nThe following previously reported exceedances were resolved:")
        for r in resolved:
            lines.append(f"  - {r.get('analyte_name', '')} at "
                         f"{r.get('location_id', '')} "
                         f"(previously {r.get('old_value', '')}, now ND).")
    else:
        lines.append("No previously identified exceedances were resolved this event.")

    text = "\n".join(lines) + "\n"
    return NarrativeSection("Exceedance Changes", text, change_log_rows)


def build_not_sampled_section(
    plan_rows: list,
    result_rows: list,
) -> NarrativeSection:
    plan_ids = {r.get("SampleID", "") for r in plan_rows}
    result_ids = {r.get("SampleID", "") for r in result_rows}
    missing_ids = sorted(plan_ids - result_ids)

    # Map SampleID → LocationID from plan
    id_to_loc = {r.get("SampleID", ""): r.get("LocationID", "")
                 for r in plan_rows}
    missing_locs = [id_to_loc.get(sid, sid) for sid in missing_ids]

    if not missing_locs:
        text = ("All scheduled monitoring locations were sampled during "
                "this event.\n")
    else:
        text = (f"The following {len(missing_locs)} location(s) were not "
                f"sampled during this event: "
                f"{', '.join(missing_locs)}.\n")

    return NarrativeSection("Sampling Completeness", text, [])


def generate_site_narrative(
    site_id: str,
    event_label: str,
    *,
    max_result_rows: Optional[list] = None,
    max_result_path: Optional[Path] = None,
    change_log_rows: Optional[list] = None,
    change_log_path: Optional[Path] = None,
    plan_rows: Optional[list] = None,
    plan_path: Optional[Path] = None,
    result_rows: Optional[list] = None,
    result_path: Optional[Path] = None,
    screening_levels: Optional[dict] = None,
    top_n: int = 5,
    qa: Optional[QACollector] = None,
) -> SiteNarrativeResult:
    if qa is None:
        qa = QACollector()

    def _read_csv(path):
        with Path(path).open(newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))

    mr_rows = max_result_rows or (_read_csv(max_result_path) if max_result_path else [])
    cl_rows = change_log_rows or (_read_csv(change_log_path) if change_log_path else [])
    pl_rows = plan_rows or (_read_csv(plan_path) if plan_path else [])
    rs_rows = result_rows or (_read_csv(result_path) if result_path else [])

    sections = []
    header_text = f"# Site Narrative — {site_id} — {event_label}\n\n"

    if mr_rows:
        sections.append(build_highest_detections_section(
            mr_rows, top_n=top_n, screening_levels=screening_levels))

    if cl_rows:
        sections.append(build_exceedance_change_section(cl_rows))

    if pl_rows or rs_rows:
        sections.append(build_not_sampled_section(pl_rows, rs_rows))

    parts = [header_text]
    for s in sections:
        parts.append(f"## {s.heading}\n\n{s.text}\n")
    full_text = "\n".join(parts)

    qa.add(QARecord(SEV_INFO, "narrative_generated",
                    f"{len(sections)} sections for {site_id} {event_label}"))

    return SiteNarrativeResult(
        sections=sections, full_text=full_text,
        site_id=site_id, event_label=event_label, qa=qa,
    )
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_site_narrative_generator.py -v
```

Expected: all 8 PASS.

- [ ] **Step 5: Full suite + commit**

```bash
git add autogis/core/envmon/site_narrative_generator.py \
        tests/envmon/test_site_narrative_generator.py
git commit -m "feat(envmon): site_narrative_generator — deterministic template-driven report narrative"
```

---

### Task 2: CLI command

- [ ] **Step 1: Add to `cli.py`**

```python
@envmon.command("generate-site-narrative")
@click.option("--site", "site_id", required=True)
@click.option("--event-label", required=True)
@click.option("--max-results", "max_results_path", default=None,
              type=click.Path(exists=True))
@click.option("--change-log", "change_log_path", default=None,
              type=click.Path(exists=True))
@click.option("--plan", "plan_path", default=None, type=click.Path(exists=True))
@click.option("--results", "results_path", default=None, type=click.Path(exists=True))
@click.option("--screening-levels", "sl_path", default=None, type=click.Path(exists=True))
@click.option("--top-n", type=int, default=5, show_default=True)
@click.option("--out", required=True, type=click.Path())
@click.option("--report", default=None, type=click.Path())
def generate_site_narrative_cmd(site_id, event_label, max_results_path,
                                 change_log_path, plan_path, results_path,
                                 sl_path, top_n, out, report):
    """Generate template-driven site monitoring narrative (headless)."""
    import yaml as _yaml
    from autogis.core.envmon.site_narrative_generator import generate_site_narrative

    sl = _yaml.safe_load(Path(sl_path).read_text()) if sl_path else None
    result = generate_site_narrative(
        site_id, event_label,
        max_result_path=Path(max_results_path) if max_results_path else None,
        change_log_path=Path(change_log_path) if change_log_path else None,
        plan_path=Path(plan_path) if plan_path else None,
        result_path=Path(results_path) if results_path else None,
        screening_levels=sl, top_n=top_n,
    )
    Path(out).write_text(result.full_text, encoding="utf-8")
    click.echo(f"Sections: {len(result.sections)}  Output: {out}")
    _render_qa(result.qa, report, "warning")
```

- [ ] **Step 2: Help test + commit**

```python
def test_generate_site_narrative_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "generate-site-narrative" in result.output
```

```bash
git add autogis/adapters/cli.py tests/envmon/test_site_narrative_generator.py
git commit -m "feat(cli): add generate-site-narrative command"
```
