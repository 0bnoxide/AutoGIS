"""Offline .pyt dialog/execution contracts; not interactive ArcGIS Pro acceptance."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from autogis.adapters import qualification, toolbox_core
from autogis.core.common.qa import QACollector
from autogis.core.envmon import msl_lidar
from tests.test_qualification import _Parameter


class _SpatialReference:
    name = "WGS 84 / UTM zone 12N"
    type = "Projected"
    VCS = None

    def __init__(self, code=None):
        self.text = f"EPSG:{code}" if code else ""

    def exportToString(self):
        return self.text

    def loadFromString(self, text):
        self.text = text


@pytest.fixture
def dialog(monkeypatch, tmp_path):
    active_map = SimpleNamespace(
        URI="map:dem", spatialReference=_SpatialReference(26912),
        addDataFromPath=Mock(return_value="dem-layer"))
    view = SimpleNamespace(
        map=active_map, getLayerExtent=Mock(return_value="raster-extent"),
        camera=SimpleNamespace(setExtent=Mock()))
    project = SimpleNamespace(activeMap=active_map, activeView=view)
    arcpy = SimpleNamespace(
        Parameter=_Parameter, SpatialReference=_SpatialReference,
        mp=SimpleNamespace(ArcGISProject=Mock(return_value=project)),
        CheckExtension=Mock(return_value="Unavailable"))
    monkeypatch.setitem(sys.modules, "arcpy", arcpy)
    module = qualification._load_toolbox(qualification._toolbox_path())
    tool = module.DownloadMSLDEM()
    parameters = tool.getParameterInfo()
    p = {item.name: item for item in parameters}
    p["aoi_source"].value = "Manual bbox"
    p["manual_bbox"].value = "-112 46 -111 47"
    p["out_raster"].value = str(tmp_path / "requested.tif")
    qa = QACollector()
    qa.add("WARNING", "coverage", "Partial coverage")
    result = SimpleNamespace(
        out_path=tmp_path / "resolved.tif", qa=qa,
        plan=SimpleNamespace(to_dict=lambda: {"archives": 2, "total_bytes": 42}))
    runner = Mock(return_value=result)
    monkeypatch.setattr(msl_lidar, "run_msl_download", runner)
    messages = SimpleNamespace(addMessage=Mock(), addWarningMessage=Mock(),
                               addErrorMessage=Mock())
    # Run-history persistence is covered separately; execute the real tool body.
    def execute():
        return tool.execute.__wrapped__(tool, parameters, messages)
    return SimpleNamespace(tool=tool, parameters=parameters, p=p, arcpy=arcpy,
                           project=project, view=view, active_map=active_map,
                           runner=runner, result=result, messages=messages,
                           execute=execute)


@pytest.mark.parametrize("source,reproject,enabled", [
    ("Active map extent", False, (False, False, True)),
    ("Feature layer (selection if any)", False, (True, False, True)),
    ("Manual bbox", True, (False, True, False)),
    (None, False, (False, False, True)),
])
def test_dialog_enables_only_relevant_aoi_and_crs_inputs(dialog, source, reproject, enabled):
    d = dialog
    d.p["aoi_source"].value = source
    d.p["reproject"].value = reproject
    d.tool.updateParameters(d.parameters)
    assert tuple(d.p[name].enabled for name in ("aoi_layer", "manual_bbox", "output_crs")) == enabled
    assert d.p["aoi_layer"].filter.list == ["Polygon"]
    assert d.p["out_raster"].direction == "Output"
    assert d.p["out_raster"].parameterType == "Required"
    assert d.p["z_units"].filter.list == ["native", "m", "int-ft", "us-ft"]


def test_execute_passes_geometry_and_normalized_options_to_download(dialog):
    d = dialog
    for key, value in {
        "projects": " 'Upper Missouri' ; ; Yellowstone ", "cache_dir": "cache",
        "allow_large_download": True, "large_download_gib": 2.5,
        "overwrite": True, "output_crs": "EPSG:26912",
        "output_resolution": 3, "add_to_map": False,
    }.items():
        d.p[key].value = value
    d.execute()
    options = d.runner.call_args.kwargs
    assert options["geometry"] == {
        "type": "Polygon", "coordinates": [[[-112.0, 46.0], [-111.0, 46.0],
        [-111.0, 47.0], [-112.0, 47.0], [-112.0, 46.0]]]}
    assert {key: options[key] for key in (
        "projects", "cache_dir", "product", "dry_run", "overwrite",
        "allow_large_download", "threshold_bytes", "output_crs", "resolution", "z_units"
    )} == {
        "projects": ["Upper Missouri", "Yellowstone"], "cache_dir": "cache",
        "product": "HFDEM", "dry_run": False, "overwrite": True,
        "allow_large_download": True, "threshold_bytes": 2684354560.0,
        "output_crs": "EPSG:26912", "resolution": 3.0, "z_units": "native"}
    assert Path(options["out_path"]).name == "requested.tif"
    assert d.p["out_raster"].value == str(d.result.out_path)
    d.messages.addWarningMessage.assert_called_once_with("[WARNING] coverage: Partial coverage")
    d.active_map.addDataFromPath.assert_not_called()
    d.arcpy.CheckExtension.assert_not_called()


def test_preview_reports_plan_without_publishing_output_or_requiring_license(dialog):
    d = dialog
    d.p["preview"].value = True
    d.p["z_units"].value = "m"
    original = d.p["out_raster"].value
    d.execute()
    options = d.runner.call_args.kwargs
    assert options["dry_run"] is True
    assert options["z_units"] == "m"
    assert options["projects"] == []
    assert options["cache_dir"] is None
    assert options["resolution"] is None
    assert options["threshold_bytes"] == 1073741824
    text = [call.args[0] for call in d.messages.addMessage.call_args_list]
    assert json.loads(text[0]) == {"archives": 2, "total_bytes": 42}
    assert "Preview only" in text[1]
    assert d.p["out_raster"].value == original
    d.active_map.addDataFromPath.assert_not_called()
    d.arcpy.CheckExtension.assert_not_called()
    d.messages.addWarningMessage.assert_not_called()


def test_native_processor_callback_preserves_geometry_and_options(dialog, monkeypatch):
    processor = Mock(return_value={"valid_cells": 4})
    monkeypatch.setattr(toolbox_core, "process_msl_dem_arcpy", processor)
    dialog.execute()
    callback = dialog.runner.call_args.kwargs["processor"]
    geometry = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [0, 1], [0, 0]]]}
    assert callback(["source.tif"], geometry, "clipped.tif", resolution=2,
                    output_crs="EPSG:26912", z_units="m") == {"valid_cells": 4}
    processor.assert_called_once_with(dialog.arcpy, ["source.tif"], geometry,
        "clipped.tif", resolution=2, output_crs="EPSG:26912", z_units="m")


def test_progress_is_throttled_by_ten_mib_and_handles_unknown_total(dialog):
    dialog.execute()
    progress = dialog.runner.call_args.kwargs["on_progress"]
    dialog.messages.addMessage.reset_mock()
    progress(1, None)
    progress(10 * 1024**2 - 1, None)
    progress(10 * 1024**2, 20 * 1024**2)
    progress(10 * 1024**2 + 1, 20 * 1024**2)
    assert [call.args[0] for call in dialog.messages.addMessage.call_args_list] == [
        "Downloaded 1 / unknown bytes", "Downloaded 10,485,760 / 20971520 bytes"]


@pytest.mark.parametrize("view_kind", ["matching", "other-map", "missing", "layout"])
def test_download_adds_layer_but_zooms_only_matching_map_view(dialog, view_kind):
    d = dialog
    if view_kind == "other-map":
        d.view.map = SimpleNamespace(URI="map:other")
    elif view_kind == "missing":
        d.project.activeView = None
    elif view_kind == "layout":
        d.project.activeView = SimpleNamespace()
    d.execute()
    d.active_map.addDataFromPath.assert_called_once_with(str(d.result.out_path))
    if view_kind == "matching":
        d.view.getLayerExtent.assert_called_once_with("dem-layer", False, False)
        d.view.camera.setExtent.assert_called_once_with("raster-extent")
    else:
        d.view.getLayerExtent.assert_not_called()
        d.view.camera.setExtent.assert_not_called()


def test_missing_map_still_returns_raster_without_map_insertion(dialog):
    dialog.project.activeMap = None
    dialog.execute()
    assert dialog.p["out_raster"].value == str(dialog.result.out_path)
    dialog.active_map.addDataFromPath.assert_not_called()
    dialog.view.camera.setExtent.assert_not_called()


def test_reproject_uses_active_map_crs_instead_of_stale_explicit_value(dialog):
    dialog.p["reproject"].value = True
    dialog.p["output_crs"].value = "EPSG:4326"
    dialog.execute()
    assert dialog.runner.call_args.kwargs["output_crs"] == "EPSG:26912"


@pytest.mark.parametrize("failure", [ValueError("invalid archive"), RuntimeError("processor failed"), OSError("disk full")])
def test_download_failure_is_reported_and_never_published(dialog, failure):
    dialog.runner.side_effect = failure
    original = dialog.p["out_raster"].value
    with pytest.raises(type(failure), match=str(failure)):
        dialog.execute()
    dialog.messages.addErrorMessage.assert_called_once_with(str(failure))
    assert dialog.p["out_raster"].value == original
    dialog.active_map.addDataFromPath.assert_not_called()


@pytest.mark.parametrize("problem,message", [
    ("missing-map", "Open an active map"),
    ("invalid-bbox", "bbox"),
    ("no-license", "Elevation conversion requires"),
])
def test_preflight_errors_stop_download_and_are_reported(dialog, problem, message):
    if problem == "missing-map":
        dialog.project.activeMap = None
        dialog.p["reproject"].value = True
    elif problem == "invalid-bbox":
        dialog.p["manual_bbox"].value = "-111 46 -112 47"
    else:
        dialog.p["z_units"].value = "us-ft"
    with pytest.raises(ValueError, match=message):
        dialog.execute()
    assert message in dialog.messages.addErrorMessage.call_args.args[0]
    dialog.runner.assert_not_called()
    dialog.active_map.addDataFromPath.assert_not_called()


@pytest.mark.parametrize("available", ["Spatial", "ImageAnalyst"])
def test_either_raster_extension_allows_elevation_conversion(dialog, available):
    dialog.arcpy.CheckExtension.side_effect = lambda code: "Available" if code == available else "Unavailable"
    dialog.p["z_units"].value = "int-ft"
    dialog.execute()
    assert dialog.runner.call_args.kwargs["z_units"] == "int-ft"
    assert dialog.p["out_raster"].value == str(dialog.result.out_path)
