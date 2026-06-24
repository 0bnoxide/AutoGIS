"""Back-compat shim. Canonical builder: autogis.runtime.sessions.agol_from_profile."""
from autogis.runtime.sessions import agol_from_profile as _agol

AGOL_URL = "https://www.arcgis.com"


def build_gis(profile=None, username=None, password=None, gis_factory=None):
    if not profile and not username:
        raise ValueError("No credentials: set a profile or AGOL_USER/AGOL_PASS")
    return _agol(profile=profile, url=AGOL_URL if username else None,
                 username=username, password=password, gis_factory=gis_factory)


def build_gis_from_env(profile, gis_factory=None):
    import os
    return build_gis(profile=profile,
                     username=os.environ.get("AGOL_USER"),
                     password=os.environ.get("AGOL_PASS"),
                     gis_factory=gis_factory)
