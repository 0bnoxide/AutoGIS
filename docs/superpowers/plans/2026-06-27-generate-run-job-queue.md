# GenerateRunJobQueue (Tool 10.4) — Implementation Plan

**Goal:** Add a headless `envmon generate-job-queue` CLI command + core module that
reads a site config directory and a list of requested tools, and emits a JSON job
queue: an ordered list of `{tool, site_id, args}` objects ready to be dispatched
by a runner (CI, cloud function, or local queue). Tools are ordered by dependency
(headless cloud tools before local arcpy tools). This enables reproducible batch
runs across multiple sites from a single manifest.

**Architecture:** New pure-core module `autogis/core/envmon/job_queue.py` with
`generate_job_queue(site_ids, tool_names, extra_args, *, qa) -> list[JobEntry]`.
A `click` command reads a YAML manifest, calls the function, writes `queue.json`,
renders QA + exit. No arcpy, no openpyxl.

**Tech stack:** Python 3.14, `click`, `pyyaml`, stdlib `json`/`dataclasses`,
`pytest`. Reuses: `QACollector` (`common/qa.py`), `_render_qa` (`cli.py`),
`TOOLS` / `Runtime` (`runtime/capabilities.py`).

## Global constraints

- `core/` and `adapters/` import without arcpy. Headless — no `_guard`.
- Command name exactly `generate-job-queue`. Register as `Runtime.CLOUD`.
- Tool ordering: `Runtime.CLOUD` jobs first, then `Runtime.HYBRID`, then
  `Runtime.LOCAL` — mirrors the natural pipeline order (headless ingest → local
  GDB build → local figure export).
- Unknown tool names (not in `TOOLS`) emit WARNING `unknown_tool`.
- Each `JobEntry` carries: `tool` (str), `site_id` (str), `runtime` (str),
  `args` (dict), `order` (int, 0-based within the sorted list).
- The queue JSON is an array of `{tool, site_id, runtime, args, order}` objects.

---

### Task 1: Core module `job_queue.py` + unit tests

**Files:**
- Create: `autogis/core/envmon/job_queue.py`
- Create: `tests/test_job_queue.py`

**Complete code:**

```python
"""Generate an ordered job queue for multi-site batch runs (Tool 10.4)."""
from __future__ import annotations
import dataclasses
from typing import Any, Dict, List, Optional
from ..common.qa import QACollector, SEV_INFO, SEV_WARNING
from ...runtime.capabilities import TOOLS, Runtime

_RUNTIME_ORDER = {Runtime.CLOUD: 0, Runtime.HYBRID: 1, Runtime.LOCAL: 2}


@dataclasses.dataclass
class JobEntry:
    tool: str
    site_id: str
    runtime: str
    args: Dict[str, Any]
    order: int

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


def generate_job_queue(
    site_ids: List[str],
    tool_names: List[str],
    extra_args: Optional[Dict[str, Dict[str, Any]]],
    *,
    qa: QACollector,
) -> List[JobEntry]:
    """Build ordered job queue entries for (site × tool) cross-product."""
    extra_args = extra_args or {}

    # Validate tool names.
    valid_tools = []
    for name in tool_names:
        if name not in TOOLS:
            qa.add(SEV_WARNING, "unknown_tool",
                   f"Tool {name!r} not in capabilities.TOOLS; skipped")
        else:
            valid_tools.append(name)

    if not valid_tools:
        qa.add(SEV_WARNING, "no_valid_tools",
               "No valid tools specified; job queue is empty.")

    # Sort tools: CLOUD → HYBRID → LOCAL, then alphabetically within tier.
    valid_tools.sort(key=lambda t: (_RUNTIME_ORDER.get(TOOLS[t], 99), t))

    entries: List[JobEntry] = []
    order = 0
    for tool in valid_tools:
        runtime = TOOLS[tool]
        for site_id in site_ids:
            args = {**(extra_args.get(tool) or {}),
                    **(extra_args.get(f"{tool}:{site_id}") or {})}
            entries.append(JobEntry(
                tool=tool, site_id=site_id,
                runtime=runtime.value, args=args, order=order))
            order += 1

    qa.add(SEV_INFO, "job_queue_complete",
           f"generate_job_queue: {len(entries)} job(s) for "
           f"{len(valid_tools)} tool(s) × {len(site_ids)} site(s)")
    return entries
```

**Test file `tests/test_job_queue.py`:**

```python
"""Unit tests for job_queue (Tool 10.4)."""
from autogis.core.common.qa import QACollector
from autogis.core.envmon.job_queue import generate_job_queue


def test_basic_queue():
    qa = QACollector()
    entries = generate_job_queue(
        ["H281"], ["inspect", "import-gdb"], None, qa=qa)
    # inspect = CLOUD, import-gdb = LOCAL → inspect comes first
    assert entries[0].tool == "inspect"
    assert entries[1].tool == "import-gdb"
    assert entries[0].runtime == "cloud"
    assert entries[1].runtime == "local"


def test_unknown_tool_warns():
    qa = QACollector()
    entries = generate_job_queue(["H281"], ["no-such-tool"], None, qa=qa)
    assert len(entries) == 0
    assert any(r.category == "unknown_tool" for r in qa.records)


def test_multi_site():
    qa = QACollector()
    entries = generate_job_queue(["H281", "H282"], ["inspect"], None, qa=qa)
    assert len(entries) == 2
    site_ids = [e.site_id for e in entries]
    assert "H281" in site_ids and "H282" in site_ids


def test_extra_args_merged():
    qa = QACollector()
    extra = {"inspect": {"format": "json"}}
    entries = generate_job_queue(["H281"], ["inspect"], extra, qa=qa)
    assert entries[0].args == {"format": "json"}


def test_order_field_sequential():
    qa = QACollector()
    entries = generate_job_queue(["S1", "S2"], ["inspect", "import-gdb"], None, qa=qa)
    orders = [e.order for e in entries]
    assert orders == list(range(len(orders)))
```

**Steps:**
- [ ] Write test file, verify ImportError.
- [ ] Implement `job_queue.py`.
- [ ] Run unit tests, verify pass.

---

### Task 2: Wire CLI + register

**Manifest YAML format:**
```yaml
sites: ["H281", "H282"]
tools: ["inspect", "import-edd", "apply-screening", "import-gdb"]
args:
  inspect:
    format: json
  import-edd:
    strict: true
```

```python
@envmon.command("generate-job-queue")
@click.option("--manifest", required=True, type=click.Path(exists=True),
              help="YAML with sites, tools, and optional args.")
@click.option("--output", required=True, type=click.Path(),
              help="Output JSON queue file.")
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error")
def generate_job_queue_cmd(manifest, output, report, fail_on):
    """Tool 10.4: generate ordered job queue JSON from a manifest YAML."""
    ...
```

`capabilities.py`: `"generate-job-queue": Runtime.CLOUD`

**Steps:**
- [ ] Write failing CLI test, verify fail.
- [ ] Add command, update capabilities.
- [ ] Full suite, commit: `feat(envmon): generate-job-queue — ordered batch job queue from manifest (Tool 10.4)`
