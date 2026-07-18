from pathlib import Path

import pytest

from autogis.adapters import toolbox_core


@pytest.mark.parametrize(("conversion", "factor", "suffix"), [
    ("Meters to international feet", 1.0 / 0.3048, "m_to_intft"),
    ("Meters to US survey feet", 3937.0 / 1200.0, "m_to_usft"),
    ("International feet to meters", 0.3048, "intft_to_m"),
    ("US survey feet to meters", 1200.0 / 3937.0, "usft_to_m"),
])
def test_elevation_conversion_spec(conversion, factor, suffix):
    actual_factor, actual_suffix = toolbox_core.elevation_conversion_spec(
        conversion)

    assert actual_factor == pytest.approx(factor)
    assert actual_suffix == suffix


class _SavedRaster:
    def __init__(self, calls):
        self.calls = calls

    def save(self, path):
        self.calls.append(("save", path))


class _SpatialAnalyst:
    def __init__(self, calls, error=None):
        self.calls = calls
        self.error = error

    def Times(self, input_raster, factor):
        self.calls.append(("Times", input_raster, factor))
        if self.error is not None:
            raise self.error
        return _SavedRaster(self.calls)


class _ArcPy:
    def __init__(self, statuses=None, checkout_status="CheckedOut",
                 times_error=None):
        self.calls = []
        self.statuses = ({"Spatial": "Available"}
                         if statuses is None else statuses)
        self.checkout_status = checkout_status
        self.sa = _SpatialAnalyst(self.calls, times_error)

    def CheckExtension(self, extension):
        self.calls.append(("CheckExtension", extension))
        return self.statuses.get(extension, "Unavailable")

    def CheckOutExtension(self, extension):
        self.calls.append(("CheckOutExtension", extension))
        return self.checkout_status

    def CheckInExtension(self, extension):
        self.calls.append(("CheckInExtension", extension))


def test_convert_raster_elevation_units_uses_times_and_returns_license():
    arcpy = _ArcPy()
    source = Path("site_epsg2256.tif")

    output = toolbox_core.convert_raster_elevation_units(
        arcpy, source, "Meters to international feet")

    assert output == Path("site_epsg2256_m_to_intft.tif")
    assert ("Times", str(source), pytest.approx(1.0 / 0.3048)) in arcpy.calls
    assert ("save", str(output)) in arcpy.calls
    assert arcpy.calls[-1] == ("CheckInExtension", "Spatial")


def test_convert_raster_elevation_units_accepts_3d_license_fallback():
    arcpy = _ArcPy(statuses={"3D": "Available"})

    toolbox_core.convert_raster_elevation_units(
        arcpy, Path("site.tif"), "Meters to US survey feet")

    assert ("CheckOutExtension", "3D") in arcpy.calls
    assert arcpy.calls[-1] == ("CheckInExtension", "3D")


def test_convert_raster_elevation_units_fails_before_math_without_license():
    arcpy = _ArcPy(statuses={})

    with pytest.raises(ValueError, match="license is unavailable"):
        toolbox_core.convert_raster_elevation_units(
            arcpy, Path("site.tif"), "Meters to international feet")

    assert not [call for call in arcpy.calls if call[0] == "Times"]


def test_convert_raster_elevation_units_returns_license_when_times_fails():
    arcpy = _ArcPy(times_error=RuntimeError("raster write failed"))

    with pytest.raises(RuntimeError, match="raster write failed"):
        toolbox_core.convert_raster_elevation_units(
            arcpy, Path("site.tif"), "Meters to international feet")

    assert arcpy.calls[-1] == ("CheckInExtension", "Spatial")
