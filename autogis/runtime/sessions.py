"""Session providers for the suite's adapters.

Three providers, each lazy: importing this module touches neither ``arcgis``
nor ``arcpy`` — only *calling* a provider that needs them does.

- ``agol_from_profile``  — an ArcGIS Online / portal ``GIS`` from a named
  ArcGIS API for Python profile (or anonymous). This is where the harvester's
  former ``connection.profile`` lives now (deltas H1: profile moved to
  ``runtime/sessions.py``).
- ``pro_active_portal``  — the ``GIS("pro")`` active portal inside ArcGIS Pro.
- ``arcpy_env``          — the ambient ``arcpy`` module + environment, for the
  LOCAL (arcpy) tools, returned only where Pro is present.
"""


def agol_from_profile(profile=None, *, url=None, username=None, password=None,
                      gis_factory=None):
    """Return a ``GIS`` for AGOL / a portal from a profile or explicit creds.

    ``profile`` is an ArcGIS API for Python connection profile name. With no
    args this yields an anonymous ``GIS()``. Lazy: ``arcgis`` is imported only
    when called.
    """
    if gis_factory is None:
        from arcgis.gis import GIS as gis_factory
    if profile:
        return gis_factory(profile=profile)
    if url or username:
        return gis_factory(url=url, username=username, password=password)
    return gis_factory()


def pro_active_portal(gis_factory=None):
    """Return a GIS connected to ArcGIS Pro's active portal (``GIS("pro")``).

    Only resolvable inside ArcGIS Pro, where ``arcgis`` is on the path. Lazy
    by design: importing this module never touches ``arcgis``.
    """
    if gis_factory is None:
        from arcgis.gis import GIS as gis_factory
    return gis_factory("pro")


def arcpy_env():
    """Return the active ``arcpy`` module for LOCAL (arcpy) tools.

    Lazy: only resolvable in ArcGIS Pro. Adapters should gate on
    ``adapters.guard.require_runtime`` before calling this so the failure is a
    clean ``RuntimeUnavailable`` rather than a raw ``ImportError``.
    """
    import arcpy
    return arcpy
