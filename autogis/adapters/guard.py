"""Runtime guard for the suite's adapters.

LOCAL tools (the 7 arcpy-touching envmon tools) are *registered* in both the
CLI and the ``.pyt`` but only *runnable* where ``arcpy`` is present (ArcGIS
Pro). ``require_runtime(name)`` is the single gate: it consults the capability
registry (``runtime.capabilities.requires_arcpy``) and, for a LOCAL tool with
no arcpy on the path, raises a clear ``RuntimeUnavailable`` instead of letting
a deep ``import arcpy`` blow up with a traceback. CLOUD/HYBRID tools pass
through untouched.
"""
from autogis.runtime.capabilities import requires_arcpy


class RuntimeUnavailable(RuntimeError):
    """A tool's required runtime (arcpy/ArcGIS Pro) is not available here."""


def _arcpy_present() -> bool:
    try:
        import arcpy  # noqa: F401
        return True
    except Exception:
        return False


def require_runtime(name: str) -> None:
    if requires_arcpy(name) and not _arcpy_present():
        raise RuntimeUnavailable(
            f"Tool '{name}' needs arcpy (ArcGIS Pro). Run it in the .pyt "
            f"toolbox inside Pro, or install into a cloned arcgispro-py3 env.")
