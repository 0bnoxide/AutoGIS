from autogis.runtime.capabilities import Runtime, TOOLS, requires_arcpy


def test_harvester_is_hybrid():
    assert TOOLS["harvest"] is Runtime.HYBRID


def test_local_tools_require_arcpy():
    assert requires_arcpy("import-gdb") is True
    assert requires_arcpy("harvest") is False


def test_cloud_ok_tools_do_not_require_arcpy():
    for name in ("inspect", "parser-profile", "figure-spec"):
        assert requires_arcpy(name) is False
