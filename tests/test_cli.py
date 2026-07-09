import yaml
import pytest
from autogis.adapters.cli import run
from autogis.core.harvest.models import RunSummary


def _write_config(tmp_path, extra=None):
    cfg = {
        "connection": {"profile": "myprofile"},
        "layer": {"item_id": "abc123"},
        "output": {
            "directory": str(tmp_path / "out"),
            "group_template": "{Status}",
            "filename_template": "{OBJECTID}_{name}",
        },
        "options": {},
    }
    if extra:
        cfg.update(extra)
    p = tmp_path / "harvest.yaml"
    p.write_text(yaml.dump(cfg))
    return str(p)


def test_load_layer_index_defaults_to_zero(tmp_path):
    from pathlib import Path
    from autogis.core.models import HarvestConfig
    cfg = HarvestConfig.load(Path(_write_config(tmp_path)))
    assert cfg.layer_index == 0


def test_load_layer_index_round_trips_from_yaml(tmp_path):
    from pathlib import Path
    from autogis.core.models import HarvestConfig
    config_path = _write_config(
        tmp_path, extra={"layer": {"item_id": "abc123", "layer_index": 5}})
    cfg = HarvestConfig.load(Path(config_path))
    assert cfg.layer_index == 5


def test_load_all_sublayers_round_trips_from_yaml(tmp_path):
    from pathlib import Path
    from autogis.core.models import HarvestConfig
    config_path = _write_config(
        tmp_path, extra={"layer": {"item_id": "abc123", "all_sublayers": True}})
    cfg = HarvestConfig.load(Path(config_path))
    assert cfg.all_sublayers is True


def test_load_all_sublayers_requires_item_id_not_url(tmp_path):
    from pathlib import Path
    from autogis.core.common.config import ConfigError
    from autogis.core.models import HarvestConfig
    config_path = _write_config(tmp_path, extra={
        "layer": {"url": "https://x/FeatureServer/0", "all_sublayers": True}})
    with pytest.raises(ConfigError, match="all_sublayers requires item_id"):
        HarvestConfig.load(Path(config_path))


def test_load_all_sublayers_rejects_explicit_layer_index(tmp_path):
    from pathlib import Path
    from autogis.core.common.config import ConfigError
    from autogis.core.models import HarvestConfig
    config_path = _write_config(tmp_path, extra={
        "layer": {"item_id": "abc123", "all_sublayers": True, "layer_index": 2}})
    with pytest.raises(ConfigError, match="mutually exclusive"):
        HarvestConfig.load(Path(config_path))


def test_load_all_sublayers_rejects_incremental(tmp_path):
    from pathlib import Path
    from autogis.core.common.config import ConfigError
    from autogis.core.models import HarvestConfig
    config_path = _write_config(tmp_path, extra={
        "layer": {"item_id": "abc123", "all_sublayers": True},
        "options": {"incremental": True}})
    with pytest.raises(ConfigError, match="cannot be combined with incremental"):
        HarvestConfig.load(Path(config_path))


def test_run_loads_config_and_calls_harvest(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path)
    captured = {}

    def fake_harvest(gis, config):
        captured["gis"] = gis
        captured["config"] = config
        return RunSummary(downloaded=1, skipped=0, failed=0)

    monkeypatch.setattr(
        "autogis.adapters.cli.agol_from_profile",
        lambda profile=None, **kw: f"GIS({profile})"
    )

    run(config_path, where=None, out=None, incremental=None,
        harvest_fn=fake_harvest)

    assert captured["gis"] == "GIS(myprofile)"
    assert captured["config"].item_id == "abc123"


def test_run_applies_cli_overrides(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path)
    captured = {}

    def fake_harvest(gis, config):
        captured["config"] = config
        return RunSummary()

    monkeypatch.setattr(
        "autogis.adapters.cli.agol_from_profile",
        lambda profile=None, **kw: None
    )

    run(config_path, where="Status='Done'", out=str(tmp_path / "override"),
        incremental=True, harvest_fn=fake_harvest)

    assert captured["config"].where == "Status='Done'"
    assert captured["config"].directory == str(tmp_path / "override")
    assert captured["config"].incremental is True


def test_run_none_overrides_ignored(tmp_path, monkeypatch):
    config_path = _write_config(tmp_path)
    captured = {}

    def fake_harvest(gis, config):
        captured["config"] = config
        return RunSummary()

    monkeypatch.setattr(
        "autogis.adapters.cli.agol_from_profile",
        lambda profile=None, **kw: None
    )

    run(config_path, where=None, out=None, incremental=None,
        harvest_fn=fake_harvest)

    assert captured["config"].where == "1=1"


def test_run_echo_output(tmp_path, monkeypatch, capsys):
    config_path = _write_config(tmp_path)

    monkeypatch.setattr(
        "autogis.adapters.cli.agol_from_profile",
        lambda profile=None, **kw: None
    )

    run(config_path, where=None, out=None, incremental=None,
        harvest_fn=lambda gis, cfg: RunSummary(downloaded=3, skipped=1, failed=2))

    out = capsys.readouterr().out
    assert "Downloaded: 3" in out
    assert "Skipped: 1" in out
    assert "Failed: 2" in out
