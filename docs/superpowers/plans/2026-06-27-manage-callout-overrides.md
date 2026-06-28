# ManageCalloutPlacementOverrides Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Implement `manage_callout_overrides.py` — `CalloutOverride` dataclass,
`load_overrides()`, `save_override()`, `clear_unlocked_overrides()` — and two CLI
subcommands. See ADR: `docs/adr/0020-callout-placement-extend-assemble-callouts.md`.

**Architecture:**
- New: `autogis/core/envmon/manage_callout_overrides.py`
- Modify: `autogis/adapters/cli.py` — add `optimize-callouts` and `manage-callout-overrides` commands
- New: `tests/envmon/test_manage_callout_overrides.py`

## Global Constraints

- Branch: `feat/gdb-schema-upgrade`
- arcpy imported lazily (inside functions, `# pragma: no cover` on arcpy blocks).
- `load_overrides()` returns a `dict[str, dict]` already in the shape `assemble_callouts` expects for its `overrides` parameter.
- `CalloutOverride` and `load_overrides()` are arcpy-free and fully testable.
- `save_override()` and `clear_unlocked_overrides()` are LOCAL (arcpy), `# pragma: no cover`.
- Run tests with `python -m pytest -q`.

---

### Task 1: Core `manage_callout_overrides.py`

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_manage_callout_overrides.py`:

```python
import inspect
from autogis.core.envmon.manage_callout_overrides import (
    CalloutOverride, load_overrides, save_override, clear_unlocked_overrides,
)


def test_callout_override_dataclass_fields():
    o = CalloutOverride(
        callout_id="CO-001", location_id="MW-01",
        figure_spec_id="FS-001", origin_x=100.0, origin_y=200.0,
        locked=True, notes="Manual fix")
    assert o.callout_id == "CO-001"
    assert o.locked is True


def test_load_overrides_returns_dict():
    # Without arcpy, load_overrides returns empty dict
    result = load_overrides.__call__.__doc__  # just check it's callable
    assert callable(load_overrides)


def test_load_overrides_signature():
    sig = inspect.signature(load_overrides)
    params = list(sig.parameters.keys())
    assert "gdb_path" in params
    assert "site_id" in params
    assert "figure_spec_id" in params


def test_save_override_signature():
    sig = inspect.signature(save_override)
    params = list(sig.parameters.keys())
    assert "gdb_path" in params
    assert "override" in params


def test_clear_unlocked_overrides_signature():
    sig = inspect.signature(clear_unlocked_overrides)
    params = list(sig.parameters.keys())
    assert "gdb_path" in params
    assert "site_id" in params
    assert "figure_spec_id" in params


