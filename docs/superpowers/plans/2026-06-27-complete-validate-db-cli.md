# CompleteValidateDB CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Wire the existing `validate_database()` function (already implemented in
`validate_database.py`) to the `validate-db` CLI command, which currently just raises
a ClickException saying "use the .pyt toolbox." Add `--analytes`, `--report`, and
`--fail-on` options so it can be driven from the CLI like the other validate commands.

**Architecture:**
- Modify: `autogis/adapters/cli.py` — replace stub body with real call
- Modify: `tests/envmon/` — add `test_cli_validate_db.py`

No new modules needed. `validate_database.py` is already complete.

## Global Constraints

- Branch: `feat/gdb-schema-upgrade`
- `validate-db` remains LOCAL (arcpy guarded) — only the stub body changes.
- The `--gdb` argument type changes from `click.Path()` to `click.Path()` (no `exists=True` — a GDB directory may not yet exist as a real path on the test runner machine).
- Run tests with `python -m pytest -q`.

---

### Task 1: Write CLI tests

Create `tests/envmon/test_cli_validate_db.py`:

- [ ] **Step 1: Write test**

```python
from click.testing import CliRunner
from autogis.adapters.cli import autogis


def test_validate_db_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert result.exit_code == 0
    assert "validate-db" in result.output


def test_validate_db_shows_analytes_option():
    result = CliRunner().invoke(autogis, ["envmon", "validate-db", "--help"])
    assert "--analytes" in result.output


def test_validate_db_shows_report_option():
    result = CliRunner().invoke(autogis, ["envmon", "validate-db", "--help"])
    assert "--report" in result.output


def test_validate_db_guard_without_arcpy():
    """Without arcpy, validate-db must error cleanly (no unhandled exception)."""
    result = CliRunner().invoke(autogis, ["envmon", "validate-db", "fake.gdb"])
    assert result.exit_code in (0, 1)
    assert result.exception is None or isinstance(result.exception, SystemExit)
```

- [ ] **Step 2: Run — help tests pass already; guard test may fail because current stub has different message**

```
python -m pytest tests/envmon/test_cli_validate_db.py -v
```

---

### Task 2: Replace stub with real call

**File:** `autogis/adapters/cli.py`

- [ ] **Step 1: Replace the `validate-db` command block**

Find:
```python
@envmon.command("validate-db")
@click.argument("gdb", type=click.Path())
def validate_db_cmd(gdb):
    """Tool 8: validate the geodatabase schema/contents (ArcGIS Pro)."""
    _guard("validate-db")
    from autogis.core.envmon import validate_database  # noqa: F401
    raise click.ClickException(
        "validate-db runs inside ArcGIS Pro only. Use the ValidateDatabase "
        "tool in the .pyt toolbox."
    )
```

Replace with:
```python
@envmon.command("validate-db")
@click.argument("gdb", type=click.Path())
@click.option("--analytes", default=None, type=click.Path(exists=True),
              help="Analyte dictionary YAML (enables analyte-name QA checks).")
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error")
def validate_db_cmd(gdb, analytes, report, fail_on):
    """Tool 8: validate the GDB schema and cross-table integrity (ArcGIS Pro)."""
    _guard("validate-db")
    from pathlib import Path
    from autogis.core.common.config import load_analyte_dictionary
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.validate_database import validate_database

    analyte_dict = {}
    if analytes:
        analyte_dict = load_analyte_dictionary(Path(analytes)) or {}
    qa = QACollector()
    validate_database(Path(gdb), qa, analyte_dict)
    _render_qa(qa, report, fail_on)
```

- [ ] **Step 2: Run tests**

```
python -m pytest tests/envmon/test_cli_validate_db.py -v
```

- [ ] **Step 3: Full suite**

```
python -m pytest -q
```

- [ ] **Step 4: Commit**

```bash
git add autogis/adapters/cli.py tests/envmon/test_cli_validate_db.py
git commit -m "feat(cli): wire validate-db to validate_database() — add --analytes/--report options"
```
