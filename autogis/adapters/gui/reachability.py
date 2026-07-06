"""Which LOCAL (arcpy) tools are *redirect-only* -- reachability policy for
the unified GUI adapter (ADR-0062).

A LOCAL tool needs arcpy, but that alone does NOT mean it runs via the CLI.
Two classes exist (verified by reading each command body in ``cli.py``):

- **class-2, executable:** guard passes under an arcgispro-py3 ``local_python``,
  then the body actually calls the core tool (``import-edd``, ``validate-db``,
  ``sync-to-gdb``, ``survey-to-well-elevation``, ...). These become runnable
  from the GUI once ``local_python`` is set.
- **class-1, redirect-only:** the body guards, then *unconditionally* raises a
  ``ClickException`` telling the user to use the ``.pyt`` toolbox (or that no
  implementation exists). Running one via ``local_python`` only ever HALTs
  with that message -- so the GUI greys it out with the reason instead.

This map is the class-1 set: space-joined command label -> human reason. It is
policy (ADR-0006 Pro-fallback tools + ADR-0039 dead ends), deliberately kept
out of ``introspect.py`` (whose docstring says the same) so introspection stays
pure. ``introspect_cli(unreachable=UNREACHABLE)`` stamps the reason onto the
matching ``CommandForm``s; ``app.py`` greys them. A workflow builder wanting to
exclude never-runnable steps can reuse the same map.

# ponytail: a hand-curated 12-entry list, not derived -- the redirect-vs-execute
# split is encoded nowhere programmatic (both classes share the same LOCAL
# Runtime + _guard call), so a curated list cross-checked against the CLI bodies
# and ADR-0006/0039 is the honest source. test_gui_reachability guards drift.
#
# export-civil3d is deliberately NOT here: its PNEZD-CSV path runs headless;
# only its --landxml leg redirects (a param-level condition the CLI's own
# ClickException handles -> a clean HALT), so the command stays reachable.
"""
from __future__ import annotations

__all__ = ["UNREACHABLE"]

# ADR-0006: tools 2-7 are Pro-only; the CLI registers them but redirects to the
# .pyt toolbox, which is their primary UI.
_PRO_ONLY = (
    "import-gdb", "build-event", "build-callouts",
    "gw-contours", "export-figures", "full-pipeline",
)
_PRO_REASON = "Runs in ArcGIS Pro only; use the .pyt toolbox (ADR-0006)."

# ADR-0039: scoped dead ends -- no standalone CLI *or* .pyt implementation.
_DEAD_END_REASON = "No standalone CLI or .pyt implementation (ADR-0039)."
_DEAD_ENDS = (
    "optimize-callouts",
    "manage-callout-overrides list",
    "manage-callout-overrides clear",
    "manage-callout-overrides lock",
    "manage-callout-overrides unlock",
)

UNREACHABLE: dict[str, str] = {
    **{f"envmon {name}": _PRO_REASON for name in _PRO_ONLY},
    **{f"envmon {name}": _DEAD_END_REASON for name in _DEAD_ENDS},
    # arcpy Export-to-CAD call not wired yet (planned) -- issue #105.
    "envmon build-cad-package":
        "CAD export (arcpy Export-to-CAD) not wired yet; see issue #105.",
}
