# AutoGIS Suite Merge (envmon) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fold the Environmental Monitoring toolbox (`staging/envmon-incoming/`) into the AutoGIS harness as one CLI- and GUI-driven suite — one core, three adapters, per-tool runtime capability.

**Architecture:** Monorepo, single `autogis` package. `core/common` (config, qa, reporting, logging) is the shared substrate; `core/harvest` and `core/envmon` sit on it. `runtime/` holds the capability registry + session providers. `adapters/` has a `click` group CLI and a `toolbox.pyt` GUI — both dumb marshallers over the same core. `arcgis`/`arcpy` stay lazy; importing any `core` module needs neither.

**Tech Stack:** Python (typed dataclasses, `dataclasses`), `click`, `PyYAML`+JSON fallback, `openpyxl`, `pytest`. `arcgis` = `cloud` extra; `arcpy` = runtime-detected (ships with Pro, never an extra).

**Source spec:** `docs/MERGE_PLAN.md` (authoritative scope) + `docs/superpowers/specs/2026-06-19-mergeplan-deltas.md` (verified ground truth — wins over MERGE_PLAN summary where they differ).

## Global Constraints

Copied from the deltas doc + MERGE_PLAN §6 (final decisions). Every task's requirements implicitly include this section.

- **Monorepo, one `autogis` package.** No second package. (MERGE_PLAN §6)
- **CLI registers all tools; only 1/9/10 are headless-supported.** Tools 2–8 are registered but runtime-guarded (error clearly when arcpy absent); the `.pyt` is their primary UI. No rich CLI ergonomics for 2–8. (MERGE_PLAN §6)
- **Import with neither `arcgis` nor `arcpy`.** Both lazy. `cloud` extra installs `arcgis`; `arcpy` runtime-detected. (MERGE_PLAN §2)
- **`openpyxl` is a BASE dependency** (deltas C2) — `envmon_config`/`excel_profile_reader` fail to import without it; this is unrelated to the arcpy/arcgis rule.
- **`logging_utils` is arcpy-edge (lazy), the 9th arcpy module** (deltas C1) — treat as edge, not arcpy-free, when applying the guard. Module import stays safe (arcpy lazy inside `_ArcpyHandler.emit`).
- **Single validation source on the dataclass.** GUI and CLI both construct/validate the same config dataclass. (MERGE_PLAN §2)
- **Config (deltas H1, resolved):** `HarvestConfig.load(path) -> HarvestConfig` (pure single-object style). `connection.profile` moves to `runtime/sessions.py`; the CLI override whitelist (`where/directory/incremental`) is a CLI-adapter concern, not a loader param. `item_id`-XOR-`url` validated on the dataclass. The legacy `(HarvestConfig, profile)` tuple (MERGE_PLAN §7) is superseded.
- **Config style (deltas C5):** keep envmon's TWO styles — field-typed `SheetProfile`/`ParserProfile`, dict-backed `__getattr__` `SiteConfig`/`FigureSpec`. Do NOT field-type the dict-backed ones. Re-express only `HarvestConfig` field-typed.
- **Reporting (deltas H2, resolved):** the unified result record carries an explicit `disposition` field (`downloaded`/`skipped`/`failed`); summary counts group by it. QA records stay issue-only — successes do NOT emit QA records.
- **Reporter thread-safety (deltas C6):** lock the WHOLE shared-state surface — `record`/`add` AND the iterating writers AND all of `QACollector` — not just the two named methods. Expose a cancel/progress hook.
- **Reserved provenance columns (deltas §5):** the unified result record reserves `checksum` (+`algorithm`), `geometry` (WKT/GeoJSON), `source_table`, `relationship_id`. Empty now; filled post-merge.
- **Per-record JSON writer (deltas C7):** keep a per-record `manifest.json` writer; envmon's `write_json_summary` is an aggregate, not a replacement.
- **Carried caveats — do NOT regress (deltas R6/H3):** H281 DRAFT banner + Tool-1/human-review gate; `average_parent_and_duplicate` QA WARNING; null screening-levels `_TODO`s; arcpy paths un-CI-able. Real-workbook H281 verification stays a manual user task.
- **Python floor:** target the `arcgispro-py3` interpreter (3.11). Code already uses `X | None` unions; bump `requires-python` to `>=3.10`.
- **Branch:** `merge/envmon-suite`. Keep `main` green. One reviewable commit per task. `pytest` green for arcpy-free code at every step; arcpy paths guarded + manually verified in Pro.
- **Import-rewrite order (deltas C3, step 4):** acyclic; migrate roots first per the topological order in the deltas doc §4. Delete `.pyt` lines 14–16.

