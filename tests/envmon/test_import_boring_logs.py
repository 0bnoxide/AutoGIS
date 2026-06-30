"""Arcpy-free tests for import_boring_logs.py (produces schema.boring dataclasses)."""
import csv

from autogis.core.common.qa import QACollector
from autogis.core.common.schema.boring import (
    BoringLocation, LithologyInterval, BoringSample,
)
from autogis.core.envmon.import_boring_logs import (
    parse_boring_locations_csv, parse_lithology_csv, parse_boring_samples_csv,
    validate_boring_package,
)

_LOC_ROWS = [
    {"BoringID": "B-01", "SiteID": "H281", "LocationType": "Monitoring Well",
     "Northing": "4527893.12", "Easting": "293847.55",
     "GroundElevation_ft": "512.34", "Status": "Complete"},
]

_LITH_ROWS = [
    {"BoringID": "B-01", "TopDepth_ft": "0.0", "BottomDepth_ft": "5.0",
     "USCS": "SM", "PrimaryMaterial": "Sandy loam", "Color": "Brown",
     "Moisture": "Moist", "Description": "Fill"},
    {"BoringID": "B-01", "TopDepth_ft": "5.0", "BottomDepth_ft": "12.0",
     "USCS": "CL", "PrimaryMaterial": "Clay", "Color": "Gray",
     "Moisture": "Wet", "Description": "Native"},
]

_SAMP_ROWS = [
    {"SampleID": "B-01-S1", "BoringID": "B-01", "SampleType": "Soil",
     "TopDepth_ft": "3.0", "BottomDepth_ft": "4.5", "Matrix": "SOIL"},
]


def _write(tmp_path, fname, rows):
    p = tmp_path / fname
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return p


def test_parse_boring_locations(tmp_path):
    locs = parse_boring_locations_csv(_write(tmp_path, "loc.csv", _LOC_ROWS))
    assert len(locs) == 1
    assert isinstance(locs[0], BoringLocation)
    assert locs[0].boring_id == "B-01"
    assert locs[0].ground_elevation == 512.34


def test_parse_lithology(tmp_path):
    ivals = parse_lithology_csv(_write(tmp_path, "lith.csv", _LITH_ROWS))
    assert len(ivals) == 2
    assert isinstance(ivals[0], LithologyInterval)
    assert ivals[0].top_depth == 0.0
    assert ivals[1].bottom_depth == 12.0


def test_parse_boring_samples(tmp_path):
    samps = parse_boring_samples_csv(_write(tmp_path, "samples.csv", _SAMP_ROWS))
    assert len(samps) == 1
    assert isinstance(samps[0], BoringSample)
    assert samps[0].sample_id == "B-01-S1"
    assert samps[0].top_depth == 3.0


def test_parse_lithology_skips_rows_missing_depth(tmp_path):
    rows = _LITH_ROWS + [{"BoringID": "B-01", "TopDepth_ft": "", "BottomDepth_ft": "",
                          "USCS": "", "PrimaryMaterial": "", "Color": "",
                          "Moisture": "", "Description": "no depths"}]
    ivals = parse_lithology_csv(_write(tmp_path, "lith.csv", rows))
    assert len(ivals) == 2  # the depthless row is skipped


def test_validate_package_missing_boring_in_lithology(tmp_path):
    locs = parse_boring_locations_csv(_write(tmp_path, "loc.csv", _LOC_ROWS))
    lith_bad = [{**_LITH_ROWS[0], "BoringID": "B-99"}]
    ivals = parse_lithology_csv(_write(tmp_path, "lith.csv", lith_bad))
    qa = QACollector()
    validate_boring_package(locs, ivals, [], qa)
    assert any(r.category == "lithology_boring_not_in_locations" for r in qa.records)


def test_validate_package_overlapping_intervals(tmp_path):
    overlap = [
        {**_LITH_ROWS[0], "TopDepth_ft": "0.0", "BottomDepth_ft": "6.0"},
        {**_LITH_ROWS[1], "TopDepth_ft": "5.0", "BottomDepth_ft": "12.0"},
    ]
    locs = parse_boring_locations_csv(_write(tmp_path, "loc.csv", _LOC_ROWS))
    ivals = parse_lithology_csv(_write(tmp_path, "lith.csv", overlap))
    qa = QACollector()
    validate_boring_package(locs, ivals, [], qa)
    assert any(r.category == "overlapping_intervals" for r in qa.records)


def test_validate_package_clean_has_no_errors(tmp_path):
    locs = parse_boring_locations_csv(_write(tmp_path, "loc.csv", _LOC_ROWS))
    ivals = parse_lithology_csv(_write(tmp_path, "lith.csv", _LITH_ROWS))
    samps = parse_boring_samples_csv(_write(tmp_path, "samples.csv", _SAMP_ROWS))
    qa = QACollector()
    validate_boring_package(locs, ivals, samps, qa)
    assert qa.counts_by_severity().get("ERROR", 0) == 0


def test_parse_lithology_warns_on_dropped_rows_when_qa_given(tmp_path):
    rows = _LITH_ROWS + [{"BoringID": "B-01", "TopDepth_ft": "", "BottomDepth_ft": "",
                          "USCS": "", "PrimaryMaterial": "", "Color": "",
                          "Moisture": "", "Description": "no depths"}]
    qa = QACollector()
    ivals = parse_lithology_csv(_write(tmp_path, "lith.csv", rows), qa)
    assert len(ivals) == 2
    assert any(r.category == "lithology_rows_dropped_missing_depth"
               for r in qa.records)


def test_parse_lithology_no_warning_without_qa(tmp_path):
    rows = _LITH_ROWS + [{"BoringID": "B-01", "TopDepth_ft": "", "BottomDepth_ft": "",
                          "USCS": "", "PrimaryMaterial": "", "Color": "",
                          "Moisture": "", "Description": "no depths"}]
    # No qa supplied → still drops, just no record (backward-compatible signature).
    ivals = parse_lithology_csv(_write(tmp_path, "lith.csv", rows))
    assert len(ivals) == 2


def test_module_imports_without_arcpy():
    import importlib
    mod = importlib.import_module("autogis.core.envmon.import_boring_logs")
    assert hasattr(mod, "parse_boring_locations_csv")
    assert hasattr(mod, "validate_boring_package")
