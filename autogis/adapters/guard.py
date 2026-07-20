"""Runtime guard for the suite's adapters.

LOCAL tools (the arcpy-touching envmon tools) are *registered* in the CLI but
only *runnable* where ``arcpy`` is present (ArcGIS Pro) -- with one
exception: per ADR-0006, tools 2-8 (``import-gdb``, ``build-event``,
``build-callouts``, ``gw-contours``, ``export-figures``, ``full-pipeline``,
``validate-db``) always guard then redirect to the ``.pyt`` toolbox and never
actually execute via the CLI, even with arcpy present -- the ``.pyt`` is their
primary UI by design, not a headless-only fallback.
``require_runtime(name)`` is the single gate: it consults the capability
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
            f"Tool '{name}' needs arcpy (ArcGIS Pro). Run this CLI command "
            f"inside a cloned arcgispro-py3 env, or use the equivalent tool "
            f"in the .pyt toolbox inside Pro if one exists for it (not "
            f"every LOCAL tool has a .pyt entry -- see ADR-0006/0039).")
