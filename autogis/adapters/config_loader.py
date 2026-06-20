import yaml
from autogis.core.harvest.models import HarvestConfig

_OVERRIDE_KEYS = ("where", "directory", "incremental")


def load_config(path, overrides=None):
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    connection = data.get("connection") or {}
    layer = data.get("layer") or {}
    output = data.get("output") or {}
    options = data.get("options") or {}

    profile = connection.get("profile")

    fields = dict(
        item_id=layer.get("item_id"),
        url=layer.get("url"),
        where=layer.get("where", "1=1"),
        directory=output["directory"],
        group_template=output["group_template"],
        filename_template=output["filename_template"],
        incremental=options.get("incremental", False),
        skip_existing=options.get("skip_existing", True),
        retries=options.get("retries", 3),
        backoff_seconds=options.get("backoff_seconds", 2),
    )

    if overrides:
        for key in _OVERRIDE_KEYS:
            if overrides.get(key) is not None:
                fields[key] = overrides[key]

    if fields["where"] is None:
        fields["where"] = "1=1"

    return HarvestConfig(**fields), profile
