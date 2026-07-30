"""Headless tests for gw_model_pipeline (Phase-5 slice 1, ADR-0085)."""
import csv
import datetime as dt

import pytest

from autogis.core.common.qa import QACollector
from autogis.core.envmon.gw_model_pipeline import (
    approve_gw_model,
    build_gw_model_review_records,
    build_run_records,
    cross_validate_and_rank,
    loo_observation_rows,
    make_run_id,
    write_observations_csv,
)

NOW = dt.datetime(2026, 7, 16, 12, 0, 0)

# 5 wells on a simple sloping surface z = x/10.
POINTS = [
    ("MW-1", 0.0, 0.0, 100.0),
    ("MW-2", 100.0, 0.0, 110.0),
    ("MW-3", 0.0, 100.0, 100.0),
    ("MW-4", 100.0, 100.0, 110.0),
    ("MW-5", 50.0, 50.0, 105.0),
]


def mean_predictor(method, rest, held):
    """Fake LOO predictor: mean GWE of the remaining points."""
    return sum(p[3] for p in rest) / len(rest)


def test_make_run_id_deterministic():
    assert make_run_id("H281", "2026-06-15", NOW) == \
        "GWM_H281_2026-06-15_20260716120000"


def test_loo_observation_rows_shape():
    qa = QACollector()
    rows = loo_observation_rows(POINTS, ["TIN", "IDW"], mean_predictor, qa)
    assert [r.well_id for r in rows] == [p[0] for p in POINTS]
    assert rows[0].observed_ft == 100.0
    # every fold got a prediction for both methods
    assert all(set(r.predictions) == {"TIN", "IDW"} for r in rows)
    # LOO: prediction excludes the held-out point
    assert rows[0].predictions["TIN"] == pytest.approx(
        (110.0 + 100.0 + 110.0 + 105.0) / 4)


def test_loo_none_prediction_is_skipped_cell():
    """None from the predictor (outside TIN hull / NoData) = missing key."""
    qa = QACollector()

    def spotty(method, rest, held):
        if method == "TIN" and held[0] == "MW-5":
            return None
        return mean_predictor(method, rest, held)

    rows = loo_observation_rows(POINTS, ["TIN", "IDW"], spotty, qa)
    mw5 = next(r for r in rows if r.well_id == "MW-5")
    assert "TIN" not in mw5.predictions and "IDW" in mw5.predictions


def test_loo_requires_four_points():
    qa = QACollector()
    rows = loo_observation_rows(POINTS[:3], ["TIN"], mean_predictor, qa)
    assert rows == []
    assert any(r.category == "insufficient_cv_points" for r in qa.records)


def test_loo_rejects_unknown_method():
    with pytest.raises(ValueError, match="Kriging"):
        loo_observation_rows(POINTS, ["Kriging"], mean_predictor,
                             QACollector())


def test_build_run_records_draft_and_unapproved():
    qa = QACollector()
    rows, stats, run_row, cv_rows = cross_validate_and_rank(
        POINTS, ["TIN", "IDW"], mean_predictor, qa,
        site_id="H281", event_date="2026-06-15", now=NOW)
    assert run_row["ReviewStatus"] == "DRAFT"
    assert run_row["ApprovedModel"] == ""
    assert run_row["Methods"] == "TIN,IDW"
    assert run_row["ExecutedMethods"] == "TIN,IDW"
    assert run_row["RunID"] == "GWM_H281_2026-06-15_20260716120000"
    assert "Rank-1 suggestion" in run_row["Notes"]
    assert len(stats) == 2 and len(cv_rows) == 2
    ranks = sorted(r["Rank"] for r in cv_rows)
    assert ranks == [1, 2]
    for r in cv_rows:
        assert r["RunID"] == run_row["RunID"]
        assert set(r) == {"RunID", "ModelName", "NPoints", "RMSE",
                          "MeanError", "MAE", "PctWithinTolerance", "Rank"}


def test_requested_methods_survive_license_skip():
    """GW_ModelRun.Methods records what was REQUESTED (ADR-0085 decision 2);
    ExecutedMethods records what actually ran — the approval universe
    (PR #240 review)."""
    qa = QACollector()
    _rows, stats, run_row, _cv = cross_validate_and_rank(
        POINTS, ["IDW"], mean_predictor, qa,
        site_id="H281", event_date="2026-06-15", now=NOW,
        requested_methods=["TIN", "IDW"])
    assert run_row["Methods"] == "TIN,IDW"
    assert run_row["ExecutedMethods"] == "IDW"
    assert [s.model_name for s in stats] == ["IDW"]


