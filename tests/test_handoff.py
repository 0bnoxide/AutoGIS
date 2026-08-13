"""Tests for autogis/core/handoff.py (ADR-0128 contract-v1 emitter)."""
import hashlib
import json
import tomllib
import uuid
import zipfile
from pathlib import Path

import pytest

from autogis import __version__
from autogis.core.handoff import build_handoff_package

_METRIC = """<?xml version="1.0"?>
<LandXML xmlns="http://www.landxml.org/schema/LandXML-1.2" version="1.2">
  <Units>
    <Metric linearUnit="meter" elevationUnit="meter"/>
  </Units>
  <CoordinateSystem name="EPSG:26913" epsgCode="26913"/>
  <Surfaces>
    <Surface name="Existing Ground">
      <Definition surfType="TIN">
        <Pnts>
          <P id="1">0.0 0.0 100.0</P>
          <P id="2">0.0 10.0 102.0</P>
          <P id="3">10.0 0.0 98.0</P>
        </Pnts>
        <Faces>
          <F>1 2 3</F>
        </Faces>
      </Definition>
    </Surface>
  </Surfaces>
</LandXML>
"""

_IMPERIAL = _METRIC.replace(
    '<Metric linearUnit="meter" elevationUnit="meter"/>',
    '<Imperial linearUnit="USSurveyFoot" elevationUnit="feet"/>').replace(
    'name="EPSG:26913" epsgCode="26913"', 'name="EPSG:2256" epsgCode="2256"')

KNOWN = dict(datum_authority="EPSG", datum_code=5703,
             datum_name="NAVD88 height")


def _source(tmp_path, text=_METRIC):
    p = tmp_path / "source.xml"
    p.write_text(text, encoding="utf-8")
    return p


def test_known_datum_manifest_and_zip(tmp_path):
    out = tmp_path / "pkg.zip"
    manifest = build_handoff_package(
        _source(tmp_path), out, vertical_unit="metre",
        source_commit="0123abc", **KNOWN)
    with zipfile.ZipFile(out) as zf:
        assert sorted(zf.namelist()) == ["handoff.json", "surface.landxml"]
        stored = json.loads(zf.read("handoff.json").decode("utf-8"))
        surface_bytes = zf.read("surface.landxml")
    assert stored == manifest
    assert manifest["contract_version"] == "1.0"
    uuid.UUID(manifest["package_id"])
    assert manifest["created_utc"].endswith("Z")
    assert manifest["producer"] == {
        "name": "AutoGIS", "version": __version__,
        "source_commit": "0123abc"}
    surface = manifest["surface"]
    assert surface["filename"] == "surface.landxml"
    assert surface["landxml_version"] == "1.2"
    assert surface["sha256"] == hashlib.sha256(surface_bytes).hexdigest()
    assert surface["name"] == "Existing Ground"
    assert surface["point_count"] == 3
    assert surface["face_count"] == 1
    ref = manifest["coordinate_reference"]
    assert ref["horizontal"] == {"kind": "projected", "authority": "EPSG",
                                 "code": 26913, "unit": "metre"}
    assert ref["vertical"] == {
        "unit": "metre", "direction": "positive_up",
        "datum": {"status": "known", "authority": "EPSG", "code": 5703,
                  "name": "NAVD88 height"}}
    assert b"<Pnts>" in surface_bytes  # re-emitted by the writer


def test_unknown_datum_with_note(tmp_path):
    manifest = build_handoff_package(
        _source(tmp_path), tmp_path / "pkg.zip", vertical_unit="metre",
        datum_note="Confirm project datum before import")
    assert manifest["coordinate_reference"]["vertical"]["datum"] == {
        "status": "unknown", "note": "Confirm project datum before import"}
    assert "source_commit" not in manifest["producer"]


