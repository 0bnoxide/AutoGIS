"""
test_cli_estimate_gw_flow.py

CLI integration tests for the estimate-gw-flow-direction command.

These four test cases are taken directly from the planned-but-skipped section
in docs/superpowers/plans/2026-06-28-estimate-gw-flow-direction.md (Task 2 —
CLI layer tests).

Geometry:
  Flow-east scenario: MW-01(0,0,100), MW-02(100,0,99), MW-03(0,100,100)
  The GWE surface drops 1 ft per 100 ft heading east → azimuth 90°.

  Collinear scenario: MW-01(0,0,100), MW-02(100,0,99), MW-03(200,0,98)
  All three wells on the same east-west line → no unique plane → ERROR.
"""
import csv
from pathlib import Path

from click.testing import CliRunner

from autogis.adapters.cli import autogis as autogis_cli


def _write_wells_csv(tmp_path, rows):
    p = tmp_path / "wells.csv"
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(
            fh, fieldnames=["well_id", "easting", "northing", "gwe_ft"]
        )
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return str(p)


_FLOW_EAST_WELLS = [
    {"well_id": "MW-01", "easting": 0.0,   "northing": 0.0,   "gwe_ft": 100.0},
    {"well_id": "MW-02", "easting": 100.0, "northing": 0.0,   "gwe_ft": 99.0},
    {"well_id": "MW-03", "easting": 0.0,   "northing": 100.0, "gwe_ft": 100.0},
]

_COLLINEAR_WELLS = [
    {"well_id": "MW-01", "easting": 0.0,   "northing": 0.0, "gwe_ft": 100.0},
    {"well_id": "MW-02", "easting": 100.0, "northing": 0.0, "gwe_ft": 99.0},
    {"well_id": "MW-03", "easting": 200.0, "northing": 0.0, "gwe_ft": 98.0},
]


def test_cli_estimate_gw_flow_direction_in_help():
    """Command name appears in 'envmon --help' output."""
    result = CliRunner().invoke(autogis_cli, ["envmon", "--help"])
    assert result.exit_code == 0, f"envmon --help failed:\n{result.output}"
    assert "estimate-gw-flow-direction" in result.output


def test_cli_estimate_gw_flow_direction_east(tmp_path):
    """Flow-east scenario: azimuth 90° and DRAFT_REVIEW_REQUIRED in stdout; exit 0."""
    csv_path = _write_wells_csv(tmp_path, _FLOW_EAST_WELLS)

    result = CliRunner().invoke(
        autogis_cli,
        [
            "envmon", "estimate-gw-flow-direction",
            "--wells-csv", csv_path,
            "--site-id", "TEST",
            "--event-date", "2026-06-28",
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, (
        f"estimate-gw-flow-direction (east) exited {result.exit_code}:\n{result.output}"
    )
    assert "90.0" in result.output, (
        f"Expected azimuth '90.0' in stdout:\n{result.output}"
    )
    assert "DRAFT_REVIEW_REQUIRED" in result.output, (
        f"Expected 'DRAFT_REVIEW_REQUIRED' in stdout:\n{result.output}"
    )


def test_cli_estimate_gw_flow_direction_output_csv(tmp_path):
    """--output flag writes a single-row CSV with flow_azimuth_deg, qa_status, draft."""
    csv_path = _write_wells_csv(tmp_path, _FLOW_EAST_WELLS)
    out_path = str(tmp_path / "result.csv")

    result = CliRunner().invoke(
        autogis_cli,
        [
            "envmon", "estimate-gw-flow-direction",
            "--wells-csv", csv_path,
            "--site-id", "TEST",
            "--event-date", "2026-06-28",
            "--output", out_path,
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, (
        f"estimate-gw-flow-direction (output CSV) exited {result.exit_code}:\n{result.output}"
    )

    rows = list(csv.DictReader(open(out_path, encoding="utf-8")))
    assert len(rows) == 1, f"Expected 1 row in output CSV, got {len(rows)}"
    assert abs(float(rows[0]["flow_azimuth_deg"]) - 90.0) < 0.01, (
        f"Expected flow_azimuth_deg ≈ 90.0, got {rows[0]['flow_azimuth_deg']}"
    )
    assert rows[0]["qa_status"] == "PASS", (
        f"Expected qa_status == 'PASS', got {rows[0]['qa_status']!r}"
    )
    assert rows[0]["draft"] == "True", (
        f"Expected draft == 'True', got {rows[0]['draft']!r}"
    )


def test_cli_estimate_gw_flow_direction_collinear_exits_1(tmp_path):
    """Collinear wells produce ERROR → _render_qa exits with code 1.

    'collinear' (case-insensitive) appears in stdout.
    """
    csv_path = _write_wells_csv(tmp_path, _COLLINEAR_WELLS)

    # catch_exceptions=True so SystemExit(1) is captured rather than raised.
    result = CliRunner().invoke(
        autogis_cli,
        [
            "envmon", "estimate-gw-flow-direction",
            "--wells-csv", csv_path,
            "--site-id", "TEST",
            "--event-date", "2026-06-28",
        ],
    )
    assert result.exit_code == 1, (
        f"Expected exit code 1 for collinear wells, got {result.exit_code}:\n{result.output}"
    )
    assert "collinear" in result.output.lower(), (
        f"Expected 'collinear' in stdout:\n{result.output}"
    )