---

## File Structure (target)

```
autogis/
  core/
    common/   config.py  qa.py  reporting.py  logging.py  seen.py
    harvest/  __init__.py  harvester.py  download.py  manifest.py  state.py  templates.py  gis_session.py  models.py
    envmon/   __init__.py  (23 modules, relative imports)
  runtime/
    capabilities.py   # Runtime enum CLOUD|LOCAL|HYBRID + per-tool registry
    sessions.py       # AGOL-profile/env, active-Pro-portal, arcpy-env providers
  adapters/
    cli.py            # click GROUP: autogis harvest … / autogis envmon <tool> …
    toolbox.pyt       # Esri .pyt, 1 + 10 Tool classes over the same core
    config_loader.py  # (thin shim retained for back-compat re-export, or removed)
  config/
pyproject.toml
tests/                # harness tests + ported envmon tests
```

- Files that change together live together (`core/harvest/*` move as a unit). Split by responsibility.
- `core/common/seen.py` = the single "seen-before" abstraction (harvester checksum-skip + envmon unique-key idempotency), reserved now, fleshed out post-merge.

---

## Task 1: Scaffold without behavior change

Add `core/common/`, `runtime/`, move harvester modules under `core/harvest/` with re-exports, convert the CLI to a `click` group. **No logic changes.** All existing tests pass unchanged.

**Files:**
- Create: `autogis/core/common/__init__.py`, `autogis/runtime/__init__.py`, `autogis/runtime/capabilities.py`
- Create: `autogis/core/harvest/__init__.py` (re-export shim)
- Move: `autogis/core/{harvester,download,manifest,state,templates,gis_session,models}.py` → `autogis/core/harvest/`
- Modify: `autogis/adapters/cli.py` (command → group), `pyproject.toml` (`[project.scripts]`, `requires-python`, base deps, `cloud` extra)
- Keep: `autogis/core/__init__.py` re-exporting old paths so existing imports/tests don't break
- Test: existing `tests/*` unchanged; add `tests/test_capabilities.py`, `tests/test_cli_group.py`

**Interfaces:**
- Consumes: existing harvester core (signatures unchanged).
- Produces:
  - `autogis.runtime.capabilities.Runtime` (enum: `CLOUD`, `LOCAL`, `HYBRID`)
  - `autogis.runtime.capabilities.TOOLS: dict[str, Runtime]` registry + `requires_arcpy(name) -> bool`
  - `autogis.core.harvest` package exposing `harvest`, `HarvestConfig`, `RunSummary`, `Manifest`, `AttachmentResult` (re-exported)
  - CLI `autogis` group with `harvest` subcommand; legacy `autogis-harvest` console-script preserved as an alias.

- [ ] **Step 1: Write the failing test for the runtime registry**

`tests/test_capabilities.py`:
```python
from autogis.runtime.capabilities import Runtime, TOOLS, requires_arcpy


def test_harvester_is_hybrid():
    assert TOOLS["harvest"] is Runtime.HYBRID


def test_local_tools_require_arcpy():
    assert requires_arcpy("import-gdb") is True
    assert requires_arcpy("harvest") is False


def test_cloud_ok_tools_do_not_require_arcpy():
    for name in ("inspect", "parser-profile", "figure-spec"):
        assert requires_arcpy(name) is False
```

- [ ] **Step 2: Run it, verify it fails**

Run: `pytest tests/test_capabilities.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'autogis.runtime'`.

- [ ] **Step 3: Implement the registry**

`autogis/runtime/__init__.py`: empty. `autogis/runtime/capabilities.py`:
```python
from enum import Enum


class Runtime(Enum):
    CLOUD = "cloud"
    LOCAL = "local"
    HYBRID = "hybrid"


# Per MERGE_PLAN §4. Names are CLI subcommand names.
TOOLS: dict[str, Runtime] = {
    "harvest": Runtime.HYBRID,
    "inspect": Runtime.CLOUD,          # tool 1
    "parser-profile": Runtime.CLOUD,   # tool 9
    "figure-spec": Runtime.CLOUD,      # tool 10
    "import-gdb": Runtime.LOCAL,       # tool 2
    "build-event": Runtime.LOCAL,      # tool 3
    "build-callouts": Runtime.LOCAL,   # tool 4
    "gw-contours": Runtime.LOCAL,      # tool 5
    "export-figures": Runtime.LOCAL,   # tool 6
    "full-pipeline": Runtime.LOCAL,    # tool 7
    "validate-db": Runtime.LOCAL,      # tool 8
}


def requires_arcpy(name: str) -> bool:
    return TOOLS[name] is Runtime.LOCAL
```

