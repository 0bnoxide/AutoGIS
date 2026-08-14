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


def _profile_is_complete(section) -> bool:
    """True when a ``.arcgisprofile`` section names a usable login.

    ArcGIS API for Python persists "any combination of" ``url``, ``username``,
    ``key_file``, ``cert_file`` and ``client_id`` in this file; the password,
    when there is one, lives in the OS keyring. So ``url`` + ``username`` is
    only *one* of the modes ``GIS(profile=...)`` accepts -- a PKI profile
    (``key_file`` + ``cert_file``) or an OAuth one (``client_id``) carries no
    username at all, and requiring one hid those profiles from the dropdown
    entirely (#493). ``url`` alone still fails: that is the half-written
    section a failed ``store_credential`` leaves behind, with nothing to log
    in with.

    Ref: developers.arcgis.com "Working with different authentication
    schemes" -> Storing your credentials locally.
    """
    if not section.get("url"):
        return False
    return bool(section.get("username")
                or (section.get("key_file") and section.get("cert_file"))
                or section.get("client_id"))


def list_connection_profiles(path=None):
    """Sorted names of *complete* ArcGIS API for Python connection profiles.

    Reads ``~/.arcgisprofile`` (the ProfileManager store) and returns the
    names of profiles that carry a ``url`` plus credentials for one of the
    supported authentication modes -- skipping the half-written sections a
    failed ``store_credential`` leaves behind. arcgis-free: plain stdlib
    ``configparser``, no ``arcgis`` import, so adapters can offer a profile
    dropdown without the heavy dependency (the password still lives in the OS
    keyring, keyed by name -- not read here).

    Fail-open: a missing or corrupt profile file yields ``[]`` rather than
    raising, so this is safe to call at CLI import time without risking the
    whole CLI over a malformed dotfile.
    """
    import configparser
    from pathlib import Path

    # interpolation=None: profile URLs legitimately contain '%' (percent-
    # encoding), which ConfigParser's default interpolation would choke on --
    # and it fires lazily at .get() time, outside any read() guard. Disable it.
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    try:
        # Path.home() is inside the guard too: it raises RuntimeError under a
        # service/container account with no resolvable home dir.
        profile_file = Path(path) if path else Path.home() / ".arcgisprofile"
        parser.read(profile_file, encoding="utf-8")
        return sorted(
            {name.strip() for name, section in parser.items()
             if name != parser.default_section and _profile_is_complete(section)}
        )
    except (configparser.Error, OSError, ValueError, RuntimeError):
        # Fail-open: a missing / corrupt / mis-encoded dotfile, or an
        # unresolvable home dir, must never break the CLI (this runs at import
        # time). UnicodeDecodeError is a ValueError; OSError covers an
        # unreadable file; RuntimeError covers Path.home() failing.
        return []


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
