"""--report is checked before any hosted AGOL write (#661, #662).

AGOL is mocked: ``agol_from_profile`` raises unless a test lets it through, so
a failing pre-check is proven to stop before authenticating.
"""
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from autogis.adapters.cli import autogis
from autogis.core.common.qa import QACollector

FIGURE_SPEC = """figure_spec_id: f1
map_type: plan
matrix: groundwater
layout_name: L
figure_title: T
output_filename_pattern: out
callout_template: c
"""


def _no_auth(*a, **kw):
    raise AssertionError("must fail before authenticating")


def _setup(tmp_path, monkeypatch, cmd):
    """Write cmd's input file; return (args before --report, input path)."""
    if cmd == "publish-dashboard":
        src = tmp_path / "dash.yaml"
        src.write_text("title: T\n", encoding="utf-8")
        args = ["--spec", str(src)]
        monkeypatch.setattr(
            "autogis.core.agol.dashboard_publish.publish_dashboard",
            lambda *a, **k: SimpleNamespace(qa=QACollector(), item_id="item-1",
                                            dashboard_json={}))
    elif cmd == "update-webmap":
        src = tmp_path / "fig.yaml"
        src.write_text(FIGURE_SPEC, encoding="utf-8")
        args = ["--webmap-item", "wm-1", "--figure-spec", str(src)]
        monkeypatch.setattr(
            "autogis.core.agol.webmap.update_webmap_from_spec",
            lambda *a, **k: SimpleNamespace(qa=QACollector()))
    else:
        src = tmp_path / "views.yaml"
        src.write_text("views:\n  - name: V\n    source_layer: L\n"
                       "    allow_fields: [A]\n", encoding="utf-8")
        args = ["--view-spec", str(src)]
        monkeypatch.setattr(
            "autogis.core.agol.hosted_views.create_stakeholder_view",
            lambda *a, **k: SimpleNamespace(qa=QACollector()))
    return args, src


def _run(cmd, args, report):
    return CliRunner().invoke(autogis, ["agol", cmd, *args, "--report", str(report)])


CMDS = ["publish-dashboard", "update-webmap", "create-views"]


@pytest.mark.parametrize("cmd", CMDS)
@pytest.mark.parametrize("make", ["dir", "under_file"])
def test_bad_report_fails_before_hosted_write(tmp_path, monkeypatch, cmd, make):
    """#661: a bad --report used to surface only after the hosted change."""
    monkeypatch.setattr("autogis.adapters.cli.agol_from_profile", _no_auth)
    args, _ = _setup(tmp_path, monkeypatch, cmd)
    blocker = tmp_path / "blocker.txt"
    blocker.write_text("x", encoding="utf-8")
    report = tmp_path / "rd.md" if make == "dir" else blocker / "rd.md"
    if make == "dir":
        report.mkdir()
    res = _run(cmd, args, report)
    assert res.exit_code == 1 and "cannot write" in res.output, res.output
    assert not isinstance(res.exception, AssertionError)


@pytest.mark.parametrize("cmd", CMDS)
def test_report_matching_input_is_refused(tmp_path, monkeypatch, cmd):
    """#662 class: the report must not overwrite the command's own input."""
    monkeypatch.setattr("autogis.adapters.cli.agol_from_profile", _no_auth)
    args, src = _setup(tmp_path, monkeypatch, cmd)
    before = src.read_text(encoding="utf-8")
    res = _run(cmd, args, src)
    assert res.exit_code == 1 and "must not overwrite an input file" in res.output, res.output
    assert src.read_text(encoding="utf-8") == before


@pytest.mark.parametrize("cmd", CMDS)
def test_empty_report_is_refused(tmp_path, monkeypatch, cmd):
    """--report "" used to skip the report silently after the hosted change."""
    monkeypatch.setattr("autogis.adapters.cli.agol_from_profile", _no_auth)
    args, _ = _setup(tmp_path, monkeypatch, cmd)
    res = _run(cmd, args, "")
    assert res.exit_code == 2 and "--report must not be empty" in res.output, res.output


@pytest.mark.parametrize("cmd", CMDS)
def test_good_report_still_written(tmp_path, monkeypatch, cmd):
    monkeypatch.setattr("autogis.adapters.cli.agol_from_profile", lambda *a, **k: object())
    args, _ = _setup(tmp_path, monkeypatch, cmd)
    report = tmp_path / "new" / "rd.md"
    res = _run(cmd, args, report)
    assert res.exit_code == 0, res.output
    assert report.is_file()


@pytest.mark.parametrize("cmd", CMDS)
def test_no_report_unchanged(tmp_path, monkeypatch, cmd):
    monkeypatch.setattr("autogis.adapters.cli.agol_from_profile", lambda *a, **k: object())
    args, _ = _setup(tmp_path, monkeypatch, cmd)
    res = CliRunner().invoke(autogis, ["agol", cmd, *args])
    assert res.exit_code == 0, res.output
