# Back-compat: old flat paths now live under core.harvest.
import sys

from autogis.core.harvest import (  # noqa: F401
    harvester, download, manifest, state, templates, gis_session, models,
)

# Make the old fully-qualified module paths (e.g. ``autogis.core.models``)
# resolve to the relocated modules so existing imports keep working.
for _name, _mod in (
    ("harvester", harvester),
    ("download", download),
    ("manifest", manifest),
    ("state", state),
    ("templates", templates),
    ("gis_session", gis_session),
    ("models", models),
):
    sys.modules[f"{__name__}.{_name}"] = _mod
del _name, _mod