def test_executed_methods_recorded_without_cv():
    """A 3-point run produces contours but no CV rows — ExecutedMethods must
    still record the generated models so approval stays possible."""
    run_row, cv_rows = build_run_records(
        "GWM_X_2026-01-01_20260101000000", "X", "2026-01-01",
        ["TIN", "IDW"], [], NOW, executed_methods=["TIN", "IDW"])
    assert cv_rows == []
    assert run_row["ExecutedMethods"] == "TIN,IDW"


def test_run_records_without_cv():
    """<4 points: no ranking, run row still shaped, note says why."""
    run_row, cv_rows = build_run_records(
        "GWM_X_2026-01-01_20260101000000", "X", "2026-01-01", ["TIN"], [], NOW)
    assert cv_rows == []
    assert run_row["ReviewStatus"] == "DRAFT"
    assert "insufficient points" in run_row["Notes"]


def test_review_records_join_ranked_stats_and_keep_unranked_methods():
    runs = [{
        "RunID": "GWM_X", "SiteID": "X",
        "EventDate": dt.datetime(2026, 7, 1),
        "Methods": "TIN,IDW,EBK", "ExecutedMethods": "TIN,IDW,EBK",
        "RunTimestamp": NOW, "ApprovedModel": "", "ReviewStatus": "DRAFT",
        "Notes": "",
    }]
    cv = [
        {"RunID": "GWM_X", "ModelName": "IDW", "Rank": 2, "RMSE": 0.14},
        {"RunID": "GWM_X", "ModelName": "TIN", "Rank": 1, "RMSE": 0.02},
    ]
    records = build_gw_model_review_records(runs, cv)
    assert records[0]["EventDate"] == "2026-07-01"
    assert records[0]["ExecutedMethods"] == ["TIN", "IDW", "EBK"]
    assert [m["ModelName"] for m in records[0]["Models"]] == ["TIN", "IDW"]
    assert "EBK" in records[0]["ExecutedMethods"]  # approvable without CV


def test_approve_requires_reviewer_before_arcpy_import():
    with pytest.raises(ValueError, match="reviewer"):
        approve_gw_model("fake.gdb", "GWM_X", "TIN", reviewer="  ")


def test_write_observations_csv_round_trips(tmp_path):
    """Audit CSV must be readable by evaluate-gw-models' own reader."""
    from autogis.core.envmon.evaluate_gw_models import read_gw_model_csv
    qa = QACollector()
    rows = loo_observation_rows(POINTS, ["TIN", "IDW"], mean_predictor, qa)
    out = tmp_path / "obs.csv"
    write_observations_csv(rows, out)
    with open(out, newline="", encoding="utf-8") as fh:
        header = next(csv.reader(fh))
    assert header == ["well_id", "observed_ft", "TIN", "IDW"]
    back = read_gw_model_csv(out)
    assert [r.well_id for r in back] == [p[0] for p in POINTS]
    assert back[0].predictions["TIN"] == pytest.approx(
        rows[0].predictions["TIN"])


def test_write_observations_csv_blank_for_missing(tmp_path):
    from autogis.core.envmon.evaluate_gw_models import read_gw_model_csv
    qa = QACollector()

    def spotty(method, rest, held):
        if method == "TIN" and held[0] == "MW-5":
            return None
        return mean_predictor(method, rest, held)

    rows = loo_observation_rows(POINTS, ["TIN", "IDW"], spotty, qa)
    out = tmp_path / "obs.csv"
    write_observations_csv(rows, out)
    back = read_gw_model_csv(out)
    mw5 = next(r for r in back if r.well_id == "MW-5")
    assert "TIN" not in mw5.predictions


def test_pipeline_core_ranks_better_model_first():
    """A predictor that nails one method must rank it #1."""
    qa = QACollector()

    def biased(method, rest, held):
        if method == "TIN":
            return held[3]  # perfect
        return held[3] + 2.0  # 2 ft biased

    _rows, stats, _run, cv_rows = cross_validate_and_rank(
        POINTS, ["TIN", "IDW"], biased, qa,
        site_id="H281", event_date="2026-06-15", now=NOW)
    assert stats[0].model_name == "TIN" and stats[0].rank == 1
    idw = next(r for r in cv_rows if r["ModelName"] == "IDW")
    assert idw["RMSE"] == pytest.approx(2.0)
    assert idw["MeanError"] == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# CLI smoke tests (guard-then-redirect pattern; no arcpy in this suite)
# ---------------------------------------------------------------------------
from click.testing import CliRunner  # noqa: E402
from autogis.adapters.cli import autogis  # noqa: E402


def test_pipeline_and_approve_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert result.exit_code == 0
    assert "run-gw-model-pipeline" in result.output
    assert "approve-gw-model" in result.output


