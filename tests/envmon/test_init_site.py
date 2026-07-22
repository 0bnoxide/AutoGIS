"""Tests for `envmon init-site` (Phase 3 site onboarding bootstrap).

Arcpy-free. All write paths use a tmp_path --dest so nothing ever lands in the
packaged config tree.
"""
from pathlib import Path

from click.testing import CliRunner

from autogis.adapters.cli import autogis as autogis_cli
from autogis.core.common.config import FigureSpec, ParserProfile, SiteConfig
from autogis.core.envmon.init_site import (
    FAMILIES, SkeletonFile, plan_site_skeleton, scan_anchors,
    validate_skeleton, write_skeleton,
)

SITE_ID = "T99"
SITE_NAME = "Test Site 99"


def test_plan_substitutes_sentinels_and_leaves_no_residual(tmp_path):
    files = plan_site_skeleton(SITE_ID, SITE_NAME, tmp_path)
    assert len(files) == len(FAMILIES) == 4
    for sf in files:
        assert "__SITE_ID__" not in sf.text
        assert "__SITE_NAME__" not in sf.text
        assert "__SITE_ID__" not in sf.target.name
        assert SITE_ID in sf.target.name  # site id reached the filename
    # runtime {site_id} placeholder in the figure spec is preserved, not touched
    figure = next(sf for sf in files if sf.family == "figure")
    assert "{site_id}" in figure.text


def test_generated_files_pass_existing_loaders(tmp_path):
    """Pins every template as structurally valid against its real loader."""
    results = validate_skeleton(plan_site_skeleton(SITE_ID, SITE_NAME, tmp_path))
    assert all(ok for _, ok, _ in results), results
    # and directly, so a loader signature drift is obvious
    write_skeleton(plan_site_skeleton(SITE_ID, SITE_NAME, tmp_path), force=False)
    SiteConfig.load(tmp_path / "sites" / f"{SITE_ID}.yaml")
    ParserProfile.load(tmp_path / "parser_profiles" / f"{SITE_ID}_DataTables.yaml")
    FigureSpec.load(tmp_path / "figure_specs" / f"{SITE_ID}_GW_Analytical.yaml")


def test_scan_anchors_finds_todo_markers(tmp_path):
    site = next(sf for sf in plan_site_skeleton(SITE_ID, SITE_NAME, tmp_path)
               if sf.family == "site")
    anchors = scan_anchors(site.text)
    assert anchors, "site skeleton must carry _TODO anchors for the operator"
    assert all("_TODO" in line for _, line in anchors)


def test_overwrite_guard_blocks_without_force(tmp_path):
    files = plan_site_skeleton(SITE_ID, SITE_NAME, tmp_path)
    written, blocked = write_skeleton(files, force=False)
    assert len(written) == 4 and not blocked
    sentinel = (tmp_path / "sites" / f"{SITE_ID}.yaml")
    sentinel.write_text("HAND EDITED", encoding="utf-8")
    # second run without --force must NOT clobber the hand-edit
    written2, blocked2 = write_skeleton(files, force=False)
    assert sentinel in blocked2
    assert sentinel.read_text(encoding="utf-8") == "HAND EDITED"
    # with --force it overwrites
    written3, blocked3 = write_skeleton(files, force=True)
    assert sentinel in written3 and not blocked3
    assert "HAND EDITED" not in sentinel.read_text(encoding="utf-8")


def test_cli_dry_run_writes_nothing(tmp_path):
    dest = tmp_path / "cfg"
    dest.mkdir()
    result = CliRunner().invoke(autogis_cli, [
        "envmon", "init-site", "--site-id", SITE_ID, "--site-name", SITE_NAME,
        "--dest", str(dest), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert list(dest.rglob("*.yaml")) == []          # nothing written
    for fam in ("site", "event", "parser", "figure"):
        assert fam in result.output
    assert "_TODO anchor" in result.output


def test_cli_rejects_path_traversal_site_id(tmp_path):
    result = CliRunner().invoke(autogis_cli, [
        "envmon", "init-site", "--site-id", "../evil", "--site-name", "x",
        "--dest", str(tmp_path), "--dry-run"])
    assert result.exit_code != 0
    assert "site id must be" in result.output


def test_coercion_prone_site_id_stays_a_string(tmp_path):
    """A CLI-valid id like NO/on/123 must not be YAML-coerced to bool/int
    (else `SiteID = '<id>'` queries break downstream). Codex P2 finding."""
    for weird in ("NO", "on", "123", "true"):
        write_skeleton(plan_site_skeleton(weird, "X", tmp_path), force=True)
        cfg = SiteConfig.load(tmp_path / "sites" / f"{weird}.yaml")
        assert cfg.site_id == weird and isinstance(cfg.site_id, str)
        fig = FigureSpec.load(tmp_path / "figure_specs" / f"{weird}_GW_Analytical.yaml")
        assert isinstance(fig.data["site_id"], str)


def test_cli_rejects_yaml_breaking_site_name(tmp_path):
    """A site name with a double-quote, backslash, or ANY non-printable char
    (control/DEL/C1/line-separator) would produce invalid YAML and crash the
    loaders; reject them all at the boundary. Codex P2 findings (2 rounds)."""
    for bad in ('North "A" Site', "back\\slash", "ctrl\x7fdel",
                "nel\x85here", "lsep\u2028here", "para\u2029x"):
        result = CliRunner().invoke(autogis_cli, [
            "envmon", "init-site", "--site-id", SITE_ID,
            "--site-name", bad, "--dest", str(tmp_path), "--dry-run"])
        assert result.exit_code != 0, f"{bad!r} should be rejected"
        # nothing must be written for a rejected name
        assert list(tmp_path.rglob("*.yaml")) == []


def test_validate_skeleton_reports_not_raises_on_bad_yaml(tmp_path):
    """validate_skeleton must degrade a malformed file to a FAIL result, never
    let a yaml.YAMLError propagate out of the report tool."""
    bad = [SkeletonFile("site", tmp_path / "sites" / "B.yaml", "a: b: c: broken")]
    results = validate_skeleton(bad)
    assert results == [("site", False, results[0][2])]
    assert not results[0][1]  # ok is False, no exception escaped


def test_cli_write_then_blocked_exit_code(tmp_path):
    dest = tmp_path / "cfg"
    args = ["envmon", "init-site", "--site-id", SITE_ID, "--site-name",
            SITE_NAME, "--dest", str(dest)]
    first = CliRunner().invoke(autogis_cli, args)
    assert first.exit_code == 0, first.output
    assert (dest / "sites" / f"{SITE_ID}.yaml").exists()
    # re-run without --force: existing files block -> non-zero exit
    second = CliRunner().invoke(autogis_cli, args)
    assert second.exit_code == 1
    assert "not overwritten" in second.output
