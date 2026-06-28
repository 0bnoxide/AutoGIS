# OptimizeCalloutPlacement (numpy hull integration) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Extend `build_figure_dataset.py:assemble_callouts` with an optional
`use_hull_collision: bool = False` parameter that routes callout box collision
detection through `convex_hull` from `autogis.core.common.numpy_geom` instead of the
current axis-aligned rect scoring. See ADR: `docs/adr/0020-callout-placement-extend-assemble-callouts.md`.

**Architecture:**
- Modify: `autogis/core/envmon/build_figure_dataset.py` — add `use_hull_collision` param to `assemble_callouts`
- Modify: `autogis/adapters/cli.py` — add `--use-hull-collision` flag to `build-callouts` command
- Modify: `tests/envmon/test_build_figure_dataset.py` (add hull collision tests)

## Global Constraints

- Branch: `feat/gdb-schema-upgrade`
- `use_hull_collision=False` (default) must produce identical behavior to the current code. Zero behavioral change for existing callers.
- numpy_geom import is guarded: `try: from ..common.numpy_geom import convex_hull; _HAS_NUMPY_GEOM = True; except ImportError: _HAS_NUMPY_GEOM = False`. If numpy absent, silently fall back to axis-aligned path.
- No new test fixtures needed; existing callout tests must continue to pass.
- Run tests with `python -m pytest -q`.

---

### Task 1: Understand current `assemble_callouts` signature

- [ ] **Step 1: Read `build_figure_dataset.py:assemble_callouts`**

```bash
# Find the function signature
grep -n "def assemble_callouts" autogis/core/envmon/build_figure_dataset.py
```

Note the current parameter list before adding `use_hull_collision`.

---

### Task 2: Add failing test for hull collision flag

**File:** `tests/envmon/test_build_figure_dataset.py` (append)

- [ ] **Step 1: Append test**

```python
# Append to existing test file
from autogis.core.envmon.build_figure_dataset import assemble_callouts
import inspect

def test_assemble_callouts_accepts_use_hull_collision():
    """assemble_callouts must accept use_hull_collision kwarg without raising."""
    sig = inspect.signature(assemble_callouts)
    assert "use_hull_collision" in sig.parameters

def test_assemble_callouts_hull_collision_default_false():
    sig = inspect.signature(assemble_callouts)
    assert sig.parameters["use_hull_collision"].default is False
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_build_figure_dataset.py -k "hull_collision" -v
```

---

### Task 3: Add `use_hull_collision` to `assemble_callouts`

**File:** `autogis/core/envmon/build_figure_dataset.py`

- [ ] **Step 1: Add numpy_geom guard near top of file** (after existing imports)

```python
try:
    from ..common.numpy_geom import convex_hull as _convex_hull
    _HAS_NUMPY_GEOM = True
except ImportError:  # pragma: no cover
    _HAS_NUMPY_GEOM = False
```

- [ ] **Step 2: Add `use_hull_collision=False` to `assemble_callouts` signature**

Find the `def assemble_callouts(` line and add the new parameter. Keep existing
parameters unchanged — add `use_hull_collision: bool = False` at the end of the
signature.

- [ ] **Step 3: Inside `assemble_callouts`, replace the collision scoring call**

Find where the axis-aligned rect collision check occurs. Wrap it:

```python
if use_hull_collision and _HAS_NUMPY_GEOM:
    # Hull-based collision detection using convex_hull from numpy_geom
    # Convert rotated corner arrays to convex hull polygons for scoring
    import numpy as np
    # ... hull-based scoring logic ...
    # For each candidate position, compute hull of rotated box corners,
    # then check intersection with other callout hulls.
    # (Implementation depends on exact structure of callout geometry data.)
    pass  # placeholder — expand based on callout_geometry.py data structures
else:
    # Existing axis-aligned rect scoring — unchanged
    ...existing code...
```

> **Implementation note:** The actual hull integration depends on the exact array
> structures in `callout_geometry.py`. Read `build_callout_geometry()` output format
> before replacing the placeholder `pass` block. The `convex_hull(points)` function
> in `numpy_geom.py` accepts an `(N, 2)` float array and returns hull vertex indices.

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_build_figure_dataset.py -v
```

Expected: all existing tests still pass + 2 new tests pass.

- [ ] **Step 5: Full suite**

```
python -m pytest -q
```

- [ ] **Step 6: Commit**

```bash
git add autogis/core/envmon/build_figure_dataset.py tests/envmon/test_build_figure_dataset.py
git commit -m "feat(envmon): assemble_callouts — add use_hull_collision flag (ADR-020)"
```

---

### Task 4: CLI `--use-hull-collision` flag

**File:** `autogis/adapters/cli.py`

- [ ] **Step 1: Add flag to `build-callouts` command**

Find the `@envmon.command("build-callouts")` block. Add:

```python
@click.option("--use-hull-collision", is_flag=True, default=False,
              help="Use convex hull (numpy_geom) for callout collision detection.")
```

Pass the flag through to `assemble_callouts` when arcpy is present.

- [ ] **Step 2: Commit**

```bash
git add autogis/adapters/cli.py
git commit -m "feat(cli): add --use-hull-collision flag to build-callouts command"
```
