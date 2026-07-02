"""Tests for draft_plume_boundary — CSV loaders, hull computation, serializers."""
from __future__ import annotations
import csv
import json
from pathlib import Path

import numpy as np
import pytest

from autogis.core.common.qa import QACollector
from autogis.core.envmon.draft_plume_boundary import (
    ExceedancePoint,
    DraftPlumeBoundaryResult,
    load_exceedance_points_csv,
    filter_results_to_exceedance_points,
    compute_draft_plume_boundary,
    result_to_geojson,
    result_to_wkt,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _points_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


_RESULT_FIELDS = [
    "ImportBatchID", "SiteID", "Matrix", "LocationID",
    "SampleID", "ParentSampleID", "SampleDate",
    "DepthTop_ft", "DepthBottom_ft", "DepthIntervalText",
    "AnalyticalGroup", "MethodGroup", "AnalyteName",
    "AnalyteCanonicalName", "AnalyteAbbreviation",
    "ResultRawText", "ResultNumeric", "ReportingLimit",
    "DetectionLimit", "Units", "Qualifier",
    "IsNonDetect", "IsDetected", "IsEstimated", "IsDiluted",
    "IsNotAnalyzed", "IsNotSampled", "IsNotMeasured",
    "ScreeningLevel", "ScreeningLevelSource",
    "ExceedsScreeningLevel", "DisplayText", "DisplayColorClass",
    "SourceWorkbook", "SourceSheet", "SourceRow",
    "SourceColumn", "SourceCell",
]


def _results_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=_RESULT_FIELDS, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            full = {f: "" for f in _RESULT_FIELDS}
            full.update(row)
            w.writerow(full)


def _coords_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["location_id", "x", "y"])
        w.writeheader()
        w.writerows(rows)


# ---------------------------------------------------------------------------
# load_exceedance_points_csv
# ---------------------------------------------------------------------------

def test_load_exceedance_points_csv_basic(tmp_path):
    p = tmp_path / "pts.csv"
    _points_csv(p, [
        {"location_id": "MW-01", "x": "100.0", "y": "200.0"},
        {"location_id": "MW-02", "x": "110.0", "y": "205.0"},
    ])
    pts = load_exceedance_points_csv(p)
    assert len(pts) == 2
    assert pts[0].location_id == "MW-01"
    assert abs(pts[0].x - 100.0) < 1e-9
    assert abs(pts[0].y - 200.0) < 1e-9


def test_load_exceedance_points_csv_optional_fields_default_none(tmp_path):
    p = tmp_path / "pts.csv"
    _points_csv(p, [{"location_id": "MW-01", "x": "1.0", "y": "2.0"}])
    pts = load_exceedance_points_csv(p)
    assert pts[0].analyte is None
    assert pts[0].event_date is None


def test_load_exceedance_points_csv_with_optional_fields(tmp_path):
    p = tmp_path / "pts.csv"
    _points_csv(p, [{"location_id": "MW-01", "x": "1.0", "y": "2.0",
                     "analyte": "Benzene", "event_date": "2025-04-01"}])
    pts = load_exceedance_points_csv(p)
    assert pts[0].analyte == "Benzene"
    assert pts[0].event_date == "2025-04-01"


# ---------------------------------------------------------------------------
# filter_results_to_exceedance_points
# ---------------------------------------------------------------------------

def test_filter_results_returns_exceedances_only(tmp_path):
    r = tmp_path / "r.csv"
    c = tmp_path / "c.csv"
    _results_csv(r, [
        {"LocationID": "MW-01", "ExceedsScreeningLevel": "1",
         "AnalyteCanonicalName": "Benzene"},
        {"LocationID": "MW-02", "ExceedsScreeningLevel": "0",
         "AnalyteCanonicalName": "Benzene"},
    ])
    _coords_csv(c, [
        {"location_id": "MW-01", "x": "1.0", "y": "2.0"},
        {"location_id": "MW-02", "x": "3.0", "y": "4.0"},
    ])
    pts = filter_results_to_exceedance_points(r, c, qa=QACollector())
    assert len(pts) == 1
    assert pts[0].location_id == "MW-01"


