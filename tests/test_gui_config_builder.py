"""Pure-logic tests for the Site Config Builder (ADR-0064).

No Qt, no network: dict assembly, validation-reuse through
``HarvestConfig.load`` (never a re-derived copy of its rules), YAML
round-tripping, and the sublayer -> dropdown-entry mapping whose ``url``
feeds ``layer.url``.
"""
from types import SimpleNamespace

import pytest

from autogis.adapters.gui.config_builder import (
    SublayerEntry, build_config, sublayer_entries, validate_config,
    write_config,
)
from autogis.core.common.config import ConfigError, HarvestConfig


def _valid_kwargs(**overrides):
    kw = dict(
        profile="corp",
        item_id="abc123",
        url="",
        where="Status = 'Open'",
        directory="C:/harvest/out",
        group_template="{OBJECTID}",
        filename_template="{OBJECTID}_{name}",
        incremental=False,
        skip_existing=True,
        retries=3,
        backoff_seconds=2.0,
    )
    kw.update(overrides)
    return kw


# --- build_config -----------------------------------------------------------

def test_build_config_assembles_nested_sections():
    cfg = build_config(**_valid_kwargs())
    assert cfg["connection"] == {"profile": "corp"}
    assert cfg["layer"] == {"item_id": "abc123", "where": "Status = 'Open'"}
    assert cfg["output"] == {
        "directory": "C:/harvest/out",
        "group_template": "{OBJECTID}",
        "filename_template": "{OBJECTID}_{name}",
    }
    assert cfg["options"] == {
        "incremental": False, "skip_existing": True,
        "retries": 3, "backoff_seconds": 2.0,
    }


def test_build_config_omits_blank_optionals():
    cfg = build_config(**_valid_kwargs(profile="  ", where=""))
    assert "connection" not in cfg     # blank profile -> anonymous
    assert "where" not in cfg["layer"]  # blank where -> load()'s "1=1" default


def test_build_config_omits_blank_output_keys_so_require_catches_them():
    # A blank directory must be MISSING, not "", or _require would pass it.
    cfg = build_config(**_valid_kwargs(directory="   "))
    assert "directory" not in cfg["output"]


def test_build_config_url_goes_into_layer_url():
    url = "https://services.arcgis.com/x/FeatureServer/5"
    cfg = build_config(**_valid_kwargs(item_id="", url=url))
    assert cfg["layer"]["url"] == url
    assert "item_id" not in cfg["layer"]


# --- validate_config: reuses HarvestConfig.load, no second rulebook ---------

def test_validate_config_accepts_a_valid_dict():
    validate_config(build_config(**_valid_kwargs()))  # must not raise


def test_validate_config_rejects_missing_output_keys():
    cfg = build_config(**_valid_kwargs(directory=""))
    with pytest.raises(ConfigError, match="directory"):
        validate_config(cfg)


def test_validate_config_rejects_both_item_id_and_url():
    cfg = build_config(**_valid_kwargs(url="https://x/FeatureServer/0"))
    with pytest.raises(ConfigError, match="exactly one"):
        validate_config(cfg)


def test_validate_config_rejects_neither_item_id_nor_url():
    cfg = build_config(**_valid_kwargs(item_id="", url=""))
    with pytest.raises(ConfigError, match="exactly one"):
        validate_config(cfg)


# --- write_config -----------------------------------------------------------

def test_write_config_round_trips_through_harvest_config(tmp_path):
    path = tmp_path / "config.yaml"
    write_config(build_config(**_valid_kwargs()), path)
    loaded = HarvestConfig.load(path)
    assert loaded.item_id == "abc123"
    assert loaded.url is None
    assert loaded.where == "Status = 'Open'"
    assert loaded.directory == "C:/harvest/out"
    assert loaded.group_template == "{OBJECTID}"
    assert loaded.filename_template == "{OBJECTID}_{name}"
    assert loaded.incremental is False
    assert loaded.skip_existing is True
    assert loaded.retries == 3
    assert loaded.backoff_seconds == 2.0


def test_write_config_writes_nothing_when_invalid(tmp_path):
    path = tmp_path / "config.yaml"
    with pytest.raises(ConfigError):
        write_config(build_config(**_valid_kwargs(directory="")), path)
    assert not path.exists()


# --- sublayer_entries --------------------------------------------------------

def _sub(idx, name, url, has_attachments):
    return SimpleNamespace(
        url=url,
        properties=SimpleNamespace(id=idx, name=name,
                                   hasAttachments=has_attachments))


def _fake_item():
    return SimpleNamespace(
        layers=[
            _sub(0, "Boundaries", "https://x/FeatureServer/0", False),
            _sub(1, "Analytical_Locations", "https://x/FeatureServer/1", True),
        ],
        tables=[
            _sub(5, "Daily_Diary_Photos", "https://x/FeatureServer/5", True),
        ],
    )


def test_sublayer_entries_labels_and_urls():
    entries = sublayer_entries(_fake_item())
    by_url = {e.url: e for e in entries}
    assert by_url["https://x/FeatureServer/1"].label == \
        "1 — Analytical_Locations (Layer, has attachments)"
    assert by_url["https://x/FeatureServer/5"].label == \
        "5 — Daily_Diary_Photos (Table, has attachments)"
    assert by_url["https://x/FeatureServer/0"].label == \
        "0 — Boundaries (Layer, no attachments)"


def test_sublayer_entries_attachment_bearing_first_others_kept():
    entries = sublayer_entries(_fake_item())
    assert [e.has_attachments for e in entries] == [True, True, False]
    assert len(entries) == 3  # attachment-less ones stay visible


def test_sublayer_entries_handles_none_layers_or_tables():
    # arcgis returns None (not []) for an item with no tables; the
    # dashboard_refresh convention `list(x or [])` must be preserved.
    item = SimpleNamespace(layers=None,
                           tables=[_sub(0, "T", "https://x/FS/0", False)])
    assert [e.url for e in sublayer_entries(item)] == ["https://x/FS/0"]


def test_sublayer_entries_missing_has_attachments_defaults_false():
    item = SimpleNamespace(
        layers=[SimpleNamespace(url="https://x/FS/0",
                                properties=SimpleNamespace(id=0, name="L"))],
        tables=None)
    (entry,) = sublayer_entries(item)
    assert entry.has_attachments is False
    assert "no attachments" in entry.label


def test_sublayer_entry_is_plain_data():
    e = SublayerEntry(label="x", url="u", has_attachments=True)
    assert (e.label, e.url, e.has_attachments) == ("x", "u", True)
