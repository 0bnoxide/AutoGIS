from enum import Enum


class Runtime(Enum):
    CLOUD = "cloud"
    LOCAL = "local"
    HYBRID = "hybrid"


# Per MERGE_PLAN §4. Names are CLI subcommand names.
TOOLS: dict[str, Runtime] = {
    "harvest": Runtime.HYBRID,
    "inspect": Runtime.CLOUD,          # tool 1
    "parser-profile": Runtime.CLOUD,   # tool 9
    "figure-spec": Runtime.CLOUD,      # tool 10
    "import-gdb": Runtime.LOCAL,       # tool 2
    "build-event": Runtime.LOCAL,      # tool 3
    "build-callouts": Runtime.LOCAL,   # tool 4
    "gw-contours": Runtime.LOCAL,      # tool 5
    "export-figures": Runtime.LOCAL,   # tool 6
    "full-pipeline": Runtime.LOCAL,    # tool 7
    "validate-db": Runtime.LOCAL,      # tool 8
    "validate-config": Runtime.CLOUD,
    "manage-analyte-dict": Runtime.CLOUD,
    "validate-units": Runtime.CLOUD,
    "reconcile-locations": Runtime.HYBRID,
    "import-edd": Runtime.CLOUD,
    "upgrade-schema": Runtime.LOCAL,   # phase 1.4
    "optimize-callouts": Runtime.LOCAL,        # tool 5.2
    "manage-callout-overrides": Runtime.LOCAL, # tool 5.3
    "build-survey-form": Runtime.CLOUD, # tool 7.1a
    "compare-events": Runtime.CLOUD,   # tool 4.7
    "process-level-loop": Runtime.CLOUD,  # tool 8.1
}


def requires_arcpy(name: str) -> bool:
    return TOOLS[name] is Runtime.LOCAL
