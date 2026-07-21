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
        "RunGWModelPipeline": "run-gw-model-pipeline",
        "BuildConcentrationSurface": "build-conc-surface",
        "ExportFigures": "export-figures",
        "FullPipeline": "full-pipeline",
        "ReconcileSampleLocations": "reconcile-locations",
        "ConditionDEM": "condition-dem",
        "CompareDroneSurfaces": "compare-drone-surfaces",
        "ExportContoursForCivil3D": "export-civil3d",
        "BuildCADExportPackage": "build-cad-package",
    }


# Deprecated (since Pro 3.2) arcpy conversion tools -> current replacement,
# per the #214 audit cited in ADR-0077.
_DEPRECATED_ARCPY_CALLS = {
    "TableToTable": "arcpy.conversion.ExportTable",
    "FeatureClassToFeatureClass": "arcpy.conversion.ExportFeatures",
}


def _autogis_source_files():
    root = pathlib.Path(autogis.__file__).parent
    yield from root.glob("**/*.py")
    yield root / "adapters" / "toolbox.pyt"


def test_no_deprecated_arcpy_tool_names():
    # Regression guard for ADR-0077 / issue #272 option 5: a static, arcpy-free
    # deny-list check so a reintroduced deprecated call fails the headless
    # suite instead of only surfacing in a live Pro session.
    offenders = []
    for path in _autogis_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in _DEPRECATED_ARCPY_CALLS:
                offenders.append(
                    f"{path}:{node.lineno} uses {node.attr} -- use "
                    f"{_DEPRECATED_ARCPY_CALLS[node.attr]} instead")
    assert not offenders, "\n".join(offenders)


def test_pyt_valuelist_domains_have_no_empty_strings():
    # Regression guard for issue #214 (fixed by PR #216): arcpy's ValueList
    # FilterObject rejects "" in a Parameter's domain, which crashes the tool
    # dialog before execute() ever runs. Static, arcpy-free.
    pyt = pathlib.Path(autogis.__file__).parent / "adapters" / "toolbox.pyt"
    tree = ast.parse(pyt.read_text(encoding="utf-8"), filename=str(pyt))
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg != "domain" or not isinstance(kw.value, (ast.Tuple, ast.List)):
                continue
            for elt in kw.value.elts:
                if isinstance(elt, ast.Constant) and elt.value == "":
                    offenders.append(f"{pyt}:{elt.lineno} empty string in domain=")
    assert not offenders, "\n".join(offenders)
