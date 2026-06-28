# CapabilitiesRegistryCompleteness — Implementation Plan

**Goal:** Ensure every CLI command registered under the `envmon` and `agol` groups is
also listed in the `TOOLS` dict in `capabilities.py`. Several commands were added over
multiple agent batches but their TOOLS entries were omitted. Also fix the known
duplicate `reconcile-locations` command in `cli.py`. This plan adds a completeness test
and fills the gaps as a single correctness commit.

**Architecture:**
1. Test `tests/test_capabilities_complete.py` — enumerates all Click commands and
   asserts each has a TOOLS entry. This test will fail until the gaps are fixed.
2. Add missing TOOLS entries to `capabilities.py`.
3. Remove the first duplicate `@envmon.command("reconcile-locations")` registration
   from `cli.py` (it appears twice; the second is the canonical one with both headless
   and GDB code paths).
No new module required.

**Tech stack:** Python 3.14, click, pytest. Reuses existing `capabilities.py` and
`cli.py` only.

## Global constraints

- `core/` and `adapters/` import without arcpy.
- Do not change command behavior — only add TOOLS registrations and remove the
  duplicate command definition.
- Missing TOOLS entries and their correct Runtime values:
  - `evaluate-rpd`: CLOUD
  - `evaluate-rpd-qa`: CLOUD
  - `export-summary`: CLOUD
  - `export-report-format-summary-tables`: CLOUD
  - `evaluate-readiness`: CLOUD
  - `validate-rtk-survey`: CLOUD
  - `import-rtk-survey`: LOCAL
  - `reconcile-survey123-lab`: CLOUD
  - `route-survey123`: LOCAL

---

### Task 1: Completeness test

**Files:**
- Create: `tests/test_capabilities_complete.py`

**Complete code:**

```python
"""Verify all envmon / agol CLI commands are registered in TOOLS."""
import click
from autogis.adapters.cli import envmon, agol
from autogis.runtime.capabilities import TOOLS


def _collect_commands(group, prefix=""):
    """Recursively collect leaf command names from a Click group."""
    names = []
    for name, cmd in group.commands.items():
        full = f"{prefix}{name}" if not prefix else f"{prefix}-{name}"
        if isinstance(cmd, click.Group):
            names.extend(_collect_commands(cmd, prefix=full))
        else:
            names.append(full)
    return names


def test_envmon_commands_in_tools():
    """Every envmon command must have a TOOLS entry."""
    commands = _collect_commands(envmon)
    missing = [c for c in commands if c not in TOOLS]
    assert not missing, (
        f"envmon CLI commands missing from capabilities.TOOLS: {missing}. "
        "Add them with the correct Runtime value.")


def test_no_duplicate_commands():
    """No duplicate command names should exist in the envmon group."""
    names = list(envmon.commands.keys())
    seen = set()
    dupes = []
    for n in names:
        if n in seen:
            dupes.append(n)
        seen.add(n)
    assert not dupes, f"Duplicate command name(s) in envmon group: {dupes}"
```

**Steps:**
- [ ] Write test file. Run `python -m pytest tests/test_capabilities_complete.py -q`.
  Confirm it fails listing the missing commands.

---

### Task 2: Add missing TOOLS entries + fix duplicate

**Files to modify:**
- `autogis/runtime/capabilities.py` — add 9 entries
- `autogis/adapters/cli.py` — remove duplicate `reconcile-locations` command

**Changes to `capabilities.py` TOOLS dict (add after existing entries):**

```python
# Commands present in CLI but previously omitted from TOOLS:
"evaluate-rpd": Runtime.CLOUD,
"evaluate-rpd-qa": Runtime.CLOUD,
"export-summary": Runtime.CLOUD,
"export-report-format-summary-tables": Runtime.CLOUD,
"evaluate-readiness": Runtime.CLOUD,
"validate-rtk-survey": Runtime.CLOUD,
"import-rtk-survey": Runtime.LOCAL,
"reconcile-survey123-lab": Runtime.CLOUD,
"route-survey123": Runtime.LOCAL,
```

**Duplicate fix in `cli.py`:**

The `reconcile-locations` command is registered twice in `cli.py`. The first
registration (lines ~183-220, which lacks the `--gdb` / `--wells-csv` split) is
the duplicate. Remove it completely. Keep the second registration (lines ~239-276)
which has both headless and GDB paths.

To identify: the first `@envmon.command("reconcile-locations")` block ends before
`@envmon.command("validate-units")`. Remove that entire block.

**Steps:**
- [ ] Modify `capabilities.py` to add the 9 missing entries.
- [ ] In `cli.py`, remove the first duplicate `reconcile-locations` command block.
- [ ] Run `python -m pytest tests/test_capabilities_complete.py -q` — confirm pass.
- [ ] Run `python -m pytest -q` — confirm all existing tests pass.
- [ ] Commit: `fix(runtime): complete TOOLS registry + remove duplicate reconcile-locations`
