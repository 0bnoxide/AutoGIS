"""Arcpy-free tests for import_drone_products.py."""
from autogis.core.common.qa import QACollector, SEV_ERROR, SEV_WARNING, SEV_INFO
from autogis.core.envmon.import_drone_products import (
    parse_product_manifest,
    validate_drone_products,
    classify_records,
    parse_gcp_csv,
    VALID_PRODUCT_TYPES,
    RASTER_PRODUCT_TYPES,
)

_MANIFEST_CSV = """\
product_type,path,crs,vertical_datum,resolution_m
orthomosaic,/data/ortho.tif,EPSG:32612,NAVD88,0.05
DSM,/data/dsm.tif,EPSG:32612,NAVD88,0.05
DEM,/data/dem.tif,EPSG:32612,NAVD88,0.10
point_cloud,/data/cloud.las,EPSG:32612,NAVD88,
"""

_GCP_CSV = """\
point_id,northing,easting,elevation,point_type,residual_h,residual_v
GCP-01,4527893.12,293847.55,512.34,GCP,0.02,0.03
GCP-02,4527750.00,293900.00,509.12,GCP,,
"""


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


# ---- parse_product_manifest -------------------------------------------------

def test_parse_manifest_count(tmp_path):
    records = parse_product_manifest(_write(tmp_path, "m.csv", _MANIFEST_CSV), "FLT-001")
    assert len(records) == 4


def test_parse_manifest_flight_id_stamped(tmp_path):
    records = parse_product_manifest(_write(tmp_path, "m.csv", _MANIFEST_CSV), "FLT-001")
    assert all(r.flight_id == "FLT-001" for r in records)


def test_parse_manifest_product_ids_unique(tmp_path):
    records = parse_product_manifest(_write(tmp_path, "m.csv", _MANIFEST_CSV), "FLT-001")
    ids = [r.product_id for r in records]
    assert len(set(ids)) == 4


def test_parse_manifest_qa_status_pending(tmp_path):
    records = parse_product_manifest(_write(tmp_path, "m.csv", _MANIFEST_CSV), "FLT-001")
    assert all(r.qa_status == "pending" for r in records)


def test_parse_manifest_resolution_none_for_point_cloud(tmp_path):
    records = parse_product_manifest(_write(tmp_path, "m.csv", _MANIFEST_CSV), "FLT-001")
    pc = next(r for r in records if r.product_type == "point_cloud")
    assert pc.resolution_m is None


def test_parse_manifest_resolution_float_for_raster(tmp_path):
    records = parse_product_manifest(_write(tmp_path, "m.csv", _MANIFEST_CSV), "FLT-001")
    ortho = next(r for r in records if r.product_type == "orthomosaic")
    assert abs(ortho.resolution_m - 0.05) < 1e-9


def test_parse_manifest_product_types_preserved(tmp_path):
    records = parse_product_manifest(_write(tmp_path, "m.csv", _MANIFEST_CSV), "FLT-001")
    assert {r.product_type for r in records} == {"orthomosaic", "DSM", "DEM", "point_cloud"}


def test_parse_manifest_empty_file_returns_empty(tmp_path):
    p = _write(tmp_path, "empty.csv", "product_type,path,crs,vertical_datum,resolution_m\n")
    assert parse_product_manifest(p, "FLT-002") == []


# ---- validate_drone_products ------------------------------------------------

def test_validate_valid_records_no_errors(tmp_path):
    records = parse_product_manifest(_write(tmp_path, "m.csv", _MANIFEST_CSV), "FLT-001")
    qa = QACollector()
    validate_drone_products(records, qa)
    assert [r.category for r in qa.records if r.severity == SEV_ERROR] == []


def test_validate_invalid_product_type(tmp_path):
    content = "product_type,path,crs,vertical_datum,resolution_m\nbadtype,/data/x.tif,EPSG:4326,,\n"
    records = parse_product_manifest(_write(tmp_path, "bad.csv", content), "FLT-002")
    qa = QACollector()
    validate_drone_products(records, qa)
    assert "invalid_product_type" in [r.category for r in qa.records]