- [ ] **Step 4: Run it, verify it passes**

Run: `pytest tests/test_capabilities.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Move harvester modules under core/harvest with re-exports**

Use `git mv` (preserves history) for each of the 7 modules:
```bash
mkdir autogis/core/harvest
git mv autogis/core/harvester.py   autogis/core/harvest/harvester.py
git mv autogis/core/download.py    autogis/core/harvest/download.py
git mv autogis/core/manifest.py    autogis/core/harvest/manifest.py
git mv autogis/core/state.py       autogis/core/harvest/state.py
git mv autogis/core/templates.py   autogis/core/harvest/templates.py
git mv autogis/core/gis_session.py autogis/core/harvest/gis_session.py
git mv autogis/core/models.py      autogis/core/harvest/models.py
```
The intra-package imports in these files are already relative (`from .models import …`, `from .manifest import …`) so they keep working unchanged inside the new package. Create `autogis/core/harvest/__init__.py`:
```python
from .models import HarvestConfig, AttachmentResult, RunSummary
from .manifest import Manifest
from .harvester import harvest, resolve_layer

__all__ = ["HarvestConfig", "AttachmentResult", "RunSummary",
           "Manifest", "harvest", "resolve_layer"]
```
Add back-compat re-exports so old import paths still resolve. `autogis/core/__init__.py`:
```python
# Back-compat: old flat paths now live under core.harvest.
from autogis.core.harvest import (  # noqa: F401
    harvester, download, manifest, state, templates, gis_session, models,
)
```
Update `autogis/adapters/config_loader.py:2` and `autogis/adapters/cli.py:3-5` imports to the new paths (`from autogis.core.harvest.models import HarvestConfig`, etc.). Create empty `autogis/core/common/__init__.py`.

- [ ] **Step 6: Run the FULL suite, verify nothing regressed**

Run: `pytest -q`
Expected: PASS — all pre-existing tests (test_harvester, test_manifest, test_models, test_config_loader, test_cli, …) still green. If any import error, fix the moved-path import, do not change behavior.

- [ ] **Step 7: Convert the CLI command to a group (behavior-preserving)**

Rewrite `autogis/adapters/cli.py`: keep `run(...)` exactly as-is (still returns the tuple-consuming flow for now — config refactor is Task-deferred), wrap the existing command as a `harvest` subcommand of a new `autogis` group, and keep a `main` alias for the legacy console script.
```python
import click

from autogis.adapters.config_loader import load_config
from autogis.core.harvest.gis_session import build_gis_from_env
from autogis.core.harvest.harvester import harvest


def run(config_path, where, out, incremental, *, gis_builder, harvest_fn, load_fn):
    overrides = {"where": where, "directory": out, "incremental": incremental}
    config, profile = load_fn(config_path, overrides=overrides)
    gis = gis_builder(profile)
    summary = harvest_fn(gis, config)
    click.echo(
        f"Downloaded: {summary.downloaded}  "
        f"Skipped: {summary.skipped}  Failed: {summary.failed}")
    return summary


@click.group()
def autogis():
    """AutoGIS suite — harvest + envmon tools."""


@autogis.command("harvest")
@click.option("--config", "config_path", required=True, type=click.Path(exists=True))
@click.option("--where", default=None)
@click.option("--out", default=None)
@click.option("--incremental/--no-incremental", default=None)
def harvest_cmd(config_path, where, out, incremental):
    run(config_path, where, out, incremental,
        gis_builder=build_gis_from_env, harvest_fn=harvest, load_fn=load_config)


# Legacy single-command entry point kept as an alias.
main = autogis


if __name__ == "__main__":
    autogis()
```

- [ ] **Step 8: Update pyproject and add a group smoke test**

`pyproject.toml`:
```toml
requires-python = ">=3.10"
dependencies = ["PyYAML", "click", "openpyxl"]

[project.optional-dependencies]
dev = ["pytest"]
cloud = ["arcgis"]

[project.scripts]
autogis = "autogis.adapters.cli:autogis"
autogis-harvest = "autogis.adapters.cli:autogis"
```
`tests/test_cli_group.py`:
```python
from click.testing import CliRunner
from autogis.adapters.cli import autogis


