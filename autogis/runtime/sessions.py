"""Session providers (AGOL profile/env, active-Pro portal, arcpy env).

Stub for the reference GUI adapter (Task 3); the full provider set is
finalized in Task 5. ``arcgis``/``arcpy`` stay lazy so importing this module
needs neither — only calling a provider that uses them does.
"""


def pro_active_portal(gis_factory=None):
    """Return a GIS connected to ArcGIS Pro's active portal (``GIS("pro")``).

    Only resolvable inside ArcGIS Pro, where ``arcgis`` is on the path. Lazy
    by design: importing this module never touches ``arcgis``.
    """
    if gis_factory is None:
        from arcgis.gis import GIS as gis_factory
    return gis_factory("pro")