def test_validate_duplicate_product_type(tmp_path):
    content = (
        "product_type,path,crs,vertical_datum,resolution_m\n"
        "orthomosaic,/data/a.tif,EPSG:4326,,\n"
        "orthomosaic,/data/b.tif,EPSG:4326,,\n"
    )
    records = parse_product_manifest(_write(tmp_path, "dup.csv", content), "FLT-003")
    qa = QACollector()
    validate_drone_products(records, qa)
    assert "duplicate_product_type" in [r.category for r in qa.records]


def test_validate_empty_path_is_error(tmp_path):
    content = "product_type,path,crs,vertical_datum,resolution_m\northomosaic,,EPSG:4326,,\n"
    records = parse_product_manifest(_write(tmp_path, "nopath.csv", content), "FLT-004")
    qa = QACollector()
    validate_drone_products(records, qa)
    assert "empty_path" in [r.category for r in qa.records]


def test_validate_empty_crs_is_warning(tmp_path):
    content = "product_type,path,crs,vertical_datum,resolution_m\northomosaic,/data/x.tif,,,\n"
    records = parse_product_manifest(_write(tmp_path, "nocrs.csv", content), "FLT-005")
    qa = QACollector()
    validate_drone_products(records, qa)
    assert "empty_crs" in [r.category for r in qa.records if r.severity == SEV_WARNING]


def test_validate_check_paths_missing_file_is_error(tmp_path):
    content = "product_type,path,crs,vertical_datum,resolution_m\northomosaic,/nope/ortho.tif,EPSG:4326,,\n"
    records = parse_product_manifest(_write(tmp_path, "missing.csv", content), "FLT-006")
    qa = QACollector()
    validate_drone_products(records, qa, check_paths=True)
    assert "path_not_found" in [r.category for r in qa.records]


def test_validate_check_paths_existing_file_no_error(tmp_path):
    real = tmp_path / "ortho.tif"
    real.write_bytes(b"")
    content = f"product_type,path,crs,vertical_datum,resolution_m\northomosaic,{real},EPSG:4326,,\n"
    records = parse_product_manifest(_write(tmp_path, "real.csv", content), "FLT-007")
    qa = QACollector()
    validate_drone_products(records, qa, check_paths=True)
    assert not any(r.category == "path_not_found" for r in qa.records)


def test_validate_empty_manifest_is_warning(tmp_path):
    p = _write(tmp_path, "empty.csv", "product_type,path,crs,vertical_datum,resolution_m\n")
    records = parse_product_manifest(p, "FLT-008")
    qa = QACollector()
    validate_drone_products(records, qa)
    assert "empty_manifest" in [r.category for r in qa.records]


def test_validate_produces_info_record_on_success(tmp_path):
    records = parse_product_manifest(_write(tmp_path, "m.csv", _MANIFEST_CSV), "FLT-001")
    qa = QACollector()
    validate_drone_products(records, qa)
    assert "manifest_parsed" in [r.category for r in qa.records if r.severity == SEV_INFO]


# ---- classify_records -------------------------------------------------------

def test_classify_raster_vs_non_raster(tmp_path):
    records = parse_product_manifest(_write(tmp_path, "m.csv", _MANIFEST_CSV), "FLT-001")
    rasters, others = classify_records(records)
    assert len(rasters) == 3
    assert len(others) == 1
    assert all(r.product_type in RASTER_PRODUCT_TYPES for r in rasters)
    assert others[0].product_type == "point_cloud"


def test_classify_all_rasters(tmp_path):
    content = (
        "product_type,path,crs,vertical_datum,resolution_m\n"
        "orthomosaic,/data/ortho.tif,EPSG:4326,,\n"
        "DSM,/data/dsm.tif,EPSG:4326,,\n"
    )
    records = parse_product_manifest(_write(tmp_path, "r.csv", content), "FLT-009")
    rasters, others = classify_records(records)
    assert len(rasters) == 2
    assert others == []