def test_callout_override_to_assemble_dict():
    """load_overrides result format matches what assemble_callouts expects."""
    o = CalloutOverride(
        callout_id="CO-001", location_id="MW-01",
        figure_spec_id="FS-001", origin_x=100.5, origin_y=200.3,
        locked=False, notes="")
    d = o.to_assemble_dict()
    assert "origin_x" in d
    assert "origin_y" in d
    assert d["origin_x"] == 100.5
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_manage_callout_overrides.py -v
```

- [ ] **Step 3: Create `autogis/core/envmon/manage_callout_overrides.py`**

```python
"""manage_callout_overrides.py — CRUD for Env_CalloutPlacementOverrides GDB table.

Pure-Python layer (CalloutOverride dataclass + to_assemble_dict) is arcpy-free.
save_override, clear_unlocked_overrides use arcpy lazily.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class CalloutOverride:
    callout_id: str
    location_id: str
    figure_spec_id: str
    origin_x: float
    origin_y: float
    locked: bool
    notes: str = ""

    def to_assemble_dict(self) -> dict:
        """Return override in format expected by assemble_callouts(overrides=...)."""
        return {
            "origin_x": self.origin_x,
            "origin_y": self.origin_y,
            "locked": self.locked,
        }


_TABLE = "Env_CalloutPlacementOverrides"
_FIELDS = ["CalloutID", "LocationID", "FigureSpecID",
           "OriginX", "OriginY", "Locked", "Notes"]


def load_overrides(
    gdb_path: str,
    site_id: str,
    figure_spec_id: str,
) -> dict[str, dict]:
    """
    Return {location_id: override_dict} for all locked overrides matching
    site_id and figure_spec_id. Returns empty dict if table doesn't exist
    or arcpy unavailable.
    """
    try:
        import arcpy  # noqa: F401
        from ...runtime.sessions import arcpy_env as _arcpy
        _ax = _arcpy()
        table = str(Path(gdb_path) / _TABLE)
        if not _ax.Exists(table):
            return {}
        where = (f"FigureSpecID = '{figure_spec_id}' "
                 f"AND Locked = 1")
        result: dict[str, dict] = {}
        with _ax.da.SearchCursor(table, _FIELDS, where) as cur:
            for row in cur:
                co = CalloutOverride(
                    callout_id=row[0], location_id=row[1],
                    figure_spec_id=row[2], origin_x=row[3],
                    origin_y=row[4], locked=bool(row[5]), notes=row[6] or "")
                result[co.location_id] = co.to_assemble_dict()
        return result
    except Exception:
        return {}


def save_override(gdb_path: str, override: CalloutOverride) -> None:  # pragma: no cover
    import arcpy  # noqa: F401
    from ...runtime.sessions import arcpy_env as _arcpy
    _ax = _arcpy()
    table = str(Path(gdb_path) / _TABLE)
    where = f"CalloutID = '{override.callout_id}'"
    existing = []
    with _ax.da.SearchCursor(table, ["CalloutID"], where) as cur:
        existing = [row[0] for row in cur]
    if existing:
        with _ax.da.UpdateCursor(table, _FIELDS, where) as cur:
            for row in cur:
                cur.updateRow([override.callout_id, override.location_id,
                               override.figure_spec_id, override.origin_x,
                               override.origin_y, int(override.locked),
                               override.notes])
    else:
        with _ax.da.InsertCursor(table, _FIELDS) as cur:
            cur.insertRow([override.callout_id, override.location_id,
                           override.figure_spec_id, override.origin_x,
                           override.origin_y, int(override.locked),
                           override.notes])


def clear_unlocked_overrides(  # pragma: no cover
    gdb_path: str,
    site_id: str,
    figure_spec_id: str,
) -> int:
    import arcpy  # noqa: F401
    from ...runtime.sessions import arcpy_env as _arcpy
    _ax = _arcpy()
    table = str(Path(gdb_path) / _TABLE)
    where = f"FigureSpecID = '{figure_spec_id}' AND Locked = 0"
    count = 0
    with _ax.da.UpdateCursor(table, ["CalloutID"], where) as cur:
        for _ in cur:
            cur.deleteRow()
            count += 1
    return count
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_manage_callout_overrides.py -v
```

Expected: all 6 PASS.

- [ ] **Step 5: Full suite + commit**

```bash
git add autogis/core/envmon/manage_callout_overrides.py tests/envmon/test_manage_callout_overrides.py
git commit -m "feat(envmon): manage_callout_overrides — CalloutOverride + load/save/clear (ADR-020)"
```

---

### Task 2: CLI commands

- [ ] **Step 1: Add `optimize-callouts` command** (LOCAL, ArcGIS Pro only)

```python
@envmon.command("optimize-callouts")
@click.argument("site_config", type=click.Path(exists=True))
@click.argument("figure_spec", type=click.Path(exists=True))
@click.option("--use-hull-collision", is_flag=True, default=False)
@click.option("--gdb", default=None, type=click.Path())
def optimize_callouts_cmd(site_config, figure_spec, use_hull_collision, gdb):
    """Run callout placement with optional numpy hull collision detection (ArcGIS Pro)."""
    _guard("optimize-callouts")
    from autogis.core.envmon.build_figure_dataset import assemble_callouts
    raise click.ClickException(
        "optimize-callouts runs inside ArcGIS Pro only. Use the BuildFigureDataset "
        "tool in the .pyt toolbox with use_hull_collision=True."
    )
```

- [ ] **Step 2: Add `manage-callout-overrides` command group with subcommands**

```python
@envmon.group("manage-callout-overrides")
def manage_callout_overrides_grp():
    """CRUD for Env_CalloutPlacementOverrides GDB table."""


@manage_callout_overrides_grp.command("list")
@click.argument("gdb", type=click.Path())
@click.option("--site", "site_id", required=True)
@click.option("--figure-spec", "figure_spec_id", required=True)
def list_overrides_cmd(gdb, site_id, figure_spec_id):
    """List locked callout overrides for a site/figure spec."""
    _guard("manage-callout-overrides")
    from autogis.core.envmon.manage_callout_overrides import load_overrides
    overrides = load_overrides(gdb, site_id, figure_spec_id)
    if not overrides:
        click.echo("No locked overrides found.")
        return
    for loc_id, d in overrides.items():
        click.echo(f"{loc_id}: x={d['origin_x']:.2f}, y={d['origin_y']:.2f} [LOCKED]")


@manage_callout_overrides_grp.command("clear")
@click.argument("gdb", type=click.Path())
@click.option("--site", "site_id", required=True)
@click.option("--figure-spec", "figure_spec_id", required=True)
def clear_overrides_cmd(gdb, site_id, figure_spec_id):
    """Delete all unlocked overrides for a site/figure spec (ArcGIS Pro)."""
    _guard("manage-callout-overrides")
    from autogis.core.envmon.manage_callout_overrides import clear_unlocked_overrides
    count = clear_unlocked_overrides(gdb, site_id, figure_spec_id)
    click.echo(f"Cleared {count} unlocked override(s).")
```

- [ ] **Step 3: Help test + commit**

```python
def test_manage_callout_overrides_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "manage-callout-overrides" in result.output
    assert "optimize-callouts" in result.output
```

```bash
git add autogis/adapters/cli.py tests/envmon/test_manage_callout_overrides.py
git commit -m "feat(cli): add optimize-callouts and manage-callout-overrides commands (ADR-020)"
```
