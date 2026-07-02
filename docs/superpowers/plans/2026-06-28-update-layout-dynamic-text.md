# UpdateLayoutDynamicText Implementation Plan

> **SUPERSEDED (2026-07-02, ADR-0041) — do not execute this plan.** The
> `layout_text_updater.py` module (Task 1) would duplicate
> `autogis/core/envmon/layout_manager.py::update_layout_text()`, which
> already shipped and is more capable (named elements *and*
> `{{placeholder}}` resolution). Tool 5.8 was implemented as the
> `envmon update-layout-text` CLI command calling that existing function,
> plus a small YAML loader (`load_layout_text_yaml`, adapted from this
> plan's `load_substitutions_from_yaml`) in `layout_manager.py`. Kept for
> historical record only.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Implement `UpdateLayoutDynamicText` — update text elements in an ArcGIS Pro APRX layout (title, date, site name, event ID, preparer) from a YAML values file, with arcpy-free substitution logic and arcpy-only APRX write.
See spec: `docs/superpowers/specs/2026-06-28-update-layout-dynamic-text-design.md`.

**Architecture:**
- New: `autogis/core/envmon/layout_text_updater.py`
- Modify: `autogis/adapters/cli.py` — add `update-layout-text` command (LOCAL, `_guard`)
- New: `tests/envmon/test_layout_text_updater.py`

## Global Constraints

- `apply_substitutions` and `load_substitutions_from_yaml` are arcpy-free and fully testable.
- `update_layout_text` is LOCAL (`# pragma: no cover`); `import arcpy` stays inside the function body.
- `QACollector` / `QARecord` from `autogis.core.common.qa`.
- Mock layout elements with `types.SimpleNamespace(text="...")` — no arcpy needed in tests.
- Run tests with `python -m pytest -q`.

---

### Task 1: Core `layout_text_updater.py`

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_layout_text_updater.py`:

```python
import types
from pathlib import Path
import pytest
from autogis.core.envmon.layout_text_updater import (
    TextSubstitution, LayoutTextUpdateResult,
    apply_substitutions, load_substitutions_from_yaml,
)


def _make_elements(*names: str) -> dict:
    """Build a fake element dict of {name: SimpleNamespace(text="")}."""
    return {n: types.SimpleNamespace(text="") for n in names}


def _make_yaml(tmp_path: Path, mapping: dict) -> Path:
    import yaml
    p = tmp_path / "values.yaml"
    p.write_text(yaml.dump(mapping), encoding="utf-8")
    return p


# --- apply_substitutions ---

def test_all_found_in_updated(tmp_path):
    elements = _make_elements("Title", "DateText", "SiteName")
    subs = [
        TextSubstitution(element_name="Title", new_text="Site H281 Report"),
        TextSubstitution(element_name="DateText", new_text="2026-06-28"),
        TextSubstitution(element_name="SiteName", new_text="H281"),
    ]
    result = apply_substitutions(subs, elements)
    assert set(result.updated) == {"Title", "DateText", "SiteName"}
    assert result.not_found == []


def test_text_attribute_set():
    elements = _make_elements("Title")
    subs = [TextSubstitution(element_name="Title", new_text="Quarterly Report")]
    apply_substitutions(subs, elements)
    assert elements["Title"].text == "Quarterly Report"


def test_missing_element_in_not_found():
    elements = _make_elements("Title")
    subs = [
        TextSubstitution(element_name="Title", new_text="Report"),
        TextSubstitution(element_name="Ghost", new_text="Never"),
    ]
    result = apply_substitutions(subs, elements)
    assert "Ghost" in result.not_found
    assert "Title" in result.updated


def test_not_found_warning_in_qa():
    elements = _make_elements("Title")
    subs = [TextSubstitution(element_name="Missing", new_text="x")]
    result = apply_substitutions(subs, elements)
    assert any(r.severity == "WARNING" for r in result.qa.records)


def test_empty_substitutions():
    elements = _make_elements("Title", "DateText")
    result = apply_substitutions([], elements)
    assert result.updated == []
    assert result.not_found == []


def test_empty_elements_all_not_found():
    subs = [TextSubstitution(element_name="Title", new_text="X")]
    result = apply_substitutions(subs, {})
    assert "Title" in result.not_found
    assert result.updated == []


def test_result_is_layouttextupdateresult():
    result = apply_substitutions([], {})
    assert isinstance(result, LayoutTextUpdateResult)


# --- load_substitutions_from_yaml ---

def test_load_yaml_flat_mapping(tmp_path):
    p = _make_yaml(tmp_path, {"Title": "H281 Q2 Report", "DateText": "2026-06-28"})
    subs = load_substitutions_from_yaml(p)
    names = {s.element_name for s in subs}
    assert "Title" in names
    assert "DateText" in names


def test_load_yaml_flat_values(tmp_path):
    p = _make_yaml(tmp_path, {"SiteName": "Site Alpha"})
    subs = load_substitutions_from_yaml(p)
    assert subs[0].new_text == "Site Alpha"


def test_load_yaml_list_form(tmp_path):
    import yaml
    data = [
        {"element_name": "Title", "text": "Report Title"},
        {"element_name": "EventID", "text": "Q2-2026"},
    ]
    p = tmp_path / "list.yaml"
    p.write_text(yaml.dump(data), encoding="utf-8")
    subs = load_substitutions_from_yaml(p)
    assert len(subs) == 2
    assert subs[0].element_name == "Title"
    assert subs[1].new_text == "Q2-2026"


def test_load_yaml_returns_list_of_substitutions(tmp_path):
    p = _make_yaml(tmp_path, {"Title": "T"})
    subs = load_substitutions_from_yaml(p)
    assert all(isinstance(s, TextSubstitution) for s in subs)


def test_load_yaml_empty_mapping(tmp_path):
    p = _make_yaml(tmp_path, {})
    assert load_substitutions_from_yaml(p) == []
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_layout_text_updater.py -v
```

- [ ] **Step 3: Create `autogis/core/envmon/layout_text_updater.py`**

```python
"""layout_text_updater.py — update text elements in an ArcGIS Pro APRX layout."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..common.qa import QACollector, QARecord, SEV_INFO, SEV_WARNING


@dataclass
class TextSubstitution:
    element_name: str
    new_text: str


@dataclass
class LayoutTextUpdateResult:
    updated: list = field(default_factory=list)
    not_found: list = field(default_factory=list)
    qa: QACollector = field(default_factory=QACollector)


def apply_substitutions(
    substitutions: list,
    layout_elements: dict,
    *,
    qa: Optional[QACollector] = None,
) -> LayoutTextUpdateResult:
    """Pure-logic substitution: set .text on matching element objects.

    ``layout_elements`` is ``{element_name: element_object}`` where each
    element object exposes a writable ``.text`` attribute (arcpy layout
    element or a plain ``types.SimpleNamespace`` in tests).
    """
    if qa is None:
        qa = QACollector()
    updated: list[str] = []
    not_found: list[str] = []

    for sub in substitutions:
        if sub.element_name in layout_elements:
            layout_elements[sub.element_name].text = sub.new_text
            updated.append(sub.element_name)
            qa.add(QARecord(SEV_INFO, "element_updated",
                            f"Set '{sub.element_name}' → '{sub.new_text}'"))
        else:
            not_found.append(sub.element_name)
            qa.add(QARecord(SEV_WARNING, "element_not_found",
                            f"Layout element '{sub.element_name}' not found; skipped."))

    return LayoutTextUpdateResult(updated=updated, not_found=not_found, qa=qa)


def load_substitutions_from_yaml(path: Path) -> list:
    """Load substitutions from YAML.

    Accepted forms:
    - Flat mapping: ``{ElementName: "new text", ...}``
    - List of dicts: ``[{element_name: ..., text: ...}, ...]``
    """
    import yaml

    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not raw:
        return []

    if isinstance(raw, dict):
        return [TextSubstitution(element_name=k, new_text=str(v))
                for k, v in raw.items()]

    if isinstance(raw, list):
        return [TextSubstitution(element_name=entry["element_name"],
                                 new_text=str(entry["text"]))
                for entry in raw]

    raise ValueError(f"Unexpected YAML structure in {path}: {type(raw)}")


def update_layout_text(  # pragma: no cover
    aprx_path: str,
    layout_name: str,
    substitutions: list,
    *,
    dry_run: bool = False,
    qa: Optional[QACollector] = None,
) -> LayoutTextUpdateResult:
    """Open APRX, locate layout, apply substitutions, save (unless dry_run).

    Requires ArcGIS Pro (arcpy). Core substitution logic lives in
    ``apply_substitutions``; this function only handles APRX I/O.
    """
    import arcpy  # noqa: F401

    if qa is None:
        qa = QACollector()

    aprx = arcpy.mp.ArcGISProject(str(aprx_path))
    layouts = [lyt for lyt in aprx.listLayouts() if lyt.name == layout_name]
    if not layouts:
        available = [lyt.name for lyt in aprx.listLayouts()]
        qa.add(QARecord(SEV_WARNING, "layout_not_found",
                        f"Layout '{layout_name}' not found. "
                        f"Available: {available}"))
        return LayoutTextUpdateResult(qa=qa)

    layout = layouts[0]
    elements = {el.name: el for el in layout.listElements("TEXT_ELEMENT")}

    result = apply_substitutions(substitutions, elements, qa=qa)

    if not dry_run:
        aprx.save()
        qa.add(QARecord(SEV_INFO, "aprx_saved",
                        f"Saved APRX: {aprx_path}"))
    else:
        qa.add(QARecord(SEV_INFO, "dry_run",
                        "Dry-run: changes not saved."))

    return result
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_layout_text_updater.py -v
```

Expected: all 12 PASS.

- [ ] **Step 5: Full suite + commit**

```bash
git add autogis/core/envmon/layout_text_updater.py \
        tests/envmon/test_layout_text_updater.py
git commit -m "feat(envmon): layout_text_updater — arcpy-free substitution logic + APRX write"
```

---

### Task 2: CLI command

- [ ] **Step 1: Add to `cli.py`**

```python
@envmon.command("update-layout-text")
@click.option("--aprx", "aprx_path", required=True, type=click.Path(),
              help="Path to .aprx project file.")
@click.option("--layout", "layout_name", required=True,
              help="Layout name inside the APRX.")
@click.option("--values", "values_path", required=True, type=click.Path(exists=True),
              help="YAML file mapping element names to new text values.")
@click.option("--dry-run", is_flag=True, default=False,
              help="Apply substitutions but do not save the APRX.")
@click.option("--report", default=None, type=click.Path())
def update_layout_text_cmd(aprx_path, layout_name, values_path, dry_run, report):
    """Update APRX layout text elements from a YAML values file (LOCAL)."""
    _guard("update-layout-text")
    from autogis.core.envmon.layout_text_updater import (
        load_substitutions_from_yaml, update_layout_text)
    from autogis.core.common.qa import QACollector

    subs = load_substitutions_from_yaml(Path(values_path))
    qa = QACollector()
    result = update_layout_text(
        aprx_path, layout_name, subs, dry_run=dry_run, qa=qa)
    click.echo(
        f"Updated: {len(result.updated)}  "
        f"Not found: {len(result.not_found)}"
        + ("  [dry-run]" if dry_run else "")
    )
    if result.not_found:
        click.echo(f"  Missing elements: {', '.join(result.not_found)}", err=True)
    _render_qa(qa, report, "warning")
```

- [ ] **Step 2: Help test + commit**

```python
def test_update_layout_text_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "update-layout-text" in result.output
```

```bash
git add autogis/adapters/cli.py tests/envmon/test_layout_text_updater.py
git commit -m "feat(cli): add update-layout-text command (LOCAL)"
```
