"""Tests for groundwater interpolation model cross-validation."""
import pytest

from autogis.core.common.qa import QACollector
from autogis.core.envmon.evaluate_gw_models import (
    ObservationRow,
    evaluate_gw_models,
    read_gw_model_csv,
    write_model_stats_csv,
)


def test_best_model_ranked_first():
    qa = QACollector()
    observations = [
        ObservationRow("MW-1", 100.0, {"TIN": 100.1, "IDW": 101.0}),
        ObservationRow("MW-2", 105.0, {"TIN": 104.9, "IDW": 107.0}),
    ]
    stats = evaluate_gw_models(observations, qa=qa)
    assert stats[0].model_name == "TIN"
    assert stats[0].rank == 1
    assert stats[1].model_name == "IDW"
    assert stats[1].rank == 2


def test_rmse_computation():
    """Errors of +1.0 and -1.0 -> RMSE = 1.0."""
    qa = QACollector()
    observations = [
        ObservationRow("MW-1", 100.0, {"TIN": 101.0}),
        ObservationRow("MW-2", 100.0, {"TIN": 99.0}),
    ]
    stats = evaluate_gw_models(observations, qa=qa)
    assert abs(stats[0].rmse - 1.0) < 1e-9
    # signed bias should cancel out
    assert abs(stats[0].mean_error - 0.0) < 1e-9
    assert abs(stats[0].mae - 1.0) < 1e-9


def test_pct_within_tolerance():
    qa = QACollector()
    observations = [
        ObservationRow("MW-1", 100.0, {"TIN": 100.1}),   # within 0.5
        ObservationRow("MW-2", 100.0, {"TIN": 101.0}),   # outside 0.5
    ]
    stats = evaluate_gw_models(observations, tolerance_ft=0.5, qa=qa)
    assert stats[0].pct_within_tolerance == 50.0


def test_missing_prediction_skipped_not_errored():
    """A well with no prediction for a model is excluded from that model's stats."""
    qa = QACollector()
    observations = [
        ObservationRow("MW-1", 100.0, {"TIN": 100.0, "IDW": 100.0}),
        ObservationRow("MW-2", 100.0, {"TIN": 100.0}),   # no IDW value
    ]
    stats = evaluate_gw_models(observations, qa=qa)
    idw = next(s for s in stats if s.model_name == "IDW")
    assert idw.n_points == 1


def test_empty_observations():
    qa = QACollector()
    stats = evaluate_gw_models([], qa=qa)
    assert stats == []
    assert any(r.category == "no_observations" for r in qa.records)


def test_no_model_columns():
    qa = QACollector()
    stats = evaluate_gw_models([ObservationRow("MW-1", 100.0, {})], qa=qa)
    assert stats == []
    assert any(r.category == "no_model_predictions" for r in qa.records)


def test_read_gw_model_csv(tmp_path):
    csv_path = tmp_path / "obs.csv"
    csv_path.write_text(
        "well_id,observed_ft,TIN,IDW\n"
        "MW-1,100.0,100.1,\n"
        "MW-2,105.0,104.9,106.0\n",
        encoding="utf-8",
    )
    rows = read_gw_model_csv(csv_path)
    assert len(rows) == 2
    assert rows[0].predictions == {"TIN": 100.1}
    assert rows[1].predictions == {"TIN": 104.9, "IDW": 106.0}


def test_read_gw_model_csv_malformed_row_reports_line_number(tmp_path):
    csv_path = tmp_path / "obs.csv"
    csv_path.write_text(
        "well_id,observed_ft,TIN\n"
        "MW-1,100.0,100.1\n"
        "MW-2,not_a_number,104.9\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="line 3"):
        read_gw_model_csv(csv_path)


def test_read_gw_model_csv_header_only(tmp_path):
    csv_path = tmp_path / "obs.csv"
    csv_path.write_text("well_id,observed_ft,TIN\n", encoding="utf-8")
    assert read_gw_model_csv(csv_path) == []


def test_duplicate_well_id_double_counted_in_rmse():
    """No natural-key constraint: duplicate well_id rows both contribute to
    that model's stats (documented behavior, not silently deduplicated)."""
    qa = QACollector()
    observations = [
        ObservationRow("MW-1", 100.0, {"TIN": 100.0}),
        ObservationRow("MW-1", 100.0, {"TIN": 102.0}),
    ]
    stats = evaluate_gw_models(observations, qa=qa)
    assert stats[0].n_points == 2


def test_write_model_stats_csv(tmp_path):
    qa = QACollector()
    stats = evaluate_gw_models(
        [ObservationRow("MW-1", 100.0, {"TIN": 100.1})], qa=qa)
    out = tmp_path / "stats.csv"
    write_model_stats_csv(stats, out)
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "TIN" in text
    assert "rank" in text
