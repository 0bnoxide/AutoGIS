"""CLI tests for `autogis handoff` (ADR-0128)."""
import json
import zipfile

from click.testing import CliRunner

from autogis.adapters.cli import autogis

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


def _write_source(tmp_path):
    p = tmp_path / "source.xml"
    p.write_text(_METRIC, encoding="utf-8")
    return p


def test_handoff_known_datum_succeeds(tmp_path):
    out = tmp_path / "pkg.zip"
    result = CliRunner().invoke(autogis, [
        "handoff",
        "--input", str(_write_source(tmp_path)),
        "--output", str(out),
        "--vertical-unit", "metre",
        "--vertical-datum-authority", "EPSG",
        "--vertical-datum-code", "5703",
        "--vertical-datum-name", "NAVD88 height",
        "--source-commit", "0123abc",
    ])
    assert result.exit_code == 0, result.output
    assert "handoff package ->" in result.output
    with zipfile.ZipFile(out) as zf:
        manifest = json.loads(zf.read("handoff.json").decode("utf-8"))
    assert manifest["coordinate_reference"]["vertical"]["datum"][
        "status"] == "known"


def test_handoff_partial_datum_trio_fails(tmp_path):
    result = CliRunner().invoke(autogis, [
        "handoff",
        "--input", str(_write_source(tmp_path)),
        "--output", str(tmp_path / "pkg.zip"),
        "--vertical-unit", "metre",
        "--vertical-datum-authority", "EPSG",
    ])
    assert result.exit_code != 0
    assert "authority, code, and name" in result.output


def test_handoff_vertical_family_mismatch_fails(tmp_path):
    result = CliRunner().invoke(autogis, [
        "handoff",
        "--input", str(_write_source(tmp_path)),
        "--output", str(tmp_path / "pkg.zip"),
        "--vertical-unit", "international_foot",
    ])
    assert result.exit_code != 0
    assert "elevation family" in result.output
