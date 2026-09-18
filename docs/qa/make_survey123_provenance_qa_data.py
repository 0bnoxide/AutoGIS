"""make_survey123_provenance_qa_data.py — synthetic inputs for the #414 rehearsal.

Stages a closed Survey123-shaped device SQLite export plus complete hosted and
client snapshots with KNOWN provenance truth, so the operator can rehearse the
exact ``envmon trace-survey123`` command shape before spending a real device
export. Every row exercises one status in the operator guide's table.

Output goes to a staging folder OUTSIDE the repo (default:
``~/Desktop/AutoGIS-QA/survey123/``) — synthetic QA data is never committed.

Usage (base install, no extras):
    python docs/qa/make_survey123_provenance_qa_data.py            # Desktop
    python docs/qa/make_survey123_provenance_qa_data.py --out DIR
    python docs/qa/make_survey123_provenance_qa_data.py --check    # self-test
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

ROOT = "inspection"
KEY = "record_id"
OBSERVED_AT = "2026-09-17T10:00:00+00:00"

# Device rows: (identity, Surveys.status, __meta__.editMode).
# status: 0 draft, 1 outbox, 2 sent, 3 submission error, 4 inbox.
# The GUID is braced/upper on the device and bare/lower downstream on purpose:
# an identity match here proves UUID normalization, a real-run risk.
GUID_DEVICE = "{A1B2C3D4-0000-4000-8000-000000000001}"
GUID_HOSTED = "a1b2c3d4-0000-4000-8000-000000000001"
DEVICE_ROWS = [
    (GUID_DEVICE, 2, 0),   # sent, new   -> visible_at_client
    ("upstream", 2, 0),    # sent, new   -> hosted_not_visible_at_client
    ("unsent", 1, 0),      # outbox, new -> device_only (still new-ready)
    ("downloaded", 4, 0),  # inbox copy  -> excluded_inbox_rows
    ("edited", 2, 1),      # sent, edit  -> hosted, NOT new-ready
    ("draft", 0, 0),       # draft       -> device_only, NOT new-ready
]
HOSTED_KEYS = [GUID_HOSTED, "upstream", "edited"]
CLIENT_KEYS = [GUID_HOSTED, "client-only"]

# Ground truth asserted by --check and cited in the runbook.
EXPECTED_COUNTS = {
    "device_rows": 5, "excluded_inbox_rows": 1, "device_unique": 5,
    "hosted_rows": 3, "client_rows": 2,
    "device_new_ready_unique": 3,
    "device_new_ready_hosted_unique": 2,
    "device_new_ready_client_unique": 1,
    "visible_at_client": 1, "hosted_not_visible_at_client": 2,
    "device_only": 2, "client_only": 1, "needs_review": 0,
}


def stage(out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    db = out / "device.sqlite"
    if db.exists():
        db.unlink()
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute("CREATE TABLE Surveys (name TEXT, data TEXT, status INTEGER)")
        conn.executemany("INSERT INTO Surveys VALUES (?, ?, ?)", [
            ("survey", json.dumps({ROOT: {KEY: key, "__meta__": {"editMode": mode}}}), status)
            for key, status, mode in DEVICE_ROWS])
    for name, keys in (("hosted.json", HOSTED_KEYS), ("client.json", CLIENT_KEYS)):
        (out / name).write_text(json.dumps({
            "version": 1, "complete": True, "source": f"export:{name[:-5]}-qa",
            "observed_at": OBSERVED_AT,
            "features": [{"attributes": {KEY: key}} for key in keys],
        }), encoding="utf-8")
    return out


def check() -> None:
    from click.testing import CliRunner

    from autogis.adapters.cli import autogis

    with tempfile.TemporaryDirectory() as tmp:
        out = stage(Path(tmp) / "qa")
        result = CliRunner().invoke(autogis, [
            "envmon", "trace-survey123", "--device", str(out / "device.sqlite"),
            "--device-root", ROOT, "--device-key", KEY,
            "--hosted-json", str(out / "hosted.json"), "--hosted-key", KEY,
            "--client-json", str(out / "client.json"), "--client-key", KEY,
            "--out", str(out / "report")],
            env={"AUTOGIS_RUN_HISTORY": str(Path(tmp) / "history.csv")})
        report = out / "report/provenance.json"
        assert result.exit_code == 2 and report.exists(), (result.exit_code, result.output)
        counts = json.loads(report.read_text())["counts"]
        bad = {k: (counts.get(k), v) for k, v in EXPECTED_COUNTS.items() if counts.get(k) != v}
        assert not bad, f"counts differ (got, expected): {bad}"
    print("CHECK OK:", EXPECTED_COUNTS)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path.home() / "Desktop/AutoGIS-QA/survey123")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if args.check:
        check()
    else:
        print("STAGED:", stage(args.out).resolve())


if __name__ == "__main__":
    main()
