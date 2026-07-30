"""ArcGIS Pro subprocess seam for groundwater-model review (#384)."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from .executor import Decision, Step, run_step

_MARKER = "AUTOGIS_GW_MODEL_REVIEWS="
_READ_SCRIPT = (
    "import json,sys;"
    "from autogis.core.envmon.gw_model_pipeline "
    "import read_gw_model_reviews;"
    f"print({_MARKER!r}+json.dumps(read_gw_model_reviews(sys.argv[1]),"
    "default=str))"
)


def load_review_runs(local_python: str, gdb: str,
                     timeout: float = 60) -> list[dict]:
    """Read review rows through the configured ArcGIS Pro interpreter."""
    if not str(local_python).strip():
        raise ValueError("arcgispro-py3 python.exe is required")
    if not str(gdb).strip():
        raise ValueError("file geodatabase is required")
    proc = subprocess.run(
        [str(local_python), "-c", _READ_SCRIPT, str(gdb)],
        capture_output=True, encoding="utf-8", errors="replace",
        timeout=timeout,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    if proc.returncode:
        detail = proc.stderr.strip() or proc.stdout.strip() or "no output"
        raise RuntimeError(
            f"could not read GW_ModelRun review data: {detail}")
    line = next(
        (line for line in reversed(proc.stdout.splitlines())
         if line.startswith(_MARKER)),
        None,
    )
    if line is None:
        raise RuntimeError(
            "ArcGIS Pro review reader returned no structured result")
    records = json.loads(line[len(_MARKER):])
    if not isinstance(records, list):
        raise RuntimeError("ArcGIS Pro review reader returned invalid data")
    return records


def approve_model(local_python: str, gdb: str, run_id: str, model: str,
                  reviewer: str, *, site_id: str = "",
                  event_id: str = "") -> str:
    """Invoke the existing approval CLI/backend through ArcGIS Pro."""
    values = {
        "gdb": gdb, "run_id": run_id, "model": model,
        "reviewer": reviewer, "site_id": site_id, "event_id": event_id,
    }
    with tempfile.TemporaryDirectory(prefix="autogis-gw-approval-") as job:
        result = run_step(
            Step(("envmon", "approve-gw-model"), values),
            Path(job), local_python=local_python)
    if result.decision is not Decision.CONTINUE:
        raise RuntimeError(result.reason)
    return result.stdout.strip()
