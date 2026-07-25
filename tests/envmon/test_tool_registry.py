"""Tests for tool_registry (Tool 10.1 ListAvailableEnvTools) — arcpy-free.

Checklist mirrors the Approved design spec
docs/superpowers/specs/2026-06-28-list-available-env-tools-design.md
"""
from autogis.core.envmon.tool_registry import (
    ToolEntry,
    get_all_tools,
    filter_tools,
    format_tool_table,
)


def test_get_all_tools_nonempty():
    tools = get_all_tools()
    assert tools
    assert all(isinstance(t, ToolEntry) for t in tools)


def test_all_entries_have_command_and_runtime():
    for t in get_all_tools():
        assert t.command, f"empty command in {t}"
        assert t.runtime in {"CLOUD", "HYBRID", "LOCAL", "DRAFT"}, t.runtime


def test_filter_by_runtime_cloud():
    tools = get_all_tools()
    cloud = filter_tools(tools, runtime="CLOUD")
    assert cloud
    assert all(t.runtime == "CLOUD" for t in cloud)
    # CLOUD subset should be smaller than the whole (there are LOCAL tools too).
    assert any(t.runtime == "LOCAL" for t in tools)


def test_filter_by_domain():
    tools = get_all_tools()
    intake = filter_tools(tools, domain="intake")
    assert intake
    assert all(t.domain == "intake" for t in intake)


def test_filter_by_search_matches_name_or_description():
    tools = get_all_tools()
    hits = filter_tools(tools, search="edd")
    assert hits
    for t in hits:
        blob = f"{t.command} {t.name} {t.description}".lower()
        assert "edd" in blob


def test_filter_no_criteria_returns_all():
    tools = get_all_tools()
    assert filter_tools(tools) == tools


def test_format_table_has_header_and_rows():
    tools = get_all_tools()
    txt = format_tool_table(tools)
    lines = txt.splitlines()
    assert "command" in lines[0]
    assert "runtime" in lines[0]
    # at least header + separator + one data row
    assert len(lines) >= 3


def test_verbose_includes_roadmap_column():
    tools = get_all_tools()
    txt = format_tool_table(tools, verbose=True)
    assert "roadmap" in txt.splitlines()[0].lower()


def test_filter_by_status():
    tools = get_all_tools()
    stable = filter_tools(tools, status="stable")
    assert stable
    assert all(t.status == "stable" for t in stable)


def test_registry_commands_exist_in_live_cli():
    """Drift guard (one-directional): every registered command must be a real
    click subcommand — bare names under `envmon`, group-qualified names
    ("agol <name>") under the `agol` group (unified discovery, ADR-0092).
    The reverse direction lives in test_capabilities.py."""
    from autogis.adapters.cli import agol, envmon
    live = set(envmon.commands.keys())
    live |= {f"agol {name}" for name in agol.commands}
    registered = {t.command for t in get_all_tools()}
    missing = sorted(registered - live)
    assert not missing, f"registry advertises non-existent commands: {missing}"