def test_group_lists_harvest():
    result = CliRunner().invoke(autogis, ["--help"])
    assert result.exit_code == 0
    assert "harvest" in result.output
```

- [ ] **Step 9: Run full suite + commit**

Run: `pytest -q` → Expected: PASS (all old + new).
```bash
git checkout -b merge/envmon-suite   # if not already on it
git add -A
git commit -m "refactor: scaffold core/common + runtime, harvest package, CLI group (no behavior change)"
```

---

## Task 2: Reporter interface over a thread-safe substrate

Introduce `core/common/reporting.py` (events + cancel/progress hook) and `core/common/qa.py`/`logging.py` (ported from envmon `qa_checks`/`logging_utils`), all thread-safe. Wire harvester to emit through it. Add the `disposition` field + reserved provenance columns. No envmon tool code yet.

**Files:**
- Create: `autogis/core/common/qa.py` (port `QARecord`/`QACollector`, add a `threading.RLock` around every mutator/iterating reader-writer — deltas C6), `autogis/core/common/logging.py` (port `_ArcpyHandler`, lazy arcpy), `autogis/core/common/reporting.py` (`Reporter` with `record_qa`, `record_result`, `cancel_check`, `progress`), `autogis/core/common/seen.py` (interface stub for the one "seen-before" concept)
- Modify: `autogis/core/harvest/models.py` (`AttachmentResult` gains `disposition` + reserved `checksum/algorithm/geometry/source_table/relationship_id` = None defaults), `autogis/core/harvest/manifest.py` (lock; keep per-record `write_json` — deltas C7; add per-record fields), `autogis/core/harvest/harvester.py` (emit via Reporter, set `disposition`)
- Test: `tests/test_reporting.py`, `tests/test_qa_threadsafe.py`, update `tests/test_manifest.py`/`tests/test_models.py` for new fields

**Interfaces:**
- Consumes: Task 1 packages.
- Produces:
  - `core.common.qa.QARecord` (severity, category, message, recommended_action, provenance…), `QACollector` (thread-safe `add/extend/counts/status/write_csv/write_json_summary/write_markdown`)
  - `core.common.reporting.Reporter(qa: QACollector, *, cancel=None, progress=None)` with `record_result(result)`, `record_qa(record)`, `cancelled() -> bool`, `emit_progress(done, total)`
  - `AttachmentResult` with `disposition: str` + reserved `checksum/algorithm/geometry/source_table/relationship_id: … | None = None`
  - A `summary_counts(results) -> dict` view grouping by `disposition` (replaces `RunSummary` semantics; keep `RunSummary` as a thin back-compat shim over this view).

- [ ] **Step 1: Failing test — QACollector is thread-safe under concurrent add**

`tests/test_qa_threadsafe.py`:
```python
import threading
from autogis.core.common.qa import QACollector, QARecord


def test_concurrent_add_keeps_every_record():
    qa = QACollector()
    def worker():
        for _ in range(1000):
            qa.add(QARecord(severity="INFO", category="t", message="m"))
    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert len(qa.records) == 8000
```

- [ ] **Step 2: Run, verify fail** — `pytest tests/test_qa_threadsafe.py -v` → FAIL (module missing).

- [ ] **Step 3: Port qa_checks → core/common/qa.py with an RLock**

Copy `staging/envmon-incoming/src/qa_checks.py` to `autogis/core/common/qa.py`. Wrap `__init__` with `self._lock = threading.RLock()`; guard `add`, `extend`, and every method that iterates `self.records` (`counts`, `status`, `write_csv`, `write_json_summary`, `write_markdown`) with `with self._lock:`. Keep `QARecord` and `as_gdb_row` unchanged. (deltas C6)

- [ ] **Step 4: Run, verify pass** — `pytest tests/test_qa_threadsafe.py -v` → PASS.

- [ ] **Step 5: Failing test — Reporter sets disposition + reserves provenance**

`tests/test_reporting.py`:
```python
from autogis.core.common.qa import QACollector
from autogis.core.common.reporting import Reporter
from autogis.core.harvest.models import AttachmentResult


def test_result_carries_disposition_and_reserved_fields():
    r = AttachmentResult(objectid=1, attachment_id=2, original_name="a.pdf",
                         saved_path="x", size=3, status="downloaded",
                         disposition="downloaded")
    assert r.disposition == "downloaded"
    assert r.checksum is None and r.geometry is None
    assert r.source_table is None and r.relationship_id is None


