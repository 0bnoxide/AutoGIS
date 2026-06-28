# RunHistoryQueryCLI — Implementation Plan

**Goal:** Add `envmon run-history` CLI command that queries the `run_history.csv` file (written by `RunHistory.write()`) and displays filtered results. Operators can see which tools ran, when, and whether they succeeded — without reading the CSV manually. Supports filtering by site, tool name, status, and date range, with output in table, CSV, or JSON format.

**Architecture:** New CLI command only (no new module — wraps existing `RunHistory` class from `autogis/core/common/run_history.py`). Options: `--run-history PATH`, `--site SITE_ID`, `--tool TOOL_NAME`, `--since DATE`, `--status STATUS`, `--limit N`, `--format table|csv|json`. Default format is `table` (aligned columns). CLOUD runtime — no arcpy required.

**Tech stack:** Python 3.14, click, stdlib csv/json/datetime. Reuses: `RunHistory`, `RunRecord` from `autogis/core/common/run_history.py`.

## Global constraints
- `core/` and `adapters/` import without arcpy or arcgis present
- Use openpyxl for Excel output (ADR-008); this plan uses no Excel
- New CLI command added to TOOLS in `autogis/runtime/capabilities.py` as `Runtime.CLOUD`
- Run tests with: `python -m pytest -q`
- CLI command goes in `autogis/adapters/cli.py` under the `envmon` group

---

### Task 1: Write test file `tests/test_cli_run_history.py`

**Files:**
- Create: `tests/test_cli_run_history.py`

**Complete code:**

```python
"""CLI tests for envmon run-history command."""
import csv
import json
from datetime import datetime
from pathlib import Path

import pytest
from click.testing import CliRunner

from autogis.adapters.cli import autogis
from autogis.core.common.run_history import RunHistory, RunRecord


def _write_run(path, tool="import-edd", site="H281", status="success", event=None):
    rh = RunHistory(path)
    rh.write(RunRecord(
        run_id=f"RUN-{tool[:4].upper()}",
        tool_name=tool,
        site_id=site,
        event_id=event,
        started_at=datetime(2026, 6, 1, 10, 0, 0),
        finished_at=datetime(2026, 6, 1, 10, 5, 0),
        status=status,
        inputs={},
        outputs={},
        qa_count_error=0,
        qa_count_warning=0,
        qa_count_info=1,
        message="ok",
    ))


def test_run_history_table_output(tmp_path):
    rh_path = tmp_path / "run_history.csv"
    _write_run(rh_path)
    runner = CliRunner()
    result = runner.invoke(autogis, [
        "envmon", "run-history",
        "--run-history", str(rh_path),
    ])
    assert result.exit_code == 0, result.output
    assert "import-edd" in result.output
    assert "H281" in result.output


def test_run_history_filter_site(tmp_path):
    rh_path = tmp_path / "run_history.csv"
    _write_run(rh_path, site="SITE-A")
    _write_run(rh_path, tool="validate-config", site="SITE-B")
    runner = CliRunner()
    result = runner.invoke(autogis, [
        "envmon", "run-history",
        "--run-history", str(rh_path),
        "--site", "SITE-A",
    ])
    assert result.exit_code == 0
    assert "SITE-A" in result.output
    assert "SITE-B" not in result.output


def test_run_history_json_format(tmp_path):
    rh_path = tmp_path / "run_history.csv"
    _write_run(rh_path)
    runner = CliRunner()
    result = runner.invoke(autogis, [
        "envmon", "run-history",
        "--run-history", str(rh_path),
        "--format", "json",
    ])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert len(data) == 1


def test_run_history_filter_status(tmp_path):
    rh_path = tmp_path / "run_history.csv"
    _write_run(rh_path, status="success")
    _write_run(rh_path, tool="compare-events", status="error")
    runner = CliRunner()
    result = runner.invoke(autogis, [
        "envmon", "run-history",
        "--run-history", str(rh_path),
        "--status", "error",
    ])
    assert result.exit_code == 0
    assert "compare-events" in result.output
    assert "import-edd" not in result.output


def test_run_history_empty_file(tmp_path):
    rh_path = tmp_path / "run_history.csv"
    runner = CliRunner()
    result = runner.invoke(autogis, [
        "envmon", "run-history",
        "--run-history", str(rh_path),
    ])
    assert result.exit_code == 0
    assert "0 record" in result.output


def test_run_history_csv_format(tmp_path):
    rh_path = tmp_path / "run_history.csv"
    _write_run(rh_path)
    runner = CliRunner()
    result = runner.invoke(autogis, [
        "envmon", "run-history",
        "--run-history", str(rh_path),
        "--format", "csv",
    ])
    assert result.exit_code == 0
    lines = result.output.strip().split("\n")
    assert "tool_name" in lines[0]
    assert len(lines) >= 2  # header + at least 1 row
```