def test_run_gw_model_pipeline_guard_without_arcpy(tmp_path):
    cfg = tmp_path / "site.yaml"
    cfg.write_text("site_id: X\n", encoding="utf-8")
    result = CliRunner().invoke(
        autogis, ["envmon", "run-gw-model-pipeline", str(cfg)])
    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_approve_gw_model_guard_without_arcpy():
    result = CliRunner().invoke(autogis, [
        "envmon", "approve-gw-model", "--gdb", "fake.gdb",
        "--run-id", "GWM_X", "--model", "TIN", "--reviewer", "QA"])
    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_approve_gw_model_cli_requires_reviewer():
    result = CliRunner().invoke(autogis, [
        "envmon", "approve-gw-model", "--gdb", "fake.gdb",
        "--run-id", "GWM_X", "--model", "TIN"])
    assert result.exit_code == 2
    assert "Missing option '--reviewer'" in result.output


# ---------------------------------------------------------------------------
# Slice-2: EBK cross-validation merge (spec D2)
# ---------------------------------------------------------------------------
from autogis.core.envmon.gw_model_pipeline import (  # noqa: E402
    PIPELINE_METHODS, merge_method_predictions,
)


def test_ebk_in_pipeline_methods():
    assert PIPELINE_METHODS == ("TIN", "IDW", "EBK")


def test_merge_method_predictions_joins_by_well():
    qa = QACollector()
    rows = loo_observation_rows(POINTS, ["TIN"], mean_predictor, qa)
    ebk = {p[0]: p[3] + 0.1 for p in POINTS}
    del ebk["MW-5"]  # CV excluded one well -> skipped cell
    matched = merge_method_predictions(rows, "EBK", ebk, qa)
    assert matched == 4
    mw1 = next(r for r in rows if r.well_id == "MW-1")
    assert mw1.predictions["EBK"] == pytest.approx(100.1)
    mw5 = next(r for r in rows if r.well_id == "MW-5")
    assert "EBK" not in mw5.predictions and "TIN" in mw5.predictions


def test_merge_no_matches_warns():
    qa = QACollector()
    rows = loo_observation_rows(POINTS, ["TIN"], mean_predictor, qa)
    assert merge_method_predictions(rows, "EBK", {}, qa) == 0
    assert any(r.category == "cv_merge_no_matches" for r in qa.records)


def test_merge_rejects_unknown_method():
    with pytest.raises(ValueError, match="Kriging"):
        merge_method_predictions([], "Kriging", {}, QACollector())


def test_cross_validate_ebk_only_via_extra_predictions():
    """EBK-only run: no manual LOO methods, ranking entirely from the
    externally supplied CV predictions (arcpy.ga.CrossValidation seam)."""
    qa = QACollector()
    ebk = {p[0]: p[3] for p in POINTS}  # perfect predictions
    rows, stats, run_row, cv_rows = cross_validate_and_rank(
        POINTS, ["EBK"], lambda *_: None, qa,
        site_id="H281", event_date="2026-06-15", now=NOW,
        loo_methods=[], extra_predictions={"EBK": ebk})
    assert [s.model_name for s in stats] == ["EBK"]
    assert stats[0].rmse == pytest.approx(0.0)
    assert run_row["ExecutedMethods"] == "EBK"
    assert len(cv_rows) == 1 and cv_rows[0]["Rank"] == 1


def test_cross_validate_mixed_manual_and_ebk_ranks_together():
    """TIN (manual, biased) vs EBK (external, perfect) rank on the same
    wells; EBK must take rank 1."""
    qa = QACollector()

    def biased(method, rest, held):
        return held[3] + 2.0

    ebk = {p[0]: p[3] for p in POINTS}
    _rows, stats, run_row, _cv = cross_validate_and_rank(
        POINTS, ["TIN", "EBK"], biased, qa,
        site_id="H281", event_date="2026-06-15", now=NOW,
        loo_methods=["TIN"], extra_predictions={"EBK": ebk})
    assert stats[0].model_name == "EBK" and stats[0].rank == 1
    assert stats[0].n_points == stats[1].n_points == len(POINTS)
    assert run_row["ExecutedMethods"] == "TIN,EBK"


def test_default_methods_exclude_ebk():
    """#241 P2 regression: EBK is in the validation universe but must not
    run by default — a bare programmatic call stays TIN,IDW."""
    import inspect
    from autogis.core.envmon.gw_model_pipeline import (
        DEFAULT_PIPELINE_METHODS, run_field_to_groundwater_model_pipeline,
    )
    assert DEFAULT_PIPELINE_METHODS == ("TIN", "IDW")
    assert "EBK" not in DEFAULT_PIPELINE_METHODS
    sig = inspect.signature(run_field_to_groundwater_model_pipeline)
    assert sig.parameters["methods"].default == DEFAULT_PIPELINE_METHODS
