from autogis.core.models import HarvestConfig, RunSummary
from autogis.adapters import cli


def test_run_wires_components(tmp_path, capsys):
    captured = {}

    def fake_load(path, overrides=None):
        captured["overrides"] = overrides
        cfg = HarvestConfig(item_id="abc", url=None, directory=str(tmp_path),
                            group_template="{S}", filename_template="{OBJECTID}")
        return cfg, "prof1"

    def fake_gis_builder(profile):
        captured["profile"] = profile
        return "GIS_OBJ"

    def fake_harvest(gis, cfg):
        captured["gis"] = gis
        captured["cfg"] = cfg
        s = RunSummary(downloaded=3, skipped=1, failed=2)
        return s

    summary = cli.run("job.yaml", where="W", out="/o", incremental=True,
                      gis_builder=fake_gis_builder, harvest_fn=fake_harvest,
                      load_fn=fake_load)

    assert captured["overrides"] == {"where": "W", "directory": "/o",
                                     "incremental": True}
    assert captured["profile"] == "prof1"
    assert captured["gis"] == "GIS_OBJ"
    assert summary.downloaded == 3
    out = capsys.readouterr().out
    assert "Downloaded: 3" in out
    assert "Skipped: 1" in out
    assert "Failed: 2" in out
