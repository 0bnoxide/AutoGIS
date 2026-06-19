import textwrap
from autogis.adapters.config_loader import load_config


def _write(tmp_path, body):
    p = tmp_path / "job.yaml"
    p.write_text(textwrap.dedent(body))
    return str(p)


def test_load_basic(tmp_path):
    path = _write(tmp_path, """
        connection:
          profile: prof1
        layer:
          item_id: "abc"
          where: "Status = 'Done'"
        output:
          directory: "./out"
          group_template: "{Status}"
          filename_template: "{OBJECTID}_{name}"
        options:
          retries: 5
    """)
    cfg, profile = load_config(path)
    assert profile == "prof1"
    assert cfg.item_id == "abc"
    assert cfg.where == "Status = 'Done'"
    assert cfg.directory == "./out"
    assert cfg.retries == 5
    assert cfg.skip_existing is True   # default applied


def test_defaults_when_options_absent(tmp_path):
    path = _write(tmp_path, """
        connection: {}
        layer:
          url: "http://x/0"
        output:
          directory: "./out"
          group_template: "{S}"
          filename_template: "{OBJECTID}"
    """)
    cfg, profile = load_config(path)
    assert profile is None
    assert cfg.where == "1=1"
    assert cfg.incremental is False
    assert cfg.retries == 3


def test_overrides_applied(tmp_path):
    path = _write(tmp_path, """
        connection:
          profile: prof1
        layer:
          item_id: "abc"
        output:
          directory: "./out"
          group_template: "{S}"
          filename_template: "{OBJECTID}"
    """)
    cfg, _ = load_config(path, overrides={
        "where": "OBJECTID < 100", "directory": "/tmp/o", "incremental": True})
    assert cfg.where == "OBJECTID < 100"
    assert cfg.directory == "/tmp/o"
    assert cfg.incremental is True


def test_none_overrides_ignored(tmp_path):
    path = _write(tmp_path, """
        connection:
          profile: prof1
        layer:
          item_id: "abc"
          where: "keep"
        output:
          directory: "./out"
          group_template: "{S}"
          filename_template: "{OBJECTID}"
    """)
    cfg, _ = load_config(path, overrides={
        "where": None, "directory": None, "incremental": None})
    assert cfg.where == "keep"
    assert cfg.directory == "./out"
