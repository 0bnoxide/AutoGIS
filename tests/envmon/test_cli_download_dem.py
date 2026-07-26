"""CLI wiring tests for `autogis envmon download-dem` — offline, arcpy-free.

The download path is exercised by monkeypatching the core module's
_default_http_get seam; no test touches the network.
"""
import pytest
from click.testing import CliRunner

from autogis.adapters.cli import autogis as cli_root


@pytest.fixture
def runner():
    return CliRunner()


def _invoke(runner, args, env=None):
    return runner.invoke(cli_root, ["envmon", "download-dem"] + args,
                         env=env, catch_exceptions=False)


def test_list_datasets_prints_registry_and_exits(runner):
    result = _invoke(runner, ["--list-datasets"])
    assert result.exit_code == 0
    assert "USGS10m" in result.output
    assert "usgsdem" in result.output
    assert "COP30" in result.output
    assert "globaldem" in result.output


def test_bbox_and_aoi_are_mutually_exclusive(runner, tmp_path):
    aoi = tmp_path / "aoi.geojson"
    aoi.write_text('{"type":"Point","coordinates":[-106.25,39.65]}')
    result = runner.invoke(cli_root, [
        "envmon", "download-dem",
        "--bbox", "-106.3", "39.6", "-106.2", "39.7", "--aoi", str(aoi)])
    assert result.exit_code != 0
    assert "mutually exclusive" in result.output


def test_missing_aoi_and_bbox_is_a_usage_error(runner):
    result = runner.invoke(cli_root, ["envmon", "download-dem"])
    assert result.exit_code != 0
    assert "--bbox" in result.output and "--aoi" in result.output


def test_unknown_dataset_lists_the_valid_codes(runner):
    """Task 5: --dataset is now a strict click.Choice, so an unknown code is a
    Click usage error (exit 2) listing the valid codes, not the difflib "did
    you mean" hint that opentopo.get_dataset() used to raise (that body path
    is now unreachable for this input -- Click rejects it during parsing)."""
    result = runner.invoke(cli_root, [
        "envmon", "download-dem", "--dataset", "usgs10",
        "--bbox", "-106.3", "39.6", "-106.2", "39.7"])
    assert result.exit_code == 2
    assert "usgs10m" in result.output.lower()


def test_dry_run_needs_no_api_key_and_redacts(runner, monkeypatch):
    monkeypatch.delenv("OPENTOPOGRAPHY_API_KEY", raising=False)
    result = _invoke(runner, [
        "--bbox", "-106.3", "39.6", "-106.2", "39.7", "--dry-run"])
    assert result.exit_code == 0
    assert "usgsdem" in result.output          # routing shown
    assert "REDACTED" in result.output         # redacted URL
    assert "km2" in result.output              # area estimate
    assert "dry run" in result.output.lower()


def test_download_writes_file_via_seam(runner, tmp_path, monkeypatch):
    from autogis.core.envmon import opentopo

    def fake_default_get(url):
        body = b"GEOTIFF"
        return 200, {"Content-Length": str(len(body))}, iter([body])

    monkeypatch.setattr(opentopo, "_default_http_get", fake_default_get)
    out = tmp_path / "site_dem.tif"
    result = _invoke(runner, [
        "--bbox", "-106.3", "39.6", "-106.2", "39.7", "--out", str(out)],
        env={"OPENTOPOGRAPHY_API_KEY": "TESTKEY"})
    assert result.exit_code == 0, result.output
    assert out.read_bytes() == b"GEOTIFF"
    assert (tmp_path / "site_dem.tif.json").exists()
    assert "Wrote" in result.output


def test_existing_out_without_overwrite_fails_cleanly(runner, tmp_path):
    out = tmp_path / "dem.tif"
    out.write_bytes(b"precious")
    result = _invoke(runner, [
        "--bbox", "-106.3", "39.6", "-106.2", "39.7", "--out", str(out)],
        env={"OPENTOPOGRAPHY_API_KEY": "TESTKEY"})
    assert result.exit_code != 0
    assert "--overwrite" in result.output
    assert out.read_bytes() == b"precious"


def test_http_error_exits_nonzero_with_qa(runner, tmp_path, monkeypatch):
    from autogis.core.envmon import opentopo

    monkeypatch.setattr(opentopo, "_default_http_get",
                        lambda url: (401, {}, iter([b""])))
    result = _invoke(runner, [
        "--bbox", "-106.3", "39.6", "-106.2", "39.7",
        "--out", str(tmp_path / "d.tif")],
        env={"OPENTOPOGRAPHY_API_KEY": "BADKEY"})
    assert result.exit_code != 0
    assert "rejected the API key" in result.output


def test_registered_in_list_tools(runner):
    result = runner.invoke(cli_root, ["envmon", "list-tools"])
    assert result.exit_code == 0
    assert "download-dem" in result.output