def test_filter_results_analyte_filter(tmp_path):
    r = tmp_path / "r.csv"
    c = tmp_path / "c.csv"
    _results_csv(r, [
        {"LocationID": "MW-01", "ExceedsScreeningLevel": "1",
         "AnalyteCanonicalName": "Benzene"},
        {"LocationID": "MW-02", "ExceedsScreeningLevel": "1",
         "AnalyteCanonicalName": "Toluene"},
    ])
    _coords_csv(c, [
        {"location_id": "MW-01", "x": "1.0", "y": "2.0"},
        {"location_id": "MW-02", "x": "3.0", "y": "4.0"},
    ])
    pts = filter_results_to_exceedance_points(
        r, c, analyte="Benzene", qa=QACollector())
    assert len(pts) == 1
    assert pts[0].location_id == "MW-01"
    assert pts[0].analyte == "Benzene"


def test_filter_results_missing_coords_warns_and_skips(tmp_path):
    r = tmp_path / "r.csv"
    c = tmp_path / "c.csv"
    _results_csv(r, [{"LocationID": "MW-NO-COORD", "ExceedsScreeningLevel": "1",
                      "AnalyteCanonicalName": "Benzene"}])
    _coords_csv(c, [])
    qa = QACollector()
    pts = filter_results_to_exceedance_points(r, c, qa=qa)
    assert len(pts) == 0
    warns = [rec for rec in qa.records if rec.severity == "WARNING"]
    assert any("MW-NO-COORD" in rec.message for rec in warns)


def test_filter_results_deduplicates_by_location(tmp_path):
    """Two analytes exceeding at the same well → one ExceedancePoint."""
    r = tmp_path / "r.csv"
    c = tmp_path / "c.csv"
    _results_csv(r, [
        {"LocationID": "MW-01", "ExceedsScreeningLevel": "1",
         "AnalyteCanonicalName": "Benzene"},
        {"LocationID": "MW-01", "ExceedsScreeningLevel": "1",
         "AnalyteCanonicalName": "Toluene"},
    ])
    _coords_csv(c, [{"location_id": "MW-01", "x": "1.0", "y": "2.0"}])
    pts = filter_results_to_exceedance_points(r, c, qa=QACollector())
    assert len(pts) == 1
    assert pts[0].location_id == "MW-01"


# ---------------------------------------------------------------------------
# Known point set: 5 wells forming a square + interior
# Convex hull = 4 corners; result should have 4 vertices (open ring)
# ---------------------------------------------------------------------------
_SQUARE_POINTS = [
    ExceedancePoint("MW-01", 0.0, 0.0),
    ExceedancePoint("MW-02", 1.0, 0.0),
    ExceedancePoint("MW-03", 1.0, 1.0),
    ExceedancePoint("MW-04", 0.0, 1.0),
    ExceedancePoint("MW-05", 0.5, 0.5),  # interior — excluded from convex hull
]


def test_compute_returns_result_object():
    qa = QACollector()
    r = compute_draft_plume_boundary(_SQUARE_POINTS, qa=qa)
    assert isinstance(r, DraftPlumeBoundaryResult)


def test_compute_review_status_always_draft():
    qa = QACollector()
    r = compute_draft_plume_boundary(_SQUARE_POINTS, qa=qa)
    assert r.review_status == "DRAFT"


def test_compute_draft_warning_present():
    qa = QACollector()
    r = compute_draft_plume_boundary(_SQUARE_POINTS, qa=qa)
    assert "DRAFT" in r.draft_warning.upper()


def test_compute_hull_vertices_open_ring():
    """hull_vertices must be open: first vertex != last vertex."""
    qa = QACollector()
    r = compute_draft_plume_boundary(_SQUARE_POINTS, qa=qa)
    verts = r.hull_vertices
    assert len(verts) >= 3
    assert verts[0] != verts[-1], "hull_vertices must be open (not closed)"


def test_compute_hull_vertices_at_least_3():
    qa = QACollector()
    r = compute_draft_plume_boundary(_SQUARE_POINTS, qa=qa)
    assert len(r.hull_vertices) >= 3


def test_compute_n_exceedance_points():
    qa = QACollector()
    r = compute_draft_plume_boundary(_SQUARE_POINTS, qa=qa)
    assert r.n_exceedance_points == len(_SQUARE_POINTS)


