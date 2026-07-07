"""Pure logic for the Site Config Builder dialog (ADR-0064).

Builds, validates, and serializes a harvest-job ``config.yaml`` from plain
form values, and maps an AGOL item's sublayers to dropdown entries whose
``url`` slots straight into ``layer.url``. No PySide6 import — the Qt glue
lives in ``config_builder_dialog.py``, matching the existing split between
``forms.py``/``introspect.py`` (logic) and ``app.py`` (widgets).

Validation is deliberately NOT re-derived here: :func:`validate_config`
round-trips the assembled dict through :meth:`HarvestConfig.load` — the
single validation source for the url-XOR-item_id invariant and the required
output keys — so the dialog can never drift from what the harvester itself
accepts.
"""
from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from autogis.core.common.config import ConfigError, HarvestConfig

__all__ = [
    "SublayerEntry",
    "build_config",
    "fetch_sublayers",
    "sublayer_entries",
    "validate_config",
    "write_config",
]


def build_config(*, profile: str = "", item_id: str = "", url: str = "",
                 where: str = "", directory: str = "",
                 group_template: str = "", filename_template: str = "",
                 incremental: bool = False, skip_existing: bool = True,
                 retries: int = 3, backoff_seconds: float = 2.0) -> dict:
    """Assemble the nested config dict from raw form values.

    Blank strings are OMITTED rather than written as ``""`` so that
    ``HarvestConfig.load`` sees them as truly missing — its ``_require``
    check and the url-XOR-item_id invariant then report them properly
    instead of accepting an empty-string value.
    """
    layer: dict = {}
    if item_id.strip():
        layer["item_id"] = item_id.strip()
    if url.strip():
        layer["url"] = url.strip()
    if where.strip():
        layer["where"] = where.strip()

    output: dict = {}
    if directory.strip():
        output["directory"] = directory.strip()
    if group_template.strip():
        output["group_template"] = group_template.strip()
    if filename_template.strip():
        output["filename_template"] = filename_template.strip()

    config: dict = {
        "layer": layer,
        "output": output,
        "options": {
            "incremental": bool(incremental),
            "skip_existing": bool(skip_existing),
            "retries": int(retries),
            "backoff_seconds": float(backoff_seconds),
        },
    }
    if profile.strip():
        config = {"connection": {"profile": profile.strip()}, **config}
    return config


def _dump_yaml(config: dict) -> str:
    import yaml  # same lazy-import stance as load_config's reader

    return yaml.safe_dump(config, sort_keys=False, allow_unicode=True)


def validate_config(config: dict) -> None:
    """Raise :class:`ConfigError` if ``config`` would be rejected by the
    harvester. Round-trips through :meth:`HarvestConfig.load` on a temp file
    so the rules (required output keys, url XOR item_id) stay single-sourced
    in ``core/common/config.py``."""
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "config.yaml"
        path.write_text(_dump_yaml(config), encoding="utf-8")
        HarvestConfig.load(path)


def write_config(config: dict, path: Path) -> None:
    """Validate ``config`` then write it to ``path`` as YAML. Nothing is
    written if validation fails."""
    validate_config(config)
    Path(path).write_text(_dump_yaml(config), encoding="utf-8")


@dataclass(frozen=True)
class SublayerEntry:
    """One layer/table of an AGOL item, ready for a dropdown: a plain-
    language ``label`` and the resolved REST ``url`` that goes into
    ``layer.url`` when picked."""

    label: str
    url: str
    has_attachments: bool


def sublayer_entries(item) -> list[SublayerEntry]:
    """Map an AGOL item's layers + tables to dropdown entries,
    attachment-bearing ones first (stable within each group) so the usual
    harvest target is easy to spot — the rest stay visible for reference.

    Same combined-list convention as ``core/agol/dashboard_refresh.py``:
    ``list(item.layers or []) + list(item.tables or [])``.
    """
    entries: list[SublayerEntry] = []
    for kind, subs in (("Layer", list(item.layers or [])),
                       ("Table", list(item.tables or []))):
        for sub in subs:
            props = sub.properties
            has = bool(getattr(props, "hasAttachments", False))
            note = "has attachments" if has else "no attachments"
            entries.append(SublayerEntry(
                label=f"{props.id} — {props.name} ({kind}, {note})",
                url=sub.url,
                has_attachments=has,
            ))
    entries.sort(key=lambda e: not e.has_attachments)  # stable: sorted() is
    return entries


def fetch_sublayers(profile: str, item_id: str) -> list[SublayerEntry]:
    """Connect to AGOL/Portal and list ``item_id``'s layers and tables.

    Network + arcgis seam: imported lazily (adapters must stay importable
    without ``arcgis``) and stubbed in tests, like ``_pick_path``'s native
    dialog. Raises ``LookupError`` when the item doesn't exist; auth/network
    failures propagate as whatever ``arcgis`` raises — the dialog reports
    either inline.
    """
    from arcgis.gis import GIS  # lazy: adapters import without arcgis

    gis = GIS(profile=profile.strip()) if profile.strip() else GIS()
    item = gis.content.get(item_id.strip())
    if item is None:
        raise LookupError(
            f"No AGOL item found with ID {item_id.strip()!r} "
            f"(check the ID and that the profile can see it)")
    return sublayer_entries(item)
