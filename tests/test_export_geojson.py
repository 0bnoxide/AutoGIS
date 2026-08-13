"""Tests for export_geojson module."""
import dataclasses
from datetime import date

import pytest

from autogis.core.common.qa import QACollector
from autogis.core.envmon.export_geojson import build_geojson, load_well_coords
from autogis.core.envmon.gdb_schema import AnalyticalResultRecord


def _r(loc, analyte, num, dt, exceed=None):
    return AnalyticalResultRecord(
        ImportBatchID="B", SiteID="S", Matrix="GW",
        LocationID=loc, SampleID="S1", ParentSampleID="",
        SampleDate=dt, DepthTop_ft=None, DepthBottom_ft=None,
        DepthIntervalText="", AnalyticalGroup="VOC", MethodGroup="EPA8260",
        AnalyteName=analyte, AnalyteCanonicalName=analyte,
        AnalyteAbbreviation=analyte[:3], ResultRawText=str(num),
        ResultNumeric=num, ReportingLimit=None, DetectionLimit=None,
        Units="ug/L", Qualifier="", IsNonDetect=0, IsDetected=1,
        IsEstimated=0, IsDiluted=0, IsNotAnalyzed=0, IsNotSampled=0,
        IsNotMeasured=0, ScreeningLevel=None, ScreeningLevelSource="",
        ExceedsScreeningLevel=exceed, DisplayText=str(num), DisplayColorClass="",
        SourceWorkbook="t.xlsx", SourceSheet="S1",
        SourceRow=1, SourceColumn="A", SourceCell="A1",
    )


COORDS = {"MW-1": (100.0, 200.0), "MW-2": (110.0, 205.0)}


def test_basic_feature_count():
    results = [_r("MW-1", "Benzene", 5.0, date(2026, 4, 1))]
    qa = QACollector()
    fc = build_geojson(results, COORDS, qa=qa)
    assert fc["type"] == "FeatureCollection"
    assert len(fc["features"]) == 1


def test_missing_coords_skipped():
    results = [_r("MW-99", "Benzene", 5.0, date(2026, 4, 1))]
    qa = QACollector()
    fc = build_geojson(results, COORDS, qa=qa)
    assert len(fc["features"]) == 0
    assert any(r.category == "missing_coords" for r in qa.records)


def test_properties_contain_analyte():
    results = [_r("MW-1", "Benzene", 5.0, date(2026, 4, 1))]
    qa = QACollector()
    fc = build_geojson(results, COORDS, qa=qa)
    props = fc["features"][0]["properties"]
    assert "Benzene_value" in props
    assert props["Benzene_value"] == "5.0"


def test_geometry_coordinates():
    results = [_r("MW-1", "Benzene", 5.0, date(2026, 4, 1))]
    qa = QACollector()
    fc = build_geojson(results, COORDS, qa=qa)
    geom = fc["features"][0]["geometry"]
    assert geom["type"] == "Point"
    assert geom["coordinates"] == [100.0, 200.0]


def test_multi_location_multi_analyte():
    results = [
        _r("MW-1", "Benzene", 5.0, date(2026, 4, 1)),
        _r("MW-1", "Toluene", 2.5, date(2026, 4, 1)),
        _r("MW-2", "Benzene", 1.0, date(2026, 4, 1)),
    ]
    qa = QACollector()
    fc = build_geojson(results, COORDS, qa=qa)
    assert len(fc["features"]) == 2
    mw1_props = next(
        f["properties"] for f in fc["features"]
        if f["properties"]["location_id"] == "MW-1"
    )
    assert "Benzene_value" in mw1_props
    assert "Toluene_value" in mw1_props


def test_load_well_coords(tmp_path):
    csv_path = tmp_path / "coords.csv"
    csv_path.write_text("location_id,x,y\nMW-1,100.0,200.0\nMW-2,110.0,205.0\n",
                        encoding="utf-8")
    coords = load_well_coords(csv_path)
    assert coords["MW-1"] == (100.0, 200.0)
    assert coords["MW-2"] == (110.0, 205.0)


def test_is_not_analyzed_excluded():
    """Records with IsNotAnalyzed=1 must be excluded from output."""
    rec = dataclasses.replace(
        _r("MW-1", "Benzene", 5.0, date(2026, 4, 1)), IsNotAnalyzed=1)
    qa = QACollector()
    fc = build_geojson([rec], COORDS, qa=qa)
    assert len(fc["features"]) == 0


def test_analyte_key_collision_warns():
    """Two analytes sanitizing to the same property key emit a QA warning."""
    results = [
        _r("MW-1", "Xylenes, total", 5.0, date(2026, 4, 1)),
        _r("MW-1", "Xylenes total", 6.0, date(2026, 4, 1)),
    ]
    qa = QACollector()
    fc = build_geojson(results, COORDS, qa=qa)
    assert any(r.category == "analyte_key_collision" for r in qa.records)
    # Only one collapsed key survives in properties.
    props = fc["features"][0]["properties"]
    assert "Xylenes_total_value" in props


def test_qa_info_emitted():
    results = [_r("MW-1", "Benzene", 5.0, date(2026, 4, 1))]
    qa = QACollector()
    build_geojson(results, COORDS, qa=qa)
    assert any(r.category == "export_geojson_complete" for r in qa.records)
