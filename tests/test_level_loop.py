"""Unit tests for process_level_loop (Tool 8.1)."""
import math
from datetime import date

from autogis.core.common.qa import QACollector
from autogis.core.common.schema.survey import LevelLoopObservation, LevelLoopRun
from autogis.core.envmon.level_loop import process_level_loop


def _obs(setup, point, bs=None, fs=None, is_=None):
    return LevelLoopObservation(run_id="L1", setup_id=str(setup), point_id=point,
                                backsight=bs, foresight=fs, intermediate_sight=is_)


def test_perfect_closing_loop_zero_misclosure():
    # BM100.000; setup1 BS on BM, FS to TP1; setup2 BS on TP1, FS back to BM.
    obs = [
        _obs(1, "BM", bs=2.000),          # HI = 102.000
        _obs(1, "TP1", fs=3.000),         # TP1 = 99.000
        _obs(2, "TP1", bs=4.000),         # HI = 103.000
        _obs(2, "BM", fs=3.000),          # closing -> 100.000, misclosure 0
    ]
    qa = QACollector()
    run, rows = process_level_loop(
        obs, run_id="L1", site_id="S", survey_date=date(2026, 4, 1),
        benchmark_id="BM", known_elevation=100.000, tolerance=0.05, qa=qa)
    assert isinstance(run, LevelLoopRun)
    assert run.misclosure_ft == 0.0
    tp1 = next(r for r in rows if r.point_id == "TP1" and r.backsight is None)
    assert tp1.elevation == 99.000
    assert run.adjusted in (False, True)
    assert not any(r.severity == "ERROR" for r in qa.records)


def test_misclosure_exceeds_tolerance_errors():
    obs = [
        _obs(1, "BM", bs=2.000),
        _obs(1, "TP1", fs=3.000),
        _obs(2, "TP1", bs=4.000),
        _obs(2, "BM", fs=2.900),          # closes at 100.100 -> misclosure +0.100
    ]
    qa = QACollector()
    run, rows = process_level_loop(
        obs, run_id="L1", site_id="S", survey_date=date(2026, 4, 1),
        benchmark_id="BM", known_elevation=100.000, tolerance=0.05, qa=qa)
    assert round(run.misclosure_ft, 3) == 0.100
    assert any(r.category == "misclosure_exceeds_tolerance"
               and r.severity == "ERROR" for r in qa.records)


def test_default_tolerance_is_sqrt_rule():
    obs = [
        _obs(1, "BM", bs=2.0), _obs(1, "TP1", fs=3.0),
        _obs(2, "TP1", bs=4.0), _obs(2, "BM", fs=3.0),
    ]
    qa = QACollector()
    run, _ = process_level_loop(
        obs, run_id="L1", site_id="S", survey_date=date(2026, 4, 1),
        benchmark_id="BM", known_elevation=100.0, tolerance=None, qa=qa)
    assert run.closure_tolerance_ft == pytest_approx_or_exact(0.05 * math.sqrt(2))
    assert any(r.category == "closure_tolerance_default" for r in qa.records)


def pytest_approx_or_exact(v):
    import pytest
    return pytest.approx(v, rel=1e-9)


def test_negative_reading_errors():
    obs = [_obs(1, "BM", bs=-2.0), _obs(1, "BM", fs=2.0)]
    qa = QACollector()
    process_level_loop(obs, run_id="L1", site_id="S",
                       survey_date=date(2026, 4, 1), benchmark_id="BM",
                       known_elevation=100.0, tolerance=0.05, qa=qa)
    assert any(r.category == "negative_reading" for r in qa.records)


def test_unclosed_loop_warns():
    # never returns a foresight onto BM
    obs = [_obs(1, "BM", bs=2.0), _obs(1, "TP1", fs=3.0)]
    qa = QACollector()
    run, _ = process_level_loop(
        obs, run_id="L1", site_id="S", survey_date=date(2026, 4, 1),
        benchmark_id="BM", known_elevation=100.0, tolerance=0.05, qa=qa)
    assert any(r.category in ("unclosed_loop", "benchmark_mismatch")
               for r in qa.records)


def test_adjustment_distributes_equally_per_setup():
    # +0.100 misclosure over 2 setups -> -0.050 per setup cumulative
    obs = [
        _obs(1, "BM", bs=2.000),
        _obs(1, "TP1", fs=3.000),         # raw 99.000 -> adj -0.050 -> 98.950
        _obs(2, "TP1", bs=4.000),
        _obs(2, "BM", fs=2.900),
    ]
    qa = QACollector()
    run, rows = process_level_loop(
        obs, run_id="L1", site_id="S", survey_date=date(2026, 4, 1),
        benchmark_id="BM", known_elevation=100.0, tolerance=0.5, qa=qa)
    assert run.adjusted is True
    tp1 = next(r for r in rows if r.point_id == "TP1" and r.foresight is not None)
    assert round(tp1.elevation, 3) == 98.950


def test_intermediate_sight_does_not_advance_hi():
    obs = [
        _obs(1, "BM", bs=2.000),    # HI = 102.000
        _obs(1, "IS1", is_=1.500),  # side-shot: elev = 100.500, HI unchanged
        _obs(1, "TP1", fs=3.000),   # TP1 = 99.000
        _obs(2, "TP1", bs=4.000),   # HI = 103.000
        _obs(2, "BM", fs=3.000),    # closing -> 100.000
    ]
    qa = QACollector()
    run, rows = process_level_loop(
        obs, run_id="L1", site_id="S", survey_date=date(2026, 4, 1),
        benchmark_id="BM", known_elevation=100.0, tolerance=0.05, qa=qa)
    is1 = next(r for r in rows if r.point_id == "IS1")
    assert abs(is1.elevation - 100.500) < 1e-9
    assert run.misclosure_ft == 0.0


def test_duplicate_turning_point_warns():
    obs = [
        _obs(1, "BM", bs=2.0),
        _obs(1, "TP1", fs=3.0),
        _obs(2, "TP1", bs=4.0),
        _obs(2, "TP1", fs=2.5),   # TP1 used twice as turning point
        _obs(3, "TP1", bs=3.0),
        _obs(3, "BM", fs=3.0),
    ]
    qa = QACollector()
    process_level_loop(
        obs, run_id="L1", site_id="S", survey_date=date(2026, 4, 1),
        benchmark_id="BM", known_elevation=100.0, tolerance=0.5, qa=qa)
    assert any(r.category == "duplicate_turning_point" for r in qa.records)
