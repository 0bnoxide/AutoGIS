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
@pytest.mark.parametrize("make", ["dir", "under_file", "dangling_link", "link_loop",
                                  "under_dangling_link", "under_link_loop"])
def test_bad_report_fails_before_hosted_write(tmp_path, monkeypatch, cmd, make):
    """#661: a bad --report used to surface only after the hosted change."""
    import os
    monkeypatch.setattr("autogis.adapters.cli.agol_from_profile", _no_auth)
    args, _ = _setup(tmp_path, monkeypatch, cmd)
    blocker = tmp_path / "blocker.txt"
    blocker.write_text("x", encoding="utf-8")
    report = blocker / "rd.md" if make == "under_file" else tmp_path / "rd.md"
    if make == "dir":
        report.mkdir()
    elif "link" in make:
        link = tmp_path / "link"
        try:
            os.symlink(tmp_path / "nope" if "dangling" in make else link, link)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks not supported here")
        report = link if make in ("dangling_link", "link_loop") else link / "sub" / "rd.md"
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


# --- Windows-only shapes the POSIX checks missed ---------------------------
# A directory junction is not a symlink to Path.is_symlink(), so a broken one
# slipped past the dangling-link guard; names with ? or | (and the rest of
# <>:"|?*) resolve and stat as "missing" on Windows, so they passed too, and
# the write failed only after the hosted change.

def _make_broken_junction(tmp_path):
    import os
    import subprocess
    target = tmp_path / "gone"
    target.mkdir()
    junction = tmp_path / "junction"
    try:
        import _winapi
        _winapi.CreateJunction(str(target), str(junction))
    except (ImportError, AttributeError, OSError):
        subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(target)],
                       check=True, capture_output=True)
    os.rmdir(target)
    assert not junction.exists() and not junction.is_symlink()
    return junction


@pytest.mark.skipif(__import__("os").name != "nt", reason="NTFS junctions")
@pytest.mark.parametrize("cmd", CMDS)
@pytest.mark.parametrize("where", ["is_report", "is_ancestor"])
def test_broken_junction_report_fails_before_hosted_write(tmp_path, monkeypatch, cmd, where):
    monkeypatch.setattr("autogis.adapters.cli.agol_from_profile", _no_auth)
    args, _ = _setup(tmp_path, monkeypatch, cmd)
    junction = _make_broken_junction(tmp_path)
    report = junction if where == "is_report" else junction / "sub" / "rd.md"
    res = _run(cmd, args, report)
    assert res.exit_code == 1 and "cannot write" in res.output, res.output
    assert not isinstance(res.exception, AssertionError)


@pytest.mark.skipif(__import__("os").name != "nt", reason="Windows file-name rules")
@pytest.mark.parametrize("cmd", CMDS)
@pytest.mark.parametrize("name", ["rd?.md", "rd|x.md", "rd*.md", "rd<.md", 'rd".md',
                                  "rd:x.md", "bad?dir/rd.md"])
def test_windows_invalid_name_fails_before_hosted_write(tmp_path, monkeypatch, cmd, name):
    monkeypatch.setattr("autogis.adapters.cli.agol_from_profile", _no_auth)
    args, _ = _setup(tmp_path, monkeypatch, cmd)
    res = _run(cmd, args, str(tmp_path) + "\\" + name.replace("/", "\\"))
    assert res.exit_code == 1 and "cannot write" in res.output, res.output
    assert not isinstance(res.exception, AssertionError)


@pytest.mark.parametrize("where", ["is_report", "is_ancestor"])
def test_dangling_link_not_reported_as_symlink_is_refused(tmp_path, monkeypatch, where):
    """Junction semantics on any OS: lstat sees an entry, stat doesn't, and
    Path.is_symlink() says False (true of a broken NTFS junction)."""
    import os
    import click
    from pathlib import Path
    from autogis.adapters.cli import _check_report_writable
    link = tmp_path / "junction"
    try:
        os.symlink(tmp_path / "gone", link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported here")
    monkeypatch.setattr(Path, "is_symlink", lambda self: False)
    report = link if where == "is_report" else link / "sub" / "rd.md"
    with pytest.raises(click.ClickException, match="cannot write"):
        _check_report_writable(str(report))


@pytest.mark.parametrize("name", ["rd?.md", "rd|x.md", "rd*.md", "rd<.md", 'rd".md',
                                  "rd:x.md", "rd\x01.md", "bad?dir/rd.md"])
def test_windows_invalid_name_rule(tmp_path, monkeypatch, name):
    """The name rule itself, on any OS: on under Windows, off elsewhere
    (? and | are legal POSIX file names)."""
    import click
    from autogis.adapters import cli
    report = str(tmp_path / name)
    monkeypatch.setattr(cli, "_IS_WINDOWS", True)
    with pytest.raises(click.ClickException, match="not a valid Windows file name"):
        cli._check_report_writable(report)
    monkeypatch.setattr(cli, "_IS_WINDOWS", False)
    cli._check_report_writable(report)


@pytest.mark.parametrize("report", [r"C:\out\rd.md", "C:rd.md", r"\\?\C:\out\rd.md",
                                    r"\\server\share\rd.md", r"rel\rd.md"])
def test_windows_anchor_is_not_a_bad_name(report):
    """The drive colon and a long-path prefix belong to the anchor, not a name."""
    from autogis.adapters.cli import _windows_bad_name_part
    assert _windows_bad_name_part(report) is None