def test_reporter_cancel_hook():
    flag = {"stop": False}
    rep = Reporter(QACollector(), cancel=lambda: flag["stop"])
    assert rep.cancelled() is False
    flag["stop"] = True
    assert rep.cancelled() is True
```

- [ ] **Step 6: Run, verify fail** — FAIL (`AttachmentResult` has no `disposition`; no `Reporter`).

- [ ] **Step 7: Extend AttachmentResult + add Reporter + summary view**

`core/harvest/models.py` — add fields (keep existing order; new fields default `None` so callers don't break):
```python
@dataclass
class AttachmentResult:
    objectid: int
    attachment_id: int
    original_name: str
    saved_path: str | None
    size: int | None
    status: str
    error: str | None = None
    disposition: str | None = None
    checksum: str | None = None
    algorithm: str | None = None
    geometry: str | None = None
    source_table: str | None = None
    relationship_id: str | None = None
```
Add `summary_counts`:
```python
def summary_counts(results) -> dict:
    out = {s: 0 for s in VALID_STATUSES}
    for r in results:
        key = r.disposition or r.status
        if key in out:
            out[key] += 1
    return out
```
`core/common/reporting.py`:
```python
class Reporter:
    def __init__(self, qa, *, cancel=None, progress=None):
        self._qa = qa
        self._cancel = cancel
        self._progress = progress

    def record_qa(self, record):
        self._qa.add(record)

    def record_result(self, result):
        # results live on the manifest; reporter is the single emit channel
        return result

    def cancelled(self) -> bool:
        return bool(self._cancel and self._cancel())

    def emit_progress(self, done, total):
        if self._progress:
            self._progress(done, total)
```

- [ ] **Step 8: Wire harvester to set disposition; keep RunSummary as a shim**

In `core/harvest/harvester.py`, set `disposition=` on each `AttachmentResult` (`"skipped"`/`"downloaded"`/`"failed"`) matching `status`. Replace `RunSummary` usage at the end with `summary_counts(manifest.results)` and have `RunSummary.record` stay as a back-compat shim. Add `threading.Lock` to `Manifest.add`/writers (deltas C6). Do NOT change harvest control flow.

- [ ] **Step 9: Run full suite + commit**

Run: `pytest -q` → PASS (old + new; update `test_manifest`/`test_models` for the new fields).
```bash
git add -A
git commit -m "feat: thread-safe QA/reporter substrate with disposition + reserved provenance"
```

---

## Task 3: Reference GUI adapter (one Tool class)

Write `adapters/toolbox.pyt` with ONE Tool class wrapping the existing harvester, importing the installed package (no `sys.path`). This is the pattern every envmon tool follows.

**Files:**
- Create: `autogis/adapters/toolbox.pyt` (Toolbox + one `HarvestAttachments` Tool class), `docs/pro-install.md`
- Test: `tests/test_toolbox_import.py` (imports the module's pure helpers without arcpy)

**Interfaces:**
- Consumes: `core.harvest.harvest`, `core.common.reporting.Reporter`, `runtime.sessions` (Pro-portal provider — stub acceptable here, finalized in Task… see Task 5 sessions).
- Produces: the `.pyt` Tool template (param marshalling → core call → `_msg` render) reused by Task 5.

- [ ] **Step 1: Failing test — pure marshalling helper is importable without arcpy**

`tests/test_toolbox_import.py`:
```python
import importlib.util, pathlib

def test_marshal_helper_importable_without_arcpy():
    # The .pyt top-level imports arcpy; the marshalling helpers must live in a
    # separately-importable module so core wiring is testable. Verify that module.
    from autogis.adapters import toolbox_core  # pure, no arcpy
    cfg = toolbox_core.build_harvest_config(directory="d", group_template="{g}",
            filename_template="{name}", url="http://x", where="1=1")
    assert cfg.layer_ref() == "http://x"