**Steps:**
- [ ] Write test file as shown above
- [ ] Run `python -m pytest tests/test_cli_run_history.py -q` — expect AttributeError or similar (command not yet registered)

---

### Task 2: Add CLI command to `autogis/adapters/cli.py`

**Files:**
- Modify: `autogis/adapters/cli.py` (add command before `_render_qa` helper or at end of `envmon` group)

**Complete code (command to add):**

```python
@envmon.command("run-history")
@click.option(
    "--run-history", "history_path", required=True, type=click.Path(),
    help="Path to run_history.csv (need not exist; treated as empty if absent).",
)
@click.option("--site", "site_id", default=None, help="Filter by site ID.")
@click.option("--tool", "tool_name", default=None, help="Filter by tool name.")
@click.option(
    "--status", default=None,
    type=click.Choice(["success", "warning", "error", "cancelled"]),
    help="Filter by run status.",
)
@click.option("--since", default=None, help="Only runs since this ISO date (YYYY-MM-DD).")
@click.option("--limit", type=int, default=0, help="Max records to show (0 = all).")
@click.option(
    "--format", "fmt",
    type=click.Choice(["table", "csv", "json"]),
    default="table", show_default=True,
)
def run_history_cmd(history_path, site_id, tool_name, status, since, limit, fmt):
    """Query the tool run history CSV (headless)."""
    import json as _json
    import csv as _csv
    import io
    from datetime import datetime as _dt
    from dataclasses import asdict
    from autogis.core.common.run_history import RunHistory

    history = RunHistory(Path(history_path))
    since_dt = _dt.fromisoformat(since) if since else None
    records = history.query(
        site_id=site_id,
        tool_name=tool_name,
        since=since_dt,
        status=status,
    )
    if limit and limit > 0:
        records = records[-limit:]

    if not records:
        click.echo("0 record(s) found.")
        return

    if fmt == "json":
        payload = []
        for r in records:
            d = asdict(r)
            d["started_at"] = r.started_at.isoformat()
            d["finished_at"] = r.finished_at.isoformat()
            payload.append(d)
        click.echo(_json.dumps(payload, indent=2))
    elif fmt == "csv":
        buf = io.StringIO()
        cols = [
            "run_id", "tool_name", "site_id", "event_id",
            "started_at", "finished_at", "status",
            "qa_count_error", "qa_count_warning", "message",
        ]
        w = _csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in records:
            row = asdict(r)
            row["started_at"] = r.started_at.isoformat()
            row["finished_at"] = r.finished_at.isoformat()
            w.writerow(row)
        click.echo(buf.getvalue().rstrip())
    else:  # table
        hdr = (
            f"{'tool_name':<28} {'site_id':<12} {'status':<10}"
            f" {'finished_at':<20} msg"
        )
        click.echo(hdr)
        click.echo("-" * len(hdr))
        for r in records:
            click.echo(
                f"{r.tool_name:<28} {r.site_id:<12} {r.status:<10} "
                f"{r.finished_at.isoformat():<20} {r.message[:40]}"
            )

    click.echo(f"\n{len(records)} record(s).")
```

**Steps:**
- [ ] Add command to `autogis/adapters/cli.py` within the `envmon` group
- [ ] Add `"run-history": Runtime.CLOUD` to `TOOLS` dict in `autogis/runtime/capabilities.py`
- [ ] Run `python -m pytest tests/test_cli_run_history.py -q` — expect all pass
- [ ] Run `python -m pytest -q` — expect full suite passes
- [ ] Commit: `feat(envmon): run-history — query tool run history CSV (headless CLI)`

---

## Run commands

```bash
# Step 1: run new tests (expect failure before implementation)
python -m pytest tests/test_cli_run_history.py -q

# Step 2: after implementation
python -m pytest tests/test_cli_run_history.py -q

# Step 3: full suite
python -m pytest -q
```
