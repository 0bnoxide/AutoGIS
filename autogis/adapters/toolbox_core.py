"""Pure (arcpy-free) marshalling helpers for the .pyt GUI adapter.

The Esri ``.pyt`` toolbox imports ``arcpy`` at module top level, so the
param-marshalling + core-wiring logic lives here instead — importable and
unit-testable with neither ``arcgis`` nor ``arcpy`` present. Both the GUI
(`toolbox.pyt`) and the test suite go through this single seam.

Single validation source (MERGE_PLAN §2): construct AND validate the same
``HarvestConfig`` dataclass the CLI uses, including the url-XOR-item_id
invariant — enforced here at build time, not deferred to ``layer_ref()``.

Today this module covers only the harvester (``build_harvest_config`` /
``run_harvest``); the ten envmon ``.pyt`` tools still marshal parameters
inline in their own ``execute()`` bodies, which is fine while that logic
stays a thin pass-through to a core function. When an envmon tool's
``execute()`` grows beyond a pass-through (branching, multi-step
orchestration, error handling that isn't just "call core, print QA") --
e.g. ``FullPipeline``, ``toolbox.pyt`` -- move its marshalling into this
module per the harvester's pattern, so it becomes unit-testable outside
Pro instead of only discoverable by running the tool inside ArcGIS Pro.
See issue #108 / the fable-architecture-review finding M2.
"""
import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime
from functools import wraps
from pathlib import Path

from autogis.core.harvest.models import HarvestConfig, AttachmentResult


def build_harvest_config(
    *,
    directory: str,
    group_template: str,
    filename_template: str,
    item_id: str | None = None,
    url: str | None = None,
    where: str = "1=1",
    incremental: bool = False,
    skip_existing: bool = True,
    retries: int = 3,
    backoff_seconds: float = 2,
) -> HarvestConfig:
    """Build + validate a HarvestConfig from marshalled GUI params.

    Enforces the (item_id XOR url) invariant up front (single validation
    source on the dataclass) rather than leaving it to ``layer_ref()``.
    """
    if bool(item_id) == bool(url):
        raise ValueError(
            "HarvestConfig requires exactly one of 'url' or 'item_id'.")
    config = HarvestConfig(
        directory=directory,
        group_template=group_template,
        filename_template=filename_template,
        item_id=item_id,
        url=url,
        where=where if where is not None else "1=1",
        incremental=incremental,
        skip_existing=skip_existing,
        retries=retries,
        backoff_seconds=backoff_seconds,
    )
    # Trip the dataclass's own validation now so a bad config fails at build
    # time, in either adapter, before any session work.
    config.layer_ref()
    return config


def run_harvest(config: HarvestConfig, session) -> list[AttachmentResult]:
    """Run the core harvester for ``config`` against an active GIS ``session``.

    Thin pass-through to ``core.harvest.harvest``; kept here so the .pyt's
    ``execute()`` stays pure marshalling.
    """
    from autogis.core.harvest.harvester import harvest

    summary = harvest(session, config)
    return list(summary.results)


def _pyt_run_history_path(dest_hint: Path | None) -> Path | None:
    """Resolve the Pro-safe run-history destination (ADR-0068)."""
    dest = os.environ.get("AUTOGIS_RUN_HISTORY", "")
    if dest.lower() == "off":
        return None
    if dest:
        return Path(dest)
    if dest_hint:
        return Path(dest_hint) / "run_history.csv"
    return Path.cwd() / "run_history.csv"


def _site_id_from_config(path: str | None) -> str:
    if not path:
        return ""
    try:
        from autogis.core.common.config import load_config
        return str(load_config(Path(path)).get("site_id") or "")
    except Exception:
        return ""


@contextmanager
def recording_pyt_run(tool_name: str, *, inputs: dict, dest_hint: Path | None,
                      site_id: str = "", event_id: str | None = None):
    """Best-effort run-history recording around one `.pyt` execution."""
    started = datetime.now()
    exc = None
    try:
        yield
    except BaseException as err:
        exc = err
        raise
    finally:
        try:
            path = _pyt_run_history_path(dest_hint)
            if path is not None:
                from autogis.core.common.run_history import RunHistory, RunRecord
                status = "success" if exc is None else (
                    "cancelled" if isinstance(exc, KeyboardInterrupt) else "error")
                RunHistory(path).write(RunRecord(
                    run_id=str(uuid.uuid4()), tool_name=tool_name, site_id=site_id,
                    event_id=event_id, started_at=started, finished_at=datetime.now(),
                    status=status, inputs=json.loads(json.dumps(inputs, default=str)),
                    outputs={}, qa_count_error=0, qa_count_warning=0,
                    qa_count_info=0,
                    message="" if exc is None else f"{type(exc).__name__}: {exc}",
                ))
        except Exception:
            pass  # observability must not change a Pro tool's outcome


def record_pyt_run(tool_name: str, *, gdb_param: str = "gdb",
                   site_config_param: str | None = "site_config",
                   event_param: str = "event_date"):
    """Decorate a thin `.pyt` execute method with the shared recorder."""
    def decorator(execute):
        @wraps(execute)
        def wrapped(self, parameters, messages):
            inputs = {p.name: p.valueAsText for p in parameters}
            gdb = inputs.get(gdb_param)
            with recording_pyt_run(
                tool_name, inputs=inputs,
                dest_hint=Path(gdb).parent if gdb else None,
                site_id=_site_id_from_config(inputs.get(site_config_param)),
                event_id=inputs.get(event_param) or None,
            ):
                return execute(self, parameters, messages)
        return wrapped
    return decorator
