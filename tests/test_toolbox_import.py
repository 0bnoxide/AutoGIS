import ast
import importlib.util, pathlib

import autogis

def test_marshal_helper_importable_without_arcpy():
    # The .pyt top-level imports arcpy; the marshalling helpers must live in a
    # separately-importable module so core wiring is testable. Verify that module.
    from autogis.adapters import toolbox_core  # pure, no arcpy
    cfg = toolbox_core.build_harvest_config(directory="d", group_template="{g}",
            filename_template="{name}", url="http://x", where="1=1")
    assert cfg.layer_ref() == "http://x"


def test_redirect_only_pyt_tools_use_shared_run_recorder():
    pyt = pathlib.Path(autogis.__file__).parent / "adapters" / "toolbox.pyt"
    tree = ast.parse(pyt.read_text(encoding="utf-8"), filename=str(pyt))
    recorded = {}
    for cls in (node for node in tree.body if isinstance(node, ast.ClassDef)):
        for method in cls.body:
            if not isinstance(method, ast.FunctionDef) or method.name != "execute":
                continue
            for decorator in method.decorator_list:
                if (isinstance(decorator, ast.Call)
                        and isinstance(decorator.func, ast.Attribute)
                        and decorator.func.attr == "record_pyt_run"):
                    recorded[cls.name] = decorator.args[0].value

    assert recorded == {
        "ImportToGdb": "import-gdb",
        "BuildCurrentEvent": "build-event",
        "BuildCallouts": "build-callouts",
        "GroundwaterContours": "gw-contours",
        "ExportFigures": "export-figures",
        "FullPipeline": "full-pipeline",
        "ReconcileSampleLocations": "reconcile-locations",
        "ConditionDEM": "condition-dem",
        "CompareDroneSurfaces": "compare-drone-surfaces",
    }