def test_classify_all_point_clouds(tmp_path):
    content = "product_type,path,crs,vertical_datum,resolution_m\npoint_cloud,/data/cloud.las,EPSG:4326,,\n"
    records = parse_product_manifest(_write(tmp_path, "pc.csv", content), "FLT-010")
    rasters, others = classify_records(records)
    assert rasters == []
    assert len(others) == 1


# ---- parse_gcp_csv ----------------------------------------------------------

def test_parse_gcp_csv_count(tmp_path):
    pts = parse_gcp_csv(_write(tmp_path, "g.csv", _GCP_CSV), "FLT-001")
    assert len(pts) == 2


def test_parse_gcp_csv_flight_id_stamped(tmp_path):
    pts = parse_gcp_csv(_write(tmp_path, "g.csv", _GCP_CSV), "FLT-011")
    assert all(pt.flight_id == "FLT-011" for pt in pts)


def test_parse_gcp_csv_residuals_optional(tmp_path):
    pts = parse_gcp_csv(_write(tmp_path, "g.csv", _GCP_CSV), "FLT-001")
    assert abs(pts[0].residual_h - 0.02) < 1e-9
    assert pts[1].residual_h is None
    assert pts[1].residual_v is None


def test_parse_gcp_csv_coordinates(tmp_path):
    pts = parse_gcp_csv(_write(tmp_path, "g.csv", _GCP_CSV), "FLT-001")
    assert abs(pts[0].northing - 4527893.12) < 0.001
    assert abs(pts[0].easting - 293847.55) < 0.001
    assert abs(pts[0].elevation - 512.34) < 0.001


def test_parse_gcp_csv_skips_malformed_row(tmp_path):
    """A GCP row with missing/non-numeric coords is skipped, not a raw traceback."""
    bad = ("point_id,northing,easting,elevation,point_type\n"
           "GCP-01,4527893.12,293847.55,512.34,GCP\n"
           "GCP-BAD,,,,GCP\n"
           "GCP-NAN,abc,293900.0,510.0,GCP\n")
    pts = parse_gcp_csv(_write(tmp_path, "g.csv", bad), "FLT-001")
    assert len(pts) == 1
    assert pts[0].point_id == "GCP-01"


def test_invalid_product_type_not_double_counted_as_duplicate(tmp_path):
    content = ("product_type,path,crs,vertical_datum,resolution_m\n"
               "badtype,/a.tif,EPSG:4326,,\n"
               "badtype,/b.tif,EPSG:4326,,\n")
    records = parse_product_manifest(_write(tmp_path, "x.csv", content), "FLT")
    qa = QACollector()
    validate_drone_products(records, qa)
    cats = [r.category for r in qa.records]
    assert "duplicate_product_type" not in cats
    assert cats.count("invalid_product_type") == 2


def test_parse_manifest_short_row_does_not_crash(tmp_path):
    # Trailing columns omitted → DictReader fills None; must coerce, not crash.
    content = "product_type,path,crs,vertical_datum,resolution_m\northomosaic,/o.tif\n"
    records = parse_product_manifest(_write(tmp_path, "short.csv", content), "FLT")
    assert len(records) == 1
    assert records[0].product_type == "orthomosaic"
    assert records[0].crs == ""
    assert records[0].resolution_m is None


def test_parse_gcp_csv_short_row_does_not_crash(tmp_path):
    content = ("point_id,northing,easting,elevation,point_type,residual_h,residual_v\n"
               "GCP-01,1.0,2.0,3.0\n")
    pts = parse_gcp_csv(_write(tmp_path, "g.csv", content), "FLT")
    assert len(pts) == 1
    assert pts[0].point_type == "GCP"
    assert pts[0].residual_h is None


def test_module_imports_without_arcpy():
    import importlib
    mod = importlib.import_module("autogis.core.envmon.import_drone_products")
    assert hasattr(mod, "parse_product_manifest")
    assert hasattr(mod, "parse_gcp_csv")
