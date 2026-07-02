import builtins

from click.testing import CliRunner

from autogis.adapters.cli import autogis
from autogis.core.common.qa import QACollector, SEV_WARNING
from autogis.core.envmon.civil3d_points import (
    build_pnezd, load_gwe_points_csv, write_pnezd_csv, write_projection_note)


def _no_arcpy_monkeypatch(monkeypatch):
    real = builtins.__import__

    def fake(name, *a, **k):
        if name == "arcpy":
            raise ModuleNotFoundError("No module named 'arcpy'")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)


def _rec(loc, x=1000.0, y=2000.0, z=512.5, **kw):
    return {"location_id": loc, "x": x, "y": y, "z": z, **kw}


def test_build_pnezd_sequential_numbering():
    qa = QACollector()
    pts = build_pnezd(
        [_rec("MW-1"), _rec("MW-2"), _rec("MW-3")], crs="EPSG:2256",
        start_number=100, qa=qa)
    assert [p.point_number for p in pts] == [100, 101, 102]


def test_build_pnezd_maps_nez_from_records():
    qa = QACollector()
    pts = build_pnezd([_rec("MW-1", x=1000.0, y=2000.0, z=512.5)],
                       crs="EPSG:2256", qa=qa)
    assert pts[0].easting == 1000.0
    assert pts[0].northing == 2000.0
    assert pts[0].elevation == 512.5
    assert pts[0].description == "MW-1"


def test_write_pnezd_csv_header_and_order(tmp_path):
    qa = QACollector()
    pts = build_pnezd([_rec("MW-1"), _rec("MW-2")], crs="EPSG:2256", qa=qa)
    out = write_pnezd_csv(pts, tmp_path / "points_pnezd.csv")
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "point_number,northing,easting,elevation,description"
    assert len(lines) == 3
    assert lines[1].split(",")[0] == str(pts[0].point_number)


def test_missing_elevation_skipped_with_warning():
    qa = QACollector()
    pts = build_pnezd(
        [_rec("MW-1"), {"location_id": "MW-2", "x": 1.0, "y": 2.0, "z": ""}],
        crs="EPSG:2256", start_number=1, qa=qa)
    assert len(pts) == 1
    assert pts[0].point_number == 1
    assert any(r.severity == SEV_WARNING and r.category == "missing_elevation"
               for r in qa.records)


def test_load_gwe_points_csv(tmp_path):
    path = tmp_path / "points.csv"
    path.write_text("location_id,x,y,z\nMW-1,1000.0,2000.0,512.5\n", encoding="utf-8")
    records = load_gwe_points_csv(path)
    assert records == [{"location_id": "MW-1", "x": "1000.0", "y": "2000.0", "z": "512.5"}]


def test_export_civil3d_headless_writes_csv_and_note(tmp_path):
    points = tmp_path / "points.csv"
    points.write_text("location_id,x,y,z\nMW-1,1000.0,2000.0,512.5\n", encoding="utf-8")
    out_dir = tmp_path / "out"

    result = CliRunner().invoke(
        autogis,
        ["envmon", "export-civil3d",
         "--points", str(points), "--crs", "EPSG:2256", "--out-dir", str(out_dir)],
    )
    assert result.exit_code == 0, result.output
    assert (out_dir / "points_pnezd.csv").exists()
    assert "EPSG:2256" in (out_dir / "projection_note.txt").read_text(encoding="utf-8")


def test_export_civil3d_landxml_guard_headless(monkeypatch, tmp_path):
    _no_arcpy_monkeypatch(monkeypatch)
    points = tmp_path / "points.csv"
    points.write_text("location_id,x,y,z\nMW-1,1000.0,2000.0,512.5\n", encoding="utf-8")

    result = CliRunner().invoke(
        autogis,
        ["envmon", "export-civil3d",
         "--points", str(points), "--crs", "EPSG:2256",
         "--out-dir", str(tmp_path / "out"), "--landxml"],
    )
    assert result.exit_code != 0
    assert "arcpy" in result.output.lower()
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_write_projection_note_reexported(tmp_path):
    out = write_projection_note("EPSG:2256", tmp_path / "note.txt")
    assert "EPSG:2256" in out.read_text(encoding="utf-8")