def test_unknown_datum_without_note_has_no_note_key(tmp_path):
    manifest = build_handoff_package(
        _source(tmp_path), tmp_path / "pkg.zip", vertical_unit="metre")
    assert manifest["coordinate_reference"]["vertical"]["datum"] == {
        "status": "unknown"}


def test_partial_datum_trio_rejected(tmp_path):
    with pytest.raises(ValueError, match="authority, code, and name"):
        build_handoff_package(
            _source(tmp_path), tmp_path / "pkg.zip", vertical_unit="metre",
            datum_authority="EPSG", datum_code=5703)


def test_note_with_known_datum_rejected(tmp_path):
    with pytest.raises(ValueError, match="only valid with an unknown"):
        build_handoff_package(
            _source(tmp_path), tmp_path / "pkg.zip", vertical_unit="metre",
            datum_note="nope", **KNOWN)


def test_missing_epsg_rejected(tmp_path):
    text = _METRIC.replace(
        '  <CoordinateSystem name="EPSG:26913" epsgCode="26913"/>\n', "")
    with pytest.raises(ValueError, match="no EPSG horizontal CRS"):
        build_handoff_package(
            _source(tmp_path, text), tmp_path / "pkg.zip",
            vertical_unit="metre")


def test_missing_units_rejected(tmp_path):
    text = _METRIC.replace(
        '  <Units>\n    <Metric linearUnit="meter" elevationUnit="meter"/>\n'
        '  </Units>\n', "")
    with pytest.raises(ValueError, match="no supported LandXML linearUnit"):
        build_handoff_package(
            _source(tmp_path, text), tmp_path / "pkg.zip",
            vertical_unit="metre")


def test_metric_source_rejects_foot_vertical(tmp_path):
    with pytest.raises(ValueError, match="elevation family"):
        build_handoff_package(
            _source(tmp_path), tmp_path / "pkg.zip",
            vertical_unit="international_foot")


def test_imperial_source_takes_either_foot_and_rejects_metre(tmp_path):
    manifest = build_handoff_package(
        _source(tmp_path, _IMPERIAL), tmp_path / "a.zip",
        vertical_unit="us_survey_foot")
    ref = manifest["coordinate_reference"]
    assert ref["horizontal"]["unit"] == "us_survey_foot"
    assert ref["horizontal"]["code"] == 2256
    assert ref["vertical"]["unit"] == "us_survey_foot"
    with pytest.raises(ValueError, match="elevation family"):
        build_handoff_package(
            _source(tmp_path, _IMPERIAL), tmp_path / "b.zip",
            vertical_unit="metre")


def test_contradictory_elevation_unit_rejected(tmp_path):
    text = _IMPERIAL.replace('elevationUnit="feet"', 'elevationUnit="meter"')
    with pytest.raises(ValueError, match="refusing to alter"):
        build_handoff_package(
            _source(tmp_path, text), tmp_path / "pkg.zip",
            vertical_unit="us_survey_foot")


def test_identical_input_output_rejected_even_with_overwrite(tmp_path):
    src = _source(tmp_path)
    with pytest.raises(ValueError, match="must be different"):
        build_handoff_package(
            src, src, vertical_unit="metre", overwrite=True)


def test_existing_output_needs_overwrite(tmp_path):
    out = tmp_path / "pkg.zip"
    out.write_bytes(b"old")
    with pytest.raises(FileExistsError):
        build_handoff_package(_source(tmp_path), out, vertical_unit="metre")
    build_handoff_package(
        _source(tmp_path), out, vertical_unit="metre", overwrite=True)
    assert zipfile.is_zipfile(out)


def test_bad_source_commit_rejected(tmp_path):
    with pytest.raises(ValueError, match="lowercase hex"):
        build_handoff_package(
            _source(tmp_path), tmp_path / "pkg.zip", vertical_unit="metre",
            source_commit="ABCDEF1")


def test_version_matches_pyproject():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    with pyproject.open("rb") as fh:
        assert tomllib.load(fh)["project"]["version"] == __version__
