import importlib.util, pathlib

def test_marshal_helper_importable_without_arcpy():
    # The .pyt top-level imports arcpy; the marshalling helpers must live in a
    # separately-importable module so core wiring is testable. Verify that module.
    from autogis.adapters import toolbox_core  # pure, no arcpy
    cfg = toolbox_core.build_harvest_config(directory="d", group_template="{g}",
            filename_template="{name}", url="http://x", where="1=1")
    assert cfg.layer_ref() == "http://x"
