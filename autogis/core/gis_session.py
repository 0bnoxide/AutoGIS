import os

try:
    from arcgis.gis import GIS
except Exception:  # pragma: no cover
    GIS = None

AGOL_URL = "https://www.arcgis.com"


def build_gis(profile=None, username=None, password=None, gis_factory=GIS):
    if gis_factory is None:
        raise RuntimeError("arcgis is not installed; cannot build a GIS")
    if profile:
        return gis_factory(profile=profile)
    if username and password:
        return gis_factory(AGOL_URL, username, password)
    raise ValueError("No credentials: set a profile or AGOL_USER/AGOL_PASS")


def build_gis_from_env(profile, gis_factory=GIS):
    return build_gis(
        profile=profile,
        username=os.environ.get("AGOL_USER"),
        password=os.environ.get("AGOL_PASS"),
        gis_factory=gis_factory,
    )
