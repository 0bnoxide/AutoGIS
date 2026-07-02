from autogis.runtime.capabilities import Runtime, TOOLS, _REGISTRY_SEED, requires_arcpy


def test_harvester_is_hybrid():
    assert TOOLS["harvest"] is Runtime.HYBRID


def test_local_tools_require_arcpy():
    assert requires_arcpy("import-gdb") is True
    assert requires_arcpy("harvest") is False


def test_cloud_ok_tools_do_not_require_arcpy():
    for name in ("inspect", "parser-profile", "figure-spec"):
        assert requires_arcpy(name) is False


# ---------------------------------------------------------------------------
# Registration-drift guard (issue #106/H3): a tool can exist in up to four
# hand-maintained places (click command, TOOLS guard registry, discovery
# _REGISTRY_SEED, .pyt). Nothing checked agreement, so batches routinely
# forgot the discovery registry (issue #98). These two tests turn that
# per-batch memory obligation into CI.
# ---------------------------------------------------------------------------

def test_every_envmon_command_registered_for_discovery():
    """Every live envmon click command has a capabilities._REGISTRY_SEED
    entry -- otherwise it's invisible to `envmon list-tools`."""
    from autogis.adapters.cli import envmon

    registered = {command for (command, *_rest) in _REGISTRY_SEED}
    live = set(envmon.commands.keys())
    missing = sorted(live - registered)
    assert not missing, (
        f"envmon commands missing from capabilities._REGISTRY_SEED "
        f"(invisible to `envmon list-tools`): {missing}")


def test_every_guarded_command_is_in_tools():
    """Every name passed to cli._guard(...) must resolve in capabilities.TOOLS,
    or the guard raises a KeyError at runtime instead of a clean click error
    (the exact failure class behind issue #62)."""
    import inspect
    import re

    from autogis.adapters import cli

    guarded = set(re.findall(r'_guard\("([^"]+)"\)', inspect.getsource(cli)))
    assert guarded, "expected at least one _guard(...) call in cli.py"
    missing = sorted(name for name in guarded if name not in TOOLS)
    assert not missing, (
        f"names passed to _guard() missing from capabilities.TOOLS: {missing}")