def test_compute_qa_emits_draft_info():
    """At least one QA INFO record must mention DRAFT."""
    qa = QACollector()
    compute_draft_plume_boundary(_SQUARE_POINTS, qa=qa)
    info_msgs = [rec.message for rec in qa.records if rec.severity == "INFO"]
    assert any("DRAFT" in m.upper() for m in info_msgs)


def test_compute_too_few_points_returns_none():
    qa = QACollector()
    r = compute_draft_plume_boundary(
        [ExceedancePoint("MW-01", 0.0, 0.0), ExceedancePoint("MW-02", 1.0, 0.0)],
        qa=qa)
    assert r is None
    errors = [rec for rec in qa.records if rec.severity == "ERROR"]
    assert errors, "expected a SEV_ERROR for < 3 points"


def test_compute_hull_method_convex_default():
    qa = QACollector()
    r = compute_draft_plume_boundary(_SQUARE_POINTS, qa=qa)
    assert r.hull_method == "convex"


def test_compute_hull_method_concave():
    qa = QACollector()
    r = compute_draft_plume_boundary(_SQUARE_POINTS, hull_method="concave",
                                     k_neighbors=3, qa=qa)
    assert r.hull_method == "concave"
    assert isinstance(r.hull_vertices, list)
    assert len(r.hull_vertices) >= 3


def test_compute_site_id_stored():
    qa = QACollector()
    r = compute_draft_plume_boundary(_SQUARE_POINTS, site_id="DEMO-01", qa=qa)
    assert r.site_id == "DEMO-01"


# ---------------------------------------------------------------------------
# result_to_geojson
# ---------------------------------------------------------------------------

def test_result_to_geojson_is_feature():
    qa = QACollector()
    r = compute_draft_plume_boundary(_SQUARE_POINTS, qa=qa)
    fc = result_to_geojson(r)
    assert fc["type"] == "Feature"
    assert fc["geometry"]["type"] == "Polygon"


def test_result_to_geojson_review_status_draft():
    qa = QACollector()
    r = compute_draft_plume_boundary(_SQUARE_POINTS, qa=qa)
    fc = result_to_geojson(r)
    assert fc["properties"]["review_status"] == "DRAFT"


def test_result_to_geojson_draft_warning_property():
    qa = QACollector()
    r = compute_draft_plume_boundary(_SQUARE_POINTS, qa=qa)
    fc = result_to_geojson(r)
    assert "draft_warning" in fc["properties"]
    assert "DRAFT" in fc["properties"]["draft_warning"].upper()


def test_result_to_geojson_ring_is_closed():
    """GeoJSON Polygon ring must have first == last coordinate."""
    qa = QACollector()
    r = compute_draft_plume_boundary(_SQUARE_POINTS, qa=qa)
    fc = result_to_geojson(r)
    ring = fc["geometry"]["coordinates"][0]
    assert ring[0] == ring[-1], "GeoJSON ring must be closed (first == last)"


def test_result_to_geojson_ring_min_4_coords():
    """Minimum valid GeoJSON polygon ring: 4 coords (3 unique + closing)."""
    qa = QACollector()
    r = compute_draft_plume_boundary(_SQUARE_POINTS, qa=qa)
    fc = result_to_geojson(r)
    ring = fc["geometry"]["coordinates"][0]
    assert len(ring) >= 4


def test_result_to_geojson_is_json_serialisable():
    qa = QACollector()
    r = compute_draft_plume_boundary(_SQUARE_POINTS, qa=qa)
    fc = result_to_geojson(r)
    blob = json.dumps(fc)  # must not raise
    assert "DRAFT" in blob


# ---------------------------------------------------------------------------
# result_to_wkt
# ---------------------------------------------------------------------------

def test_result_to_wkt_starts_with_polygon():
    qa = QACollector()
    r = compute_draft_plume_boundary(_SQUARE_POINTS, qa=qa)
    wkt = result_to_wkt(r)
    assert wkt.startswith("POLYGON")


def test_result_to_wkt_ring_closed():
    """WKT ring must close: first and last coordinate pair are identical."""
    qa = QACollector()
    r = compute_draft_plume_boundary(_SQUARE_POINTS, qa=qa)
    wkt = result_to_wkt(r)
    # Extract coordinates between the outer parentheses
    inner = wkt.split("((")[1].rstrip("))")
    pairs = [pair.strip().split() for pair in inner.split(",")]
    assert pairs[0] == pairs[-1], "WKT ring must be closed"