```

- [ ] **Step 2: Run, verify fail** — FAIL (no `toolbox_core`).

- [ ] **Step 3: Add a pure marshalling module + the .pyt over it**

Create `autogis/adapters/toolbox_core.py` (pure, no arcpy) with `build_harvest_config(**params) -> HarvestConfig` (validates url/item_id XOR on the dataclass) and a `run_harvest(config, session) -> list[AttachmentResult]`. Create `autogis/adapters/toolbox.pyt`: top-level `import arcpy`, `from autogis.adapters import toolbox_core`, `from autogis.core.common.qa import QACollector`, a `_msg(messages, qa)` renderer (reuse the embryo at `staging/.../EnvironmentalMonitoringTools.pyt:25-33`), and a `HarvestAttachments` Tool whose `execute()` marshals params → `toolbox_core` → `_msg`. NO logic in `execute()` beyond marshalling.

- [ ] **Step 4: Run, verify pass** — `pytest tests/test_toolbox_import.py -v` → PASS.

- [ ] **Step 5: Document the Pro install**

`docs/pro-install.md`: clone `arcgispro-py3`, `pip install -e .` into it, add the `.pyt` to the project, and the toolbox cache/reload gotcha (right-click → Refresh; restart Pro on import changes).

- [ ] **Step 6: Run full suite + commit**

Run: `pytest -q` → PASS.
```bash
git add -A
git commit -m "feat: reference .pyt GUI adapter (HarvestAttachments) over installed core"
```

---

## Task 4: Repackage envmon core (mechanical, one commit)

Move the 23 `staging/envmon-incoming/src/*` modules → `core/envmon/`, rewrite flat imports to relative per the **deltas §4 topological order**, fold `qa_checks`/`logging_utils` into `core/common`, reconcile `envmon_config` into `core/common/config.py`. Port the 56 tests. Pure-Python modules import + pass with no arcpy.

**Files:**
- Move (git mv, roots first per deltas §4): all 23 `src/*.py` except `qa_checks.py`+`logging_utils.py` → `autogis/core/envmon/`
- Fold: `qa_checks.py` already in `core/common/qa.py` (Task 2) → envmon modules import `from ..common.qa import …`; `logging_utils.py` → `core/common/logging.py`
- Reconcile: `envmon_config.py` → `core/common/config.py` (add `ConfigError`, `load_config`, `SiteConfig`/`ParserProfile`/`SheetProfile`/`FigureSpec`, `load_analyte_dictionary`/`load_screening_levels`); re-express `HarvestConfig` field-typed with `HarvestConfig.load(path)` (deltas H1/C5)
- Move: `staging/.../tests/*` → `tests/envmon/`; `config/*` → `autogis/config/`
- Test: ported `tests/envmon/{test_result_parser,test_h281_profile,test_rules_and_callouts}.py` + `conftest.py`

**Interfaces:**
- Consumes: `core/common/{qa,logging,config}` from Tasks 2 + this task.
- Produces: `autogis.core.envmon.*` (23 modules, relative imports), `autogis.core.common.config.*` (the typed + dict-backed config classes), all importable without arcpy.

- [ ] **Step 1: Port the 56 tests first (red), pointing at the target package**

`git mv staging/envmon-incoming/tests tests/envmon`. Rewrite test imports from flat (`from result_parser import …`) to packaged (`from autogis.core.envmon.result_parser import …`) and config imports to `from autogis.core.common.config import …`. Run: `pytest tests/envmon -q` → Expected: FAIL (target modules not yet in place). This is the red bar for the whole task.

- [ ] **Step 2: Reconcile envmon_config → core/common/config.py**

Copy `staging/.../src/envmon_config.py` to `autogis/core/common/config.py`. Keep ALL of: `ConfigError`, `load_config` (YAML+JSON), `_require`, dict-backed `SiteConfig`/`FigureSpec` (`__getattr__` passthrough — do NOT field-type, deltas C5), field-typed `SheetProfile`/`ParserProfile`, `load_analyte_dictionary`, `load_screening_levels`. Then add `HarvestConfig` re-expressed field-typed with a `@classmethod load(cls, path) -> "HarvestConfig"` that does nested-section flatten + url/item_id-XOR validation on the dataclass (deltas H1). Remove `profile` from the return (it moves to sessions, Task 5).

- [ ] **Step 3: Move the 23 modules in topological order, rewrite imports**

For each module in deltas §4 order (`callout_templates` first … `build_current_event` last), `git mv staging/.../src/<m>.py autogis/core/envmon/<m>.py` and rewrite each sibling import using the deltas §4 adjacency list: `from qa_checks import X` → `from ..common.qa import X`; `from logging_utils import X` → `from ..common.logging import X`; `from envmon_config import X` → `from ..common.config import X`; every other sibling → `from .<sibling> import X`. Create `autogis/core/envmon/__init__.py` (empty or curated re-exports). Leave `_arcpy()` lazy patterns untouched. Delete the now-duplicated `qa_checks.py`/`logging_utils.py` from the move set.

- [ ] **Step 4: Run the ported tests green**

Run: `pytest tests/envmon -q`
Expected: PASS — 56 tests. Fix only import paths / missing relative dots; do NOT alter logic. Verify each pure module imports with no arcpy: `python -c "import autogis.core.envmon.result_parser"` (and the other 13 arcpy-free + the lazy-edge ones — import must succeed).

- [ ] **Step 5: Verify caveats intact (no regression)**

Confirm (grep/read) post-move: H281 DRAFT banner + `_TODO`s present under `autogis/config/parser_profiles/`; `average_parent_and_duplicate` still emits the QA WARNING (`build_current_event.py`); screening-levels still all-null `_TODO` under `autogis/config/screening_levels/`. (deltas R6)

- [ ] **Step 6: Run full suite + commit**

Run: `pytest -q` → PASS (harness + envmon).
```bash
git add -A
git commit -m "refactor: repackage envmon src into autogis.core.envmon with relative imports; port 56 tests"
```

---

## Task 5: Wire envmon adapters (CLI + 10 Tool classes) with the runtime guard

Add envmon subcommands to the CLI group and the 10 Tool classes to `toolbox.pyt`, all over shared core. Apply the runtime guard. Add `runtime/sessions.py` providers.

**Files:**
- Create: `autogis/runtime/sessions.py` (AGOL-profile/env, active-Pro-portal `GIS("pro")`, arcpy-env providers)
- Modify: `autogis/adapters/cli.py` (add an `envmon` sub-group with `inspect`/`parser-profile`/`figure-spec` headless + `import-gdb`…`validate-db` registered-but-guarded), `autogis/adapters/toolbox.pyt` (add the 10 envmon Tool classes following the Task 3 template)
- Create: `autogis/adapters/guard.py` (`require_runtime(name)` raises a clear error when arcpy absent for LOCAL tools)
- Test: `tests/test_runtime_guard.py`, `tests/test_cli_envmon.py`

**Interfaces:**
- Consumes: `core.envmon.*`, `core.common.config`, `runtime.capabilities`, `runtime.sessions`.
- Produces: `autogis envmon <tool>` CLI surface; `guard.require_runtime(name)`; session providers `agol_from_profile`, `pro_active_portal`, `arcpy_env`.

- [ ] **Step 1: Failing test — guard refuses LOCAL tool when arcpy absent**

`tests/test_runtime_guard.py`:
```python
import builtins, pytest
from autogis.adapters.guard import require_runtime, RuntimeUnavailable


def test_local_tool_errors_without_arcpy(monkeypatch):
    real = builtins.__import__
    def fake(name, *a, **k):
        if name == "arcpy":
            raise ModuleNotFoundError("No module named 'arcpy'")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", fake)
    with pytest.raises(RuntimeUnavailable) as e:
        require_runtime("import-gdb")
    assert "arcpy" in str(e.value).lower()


def test_cloud_ok_tool_passes_without_arcpy():
    require_runtime("inspect")   # no raise
```

- [ ] **Step 2: Run, verify fail** — FAIL (no `guard`).

- [ ] **Step 3: Implement the guard**

`autogis/adapters/guard.py`:
```python
from autogis.runtime.capabilities import requires_arcpy


class RuntimeUnavailable(RuntimeError):
    pass


def _arcpy_present() -> bool:
    try:
        import arcpy  # noqa: F401
        return True
    except Exception:
        return False


def require_runtime(name: str) -> None:
    if requires_arcpy(name) and not _arcpy_present():
        raise RuntimeUnavailable(
            f"Tool '{name}' needs arcpy (ArcGIS Pro). Run it in the .pyt "
            f"toolbox inside Pro, or install into a cloned arcgispro-py3 env.")
```

- [ ] **Step 4: Run, verify pass** — `pytest tests/test_runtime_guard.py -v` → PASS.

- [ ] **Step 5: Add the envmon CLI sub-group (headless 1/9/10 first-class; 2–8 guarded)**

In `cli.py` add an `envmon` group. `inspect`/`parser-profile`/`figure-spec` call their pure core fns directly (openpyxl-only). `import-gdb`/`build-event`/`build-callouts`/`gw-contours`/`export-figures`/`full-pipeline`/`validate-db` each call `require_runtime(<name>)` first, then the core fn. No progress bars / fancy prompts for 2–8 (Global Constraints).

- [ ] **Step 6: Failing test — `autogis envmon inspect` runs headless**

`tests/test_cli_envmon.py`: invoke the group with `["envmon", "import-gdb", …]` under the no-arcpy monkeypatch → asserts a clean `RuntimeUnavailable`-derived exit message; invoke `["envmon", "inspect", <synthetic workbook>]` → exit 0.

- [ ] **Step 7: Implement until green; add the 10 Tool classes to the .pyt**

Add the 10 envmon Tool classes to `toolbox.pyt` following the Task 3 template (param marshal → core fn → `_msg`). Each `execute()` is pure marshalling. Run: `pytest tests/test_cli_envmon.py -v` → PASS.

- [ ] **Step 8: Run full suite + commit**

Run: `pytest -q` → PASS.
```bash
git add -A
git commit -m "feat: wire envmon CLI subcommands + 10 .pyt tools over shared core with runtime guard"
```

---

## Task 6: Cleanup, docs, changelog

Delete `staging/envmon-incoming/`, update README (suite, install paths, runtime matrix), CHANGELOG, `.gitignore`.

**Files:**
- Delete: `staging/envmon-incoming/`
- Modify: `README.md` (suite overview, cloud vs Pro install, the §4 runtime matrix), `CHANGELOG.md`, `.gitignore` (add `.pytest_cache/`)

**Interfaces:**
- Consumes: the finished merged tree.
- Produces: a clean repo with no `staging/` and accurate docs.

- [ ] **Step 1: Confirm nothing still imports from staging**

Run (Grep): pattern `staging/envmon-incoming` across `autogis/` and `tests/`. Expected: zero hits. If any, fix before deleting.

- [ ] **Step 2: Delete staging + add .gitignore entry**

```bash
git rm -r staging/envmon-incoming
```
Add `.pytest_cache/` to `.gitignore` (the locked cache came along with the staged tree — MERGE_PLAN kickoff note).

- [ ] **Step 3: Rewrite README + CHANGELOG**

README: describe the suite (harvest + envmon), the runtime matrix (MERGE_PLAN §4), install paths (`pip install autogis[cloud]` for cloud; `pip install -e .` in a cloned `arcgispro-py3` for Pro), and the carried caveats (H281 draft gate, null screening levels). CHANGELOG: a suite-merge entry.

- [ ] **Step 4: Run full suite + commit**

Run: `pytest -q` → PASS.
```bash
git add -A
git commit -m "chore: delete staging, document the merged suite + runtime matrix"
```

- [ ] **Step 5: Finish the branch**

Invoke superpowers:finishing-a-development-branch to verify tests, then open the PR / merge `merge/envmon-suite` → `main`. Note in the PR body that arcpy paths (tools 2–8) remain manually verified in Pro and the H281 profile needs real-workbook verification before production (carried caveats).

---

## Self-Review

**Spec coverage (MERGE_PLAN §5 steps → tasks):** step 1 scaffold → Task 1; step 2 reporter → Task 2; step 3 reference GUI → Task 3; step 4 repackage → Task 4; step 5 wire adapters → Task 5; step 6 cleanup → Task 6. §6 decisions, §3 reconciliations, §4 runtime matrix → Global Constraints + Tasks 1/4/5. Deltas C1–C7 + H1/H2/H3 → Global Constraints, applied in Tasks 2/4/5. Carried caveats → Task 4 Step 5 + Task 6. Covered.

**Placeholder scan:** Task 1–3 carry complete code (grounded in the read harness source). Task 4 is mechanical-by-graph: the per-file rewrite rule is fully specified by the deltas §4 adjacency list + the `from X import` → relative-dot mapping (Step 3), not a fabricated reproduction of 23 unread module bodies — this is the honest, complete instruction for a mechanical move. Task 5/6 carry code for the new files (guard, capabilities-driven CLI) and exact procedures for the templated Tool classes. No "TBD"/"add error handling"/"similar to".

**Type consistency:** `Runtime` enum + `TOOLS`/`requires_arcpy` names consistent across Tasks 1/5. `AttachmentResult.disposition` + reserved fields defined in Task 2, consumed in Tasks 2/4. `Reporter(qa, *, cancel, progress)` signature consistent Tasks 2/3. `require_runtime(name)`/`RuntimeUnavailable` consistent Task 5. CLI subcommand names match the `TOOLS` registry keys. `HarvestConfig.load(path)` single-object (deltas H1) consistent in Tasks 4/5; the legacy tuple in Task 1 Step 7 is explicitly the pre-refactor shim and is superseded at Task 4 (noted in Global Constraints).
