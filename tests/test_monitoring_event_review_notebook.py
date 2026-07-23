"""Phase 4 gate (ADR-0105): the monitoring-event review notebook must survive a
clean restart-and-run-all against the sanitized reference event.

Opt-in: needs the `notebook` extra (nbclient + ipykernel) and a `python3`
kernelspec. The arcpy-free dev suite without the extra skips this cleanly.
"""
import sys
from pathlib import Path

import pytest

nbformat = pytest.importorskip("nbformat")
nbclient = pytest.importorskip("nbclient")

REPO_ROOT = Path(__file__).resolve().parent.parent
NOTEBOOK = REPO_ROOT / "notebooks" / "monitoring_event_review.ipynb"


def test_restart_run_all_reference_event():
    if sys.platform == "win32":
        # zmq's proactor loop crashes ipykernel on Windows; the selector loop is
        # the documented workaround.
        import asyncio
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    from nbclient import NotebookClient
    from nbclient.exceptions import CellExecutionError
    try:
        from jupyter_client.kernelspec import NoSuchKernel
    except Exception:  # pragma: no cover - jupyter_client always ships with nbclient
        NoSuchKernel = ()

    nb = nbformat.read(str(NOTEBOOK), as_version=4)
    client = NotebookClient(
        nb, timeout=300, kernel_name="python3",
        resources={"metadata": {"path": str(REPO_ROOT)}},
    )
    try:
        client.execute()
    except NoSuchKernel:
        pytest.skip("no python3 kernelspec installed (needs the 'notebook' extra)")
    except CellExecutionError as exc:  # surface the failing cell
        pytest.fail(f"notebook restart-run-all failed:\n{exc}")

    # Prove cells produced output, not merely ran: readiness + report must render.
    text = "\n".join(
        out.get("text", "")
        + str(out.get("data", {}).get("text/html", ""))
        + str(out.get("data", {}).get("text/plain", ""))
        for cell in nb.cells if cell.cell_type == "code"
        for out in cell.get("outputs", [])
    )
    assert "producers): PASS" in text, "readiness cell did not render PASS from the current run"
    assert "Executive Summary" in text, "event-report HTML did not render"
