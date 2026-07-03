from autogis.core.envmon.import_rtk_survey import RTKPoint
from autogis.core.envmon.validate_rtk_survey import validate_rtk_points

_POINTS_OK = [
    RTKPoint("MW-01", 4527893.12, 293847.55, 512.34,
             hrms_ft=0.01, vrms_ft=0.02, fix_type="RTK_FIXED"),
    RTKPoint("MW-02", 4527750.00, 293900.00, 509.12,
             hrms_ft=0.01, vrms_ft=0.02, fix_type="RTK_FIXED"),
]

_POINTS_POOR = [
    RTKPoint("MW-03", 4527700.00, 293850.00, 508.00,
             hrms_ft=0.15, vrms_ft=0.20, fix_type="AUTONOMOUS"),
]

_POINTS_DUP = [
    RTKPoint("MW-01", 4527893.12, 293847.55, 512.34,
             hrms_ft=0.01, vrms_ft=0.02, fix_type="RTK_FIXED"),
    RTKPoint("MW-01", 4527893.10, 293847.53, 512.36,
             hrms_ft=0.01, vrms_ft=0.02, fix_type="RTK_FIXED"),
]


def test_valid_points_no_errors():
    qa = validate_rtk_points(_POINTS_OK)
    assert qa.counts_by_severity().get("ERROR", 0) == 0


def test_poor_precision_warns():
    qa = validate_rtk_points(_POINTS_POOR)
    cats = [r.category for r in qa.records]
    assert "hrms_exceeds_threshold" in cats or "fix_type_not_rtk" in cats


def test_autonomous_fix_warns():
    qa = validate_rtk_points(_POINTS_POOR)
    assert any(r.category == "fix_type_not_rtk" for r in qa.records)


def test_duplicate_point_id_warns():
    qa = validate_rtk_points(_POINTS_DUP)
    assert any(r.category == "duplicate_point_id" for r in qa.records)


def test_duplicate_point_id_pass_count_is_unique():
    qa = validate_rtk_points(_POINTS_DUP)
    summary = next(r for r in qa.records if r.category == "validation_complete")
    assert summary.message == "RTK validation: 1/2 points QA pass."


def test_duplicate_point_id_with_warning_does_not_count_as_pass():
    points = [
        RTKPoint("MW-01", 4527893.12, 293847.55, 512.34,
                 hrms_ft=0.15, vrms_ft=0.02, fix_type="AUTONOMOUS"),
        RTKPoint("MW-01", 4527893.10, 293847.53, 512.36,
                 hrms_ft=0.01, vrms_ft=0.02, fix_type="RTK_FIXED"),
    ]
    qa = validate_rtk_points(points)
    summary = next(r for r in qa.records if r.category == "validation_complete")
    assert summary.message == "RTK validation: 0/2 points QA pass."
    assert any(r.category == "fix_type_not_rtk" for r in qa.records)


def test_no_points_no_error():
    qa = validate_rtk_points([])
    assert qa.counts_by_severity().get("ERROR", 0) == 0


def test_summary_record_present():
    qa = validate_rtk_points(_POINTS_OK)
    assert any(r.category == "validation_complete" for r in qa.records)


def test_custom_thresholds():
    point = RTKPoint("MW-01", 4527893.12, 293847.55, 512.34,
                     hrms_ft=0.05, vrms_ft=0.04, fix_type="RTK_FIXED")
    qa = validate_rtk_points([point], hrms_threshold_ft=0.02, vrms_threshold_ft=0.02)
    cats = [r.category for r in qa.records]
    assert "hrms_exceeds_threshold" in cats


def test_validate_rtk_survey_in_help():
    from click.testing import CliRunner
    from autogis.adapters.cli import autogis
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "validate-rtk-survey" in result.output


def test_validate_rtk_survey_format_flag_and_guessed_order_in_report(tmp_path):
    from click.testing import CliRunner
    from autogis.adapters.cli import autogis

    csv_path = tmp_path / "headerless.csv"
    csv_path.write_text(
        "1,558281.5482,2206038.3110,3224.0823,PT-1\n"
        "2,558300.1200,2206050.4400,3225.1000,PT-2\n",
        encoding="utf-8",
    )
    report_path = tmp_path / "report.md"
    result = CliRunner().invoke(autogis, [
        "envmon", "validate-rtk-survey", str(csv_path),
        "--format", "auto", "--fail-on", "error",
        "--report", str(report_path),
    ])
    assert result.exit_code == 0, result.output
    assert "guessed_coord_order" in report_path.read_text(encoding="utf-8")
