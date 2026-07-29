from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import autogis
from autogis.core.common.run_history import RunHistory

_N = 25

# Runs in a real child process (cross-*process* safety is the point --
# threads share the GIL and one fd table and would not exercise the race).
_WRITER = """
import sys, time
from datetime import datetime
from pathlib import Path

from autogis.core.common.run_history import RunHistory, RunRecord

csv_path, ready_path, go_path, tag, n = sys.argv[1:6]
Path(ready_path).touch()
deadline = time.monotonic() + 30
while not Path(go_path).exists():
    if time.monotonic() > deadline:
        sys.exit("go-file barrier timed out")
    time.sleep(0.005)
h = RunHistory(Path(csv_path))
for i in range(int(n)):
    h.write(RunRecord(
        run_id=f"{tag}-{i}", tool_name="ConcTool", site_id="H281",
        event_id=None,
        started_at=datetime(2026, 1, 1, 0, 0, 0),
        finished_at=datetime(2026, 1, 1, 0, 0, 1),
        status="success", inputs={}, outputs={},
        qa_count_error=0, qa_count_warning=0, qa_count_info=0,
        message=f"writer {tag} record {i}",
    ))
"""


@pytest.mark.skipif(
    os.name != "nt",
    reason="ADR-0051's _sentinel_lock is built on msvcrt.locking and is a "
           "documented no-op off Windows, so this races a lock that does not "
           "exist and asserts an invariant the code makes no attempt to hold "
           "there (~1 in 3 failures on Linux, issue #374). The deployment "
           "target is Windows/SMB; on Windows this stays a real regression "
           "test for the TOCTOU race below.",
)
def test_two_process_writers_single_header_and_clean_parse(tmp_path):
    """Two real processes racing on first-write must yield exactly one header
    row, 2N data rows, and a file query() parses cleanly.

    The old unlocked write path checked Path.exists() before open (TOCTOU):
    two simultaneous first-writers could both emit a header, and a mid-file
    header row makes _decode raise on int("qa_count_error"), turning the
    whole file into a RunHistoryError for every later reader.
    """
    csv_path = tmp_path / "run_history.csv"
    go_path = tmp_path / "go"
    env = dict(os.environ)
    # Children must import the same autogis the test process did (a worktree
    # run must not fall back to an installed copy on sys.path).
    env["PYTHONPATH"] = str(Path(autogis.__file__).resolve().parents[1])

    procs = []
    for tag in ("a", "b"):
        ready = tmp_path / f"ready-{tag}"
        procs.append((
            ready,
            subprocess.Popen(
                [sys.executable, "-c", _WRITER,
                 str(csv_path), str(ready), str(go_path), tag, str(_N)],
                env=env,
            ),
        ))

    deadline = time.monotonic() + 30
    while not all(ready.exists() for ready, _ in procs):
        assert time.monotonic() < deadline, "writer children never became ready"
        time.sleep(0.005)
    go_path.touch()  # release both writers at once so the first-writes race

    for _, proc in procs:
        assert proc.wait(timeout=60) == 0

    lines = csv_path.read_text(encoding="utf-8").splitlines()
    header = lines[0]
    assert header.startswith("run_id,"), f"first line is not a header: {header!r}"
    assert sum(1 for ln in lines if ln == header) == 1, "duplicate header row"
    assert len(lines) == 2 * _N + 1  # one header + every record from both writers

    records = RunHistory(csv_path).query()  # must not raise RunHistoryError
    assert len(records) == 2 * _N
    assert {r.run_id for r in records} == {
        f"{tag}-{i}" for tag in ("a", "b") for i in range(_N)
    }
