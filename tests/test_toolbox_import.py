import ast
import importlib.util, json, pathlib
from types import SimpleNamespace

import autogis
import click
import pytest


def _load_pyt_class(name):
    """Load one .pyt class without importing the arcpy-only module."""
    pyt = pathlib.Path(autogis.__file__).parent / "adapters" / "toolbox.pyt"
    tree = ast.parse(pyt.read_text(encoding="utf-8"), filename=str(pyt))
    cls = next(node for node in tree.body
               if isinstance(node, ast.ClassDef) and node.name == name)
    module = ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[]))
    namespace = {
        "json": json,
        "Path": pathlib.Path,
        "arcpy": SimpleNamespace(
            env=SimpleNamespace(workspace=r"C:\data\site.gdb"),
            ExecuteError=RuntimeError),
        "SiteConfig": SimpleNamespace(load=lambda path: object()),
        "ParserProfile": SimpleNamespace(load=lambda path: object()),
        "toolbox_core": SimpleNamespace(
            record_pyt_run=lambda *args, **kwargs: lambda func: func),
    }
    exec(compile(module, str(pyt), "exec"), namespace)
    return namespace[name]


def test_import_to_gdb_raises_when_summary_fails(monkeypatch):
    from autogis.adapters import guard
    from autogis.core.envmon import import_to_gdb

    monkeypatch.setattr(guard, "require_runtime", lambda tool: None)
    monkeypatch.setattr(
        import_to_gdb, "run_import",
        lambda **kwargs: {"qa_status": "FAIL", "counts_parsed": {}})
    params = [
        SimpleNamespace(name=name, valueAsText="x", value=False)
        for name in (
            "workbook", "gdb", "site_config", "parser_profile",
            "analyte_dictionary", "screening_levels", "qa_output_dir", "mode",
            "matrix_filter", "batch_id_to_replace", "event_date",
            "allow_duplicates", "allow_errors",
        )
    ]

    class Messages:
        def __init__(self):
            self.errors = []

        def addMessage(self, message):
            pass

        def addErrorMessage(self, message):
            self.errors.append(message)

    messages = Messages()
    with pytest.raises(RuntimeError):
        _load_pyt_class("ImportToGdb")().execute(params, messages)

    assert messages.errors


class _FakeParameter:
    def __init__(self, name, value=""):
        self.name = name
        self.valueAsText = value
        self.message = ""

    def setErrorMessage(self, message):
        self.message = message

    def clearMessage(self):
        self.message = ""


def test_compare_drone_surfaces_preflight_rejects_output_input_collision(
        monkeypatch):
    """The GP Output must be blocked before ArcGIS can delete an input."""
    from autogis.core.envmon import compare_drone_surfaces as compare

    paths = {
        "primary": r"C:\data\site.gdb\dem_a",
        "baseline": r"C:\data\site.gdb\dem_b",
    }
    monkeypatch.setattr(
        compare, "_product_path", lambda _gdb, product_id: paths[product_id])
    parameters = [
        _FakeParameter("gdb", r"C:\data\site.gdb"),
        _FakeParameter("primary_product_id", "primary"),
        _FakeParameter("baseline_product_id", "baseline"),
        _FakeParameter("baseline_landxml"),
        _FakeParameter("diff_raster_out", "dem_a"),
    ]

    tool = _load_pyt_class("CompareDroneSurfaces")()
    tool.updateMessages(parameters)

    output = next(p for p in parameters if p.name == "diff_raster_out")
    assert "input DEM" in output.message

    output.valueAsText = r"C:\data\site.gdb\diff"
    tool.updateMessages(parameters)
    assert output.message == ""

    def fail_lookup(_gdb, _product_id):
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr(compare, "_product_path", fail_lookup)
    tool.updateMessages(parameters)
    assert "registry unavailable" in output.message

def test_marshal_helper_importable_without_arcpy():
    # The .pyt top-level imports arcpy; the marshalling helpers must live in a
    # separately-importable module so core wiring is testable. Verify that module.
    from autogis.adapters import toolbox_core  # pure, no arcpy
    cfg = toolbox_core.build_harvest_config(directory="d", group_template="{g}",
            filename_template="{name}", url="http://x", where="1=1")
    assert cfg.layer_ref() == "http://x"


def _pyt_run_recorders() -> tuple[set[str], dict[str, str]]:
    """(tool classes that define execute(), {class: recorded tool name})."""
    pyt = pathlib.Path(autogis.__file__).parent / "adapters" / "toolbox.pyt"
    tree = ast.parse(pyt.read_text(encoding="utf-8"), filename=str(pyt))
    tools, recorded = set(), {}
    for cls in (node for node in tree.body if isinstance(node, ast.ClassDef)):
        for method in cls.body:
            if not isinstance(method, ast.FunctionDef) or method.name != "execute":
                continue
            tools.add(cls.name)
            for decorator in method.decorator_list:
                if (isinstance(decorator, ast.Call)
                        and isinstance(decorator.func, ast.Attribute)
                        and decorator.func.attr == "record_pyt_run"):
                    recorded[cls.name] = decorator.args[0].value
    return tools, recorded


def test_every_pyt_tool_execute_uses_shared_run_recorder():
    """ADR-0068 item 2: every `.pyt` execute() records its run.

    Was an exact-match allowlist, which froze a snapshot rather than the rule
    — five tools shipped undecorated and the assertion happily agreed with
    them (#447). Stated as the invariant, a new tool without the decorator
    now fails here instead of going silently unrecorded in Pro.
    """
    tools, recorded = _pyt_run_recorders()
    assert tools, "no .pyt tool classes found — parser broken, not the toolbox"
    missing = sorted(tools - set(recorded))
    assert not missing, (
        f".pyt tools whose execute() has no @toolbox_core.record_pyt_run, so "
        f"their Pro runs are invisible to evaluate-readiness/portfolio-"
        f"metrics: {missing}")


def test_pyt_recorded_tool_names_are_live_cli_commands():
    """A recorded name that doesn't match a CLI subcommand splits one tool's
    run history in two, which readiness reads as "never run"."""
    from autogis.adapters import cli

    live: set[str] = set()

    def walk(group):
        for name, cmd in group.commands.items():
            live.add(name)
            if isinstance(cmd, click.Group):
                walk(cmd)

    walk(cli.autogis)
    _tools, recorded = _pyt_run_recorders()
    ghosts = sorted({n for n in recorded.values() if n not in live})
    assert not ghosts, (
        f"record_pyt_run names with no matching CLI subcommand: {ghosts}")


def test_groundwater_approval_tool_is_registered():
    pyt = pathlib.Path(autogis.__file__).parent / "adapters" / "toolbox.pyt"
    tree = ast.parse(pyt.read_text(encoding="utf-8"), filename=str(pyt))
    toolbox = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "Toolbox")
    init = next(
        node for node in toolbox.body
        if isinstance(node, ast.FunctionDef) and node.name == "__init__")
    tools = next(
        node.value for node in ast.walk(init)
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Attribute) and t.attr == "tools"
                for t in node.targets))
    assert "ApproveGWModel" in [
        elt.id for elt in tools.elts if isinstance(elt, ast.Name)]


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


# ArcGIS Pro GUI extent labels that are NOT valid scripting keywords -> the
# keyword to use. This is the #174 defect class (ADR-0077): PR #174 shipped
# `extent="INTERSECTION"`, which arcpy rejects -- the only scripting keywords
# are MAXOF/MINOF ("Intersection of Inputs"/"Union of Inputs" are dialog labels).
# Doc-verified against the Extent environment reference:
# https://doc.esri.com/en/arcgis-pro/latest/tool-reference/environment-settings/output-extent.html
_INVALID_EXTENT_KEYWORDS = {"INTERSECTION": "MINOF", "UNION": "MAXOF"}


def test_no_gui_labels_as_extent_keywords():
    # Regression guard for #174 (ADR-0077): a GUI extent label passed as an
    # `extent=` scripting keyword crashes only in a live Pro session, invisible
    # to the arcpy-free suite. Static AST deny-list over every source file.
    offenders = []
    for path in _autogis_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if (kw.arg == "extent" and isinstance(kw.value, ast.Constant)
                        and kw.value.value in _INVALID_EXTENT_KEYWORDS):
                    offenders.append(
                        f"{path}:{kw.value.lineno} extent={kw.value.value!r} is a "
                        f"GUI label, not a scripting keyword -- use "
                        f"{_INVALID_EXTENT_KEYWORDS[kw.value.value]!r}")
    assert not offenders, "\n".join(offenders)


def _const_strs(seq):
    """Values of a Tuple/List literal, or None if any element isn't a constant
    (i.e. the domain can't be resolved statically -- callers fail loud on None)."""
    if not isinstance(seq, (ast.Tuple, ast.List)):
        return None
    out = []
    for elt in seq.elts:
        if not isinstance(elt, ast.Constant):
            return None
        out.append(elt.value)
    return out


def _dotted(node):
    """Dotted name of an Attribute/Name chain (toolbox_core.ELEVATION_CONVERSIONS),
    or None."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _resolve_domain(expr, names):
    """Resolve a `domain=` expression to its list of values, or None if the
    shape isn't statically resolvable. Covers the forms the .pyt actually uses:
    an inline tuple/list, a bare name, a dotted attribute, and sorted()/tuple()
    wrapping either. `names` maps referenceable names to their value lists."""
    if isinstance(expr, (ast.Tuple, ast.List)):
        return _const_strs(expr)
    if isinstance(expr, ast.Name):
        return names.get(expr.id)
    if isinstance(expr, ast.Attribute):
        key = _dotted(expr)
        return names.get(key) if key else None
    if (isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name)
            and expr.func.id in {"sorted", "tuple"} and len(expr.args) == 1):
        return _resolve_domain(expr.args[0], names)
    return None


def _domain_offenders(tree, names):
    """(offenders, checked): flag empty-string or unresolvable `domain=` sites,
    and count how many were inspected so a zero-match walk can't pass vacuously."""
    offenders, checked = [], 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg != "domain":
                continue
            checked += 1
            vals = _resolve_domain(kw.value, names)
            if vals is None:
                offenders.append(
                    f"line {kw.value.lineno}: domain= is not statically "
                    f"resolvable -- extend _resolve_domain to cover it")
            elif "" in vals:
                offenders.append(f"line {kw.value.lineno}: empty string in domain=")
    return offenders, checked


def _pyt_domain_names(tree):
    """Names a .pyt `domain=` can reference -> their value lists: module-level
    literal tuples resolved from `tree`, plus collections imported from
    arcpy-free modules (imported for real). Both dicts iterate to their keys,
    which is exactly what `sorted(...)`/`tuple(...)` turn into the domain."""
    from autogis.core.envmon.opentopo import DEM_DATASETS
    from autogis.adapters import toolbox_core
    names = {
        "DEM_DATASETS": list(DEM_DATASETS),
        "toolbox_core.ELEVATION_CONVERSIONS": list(toolbox_core.ELEVATION_CONVERSIONS),
    }
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        vals = _const_strs(node.value)
        if vals is None:
            continue
        for tgt in node.targets:
            if isinstance(tgt, ast.Name):
                names[tgt.id] = vals
    return names


def test_pyt_valuelist_domains_have_no_empty_strings():
    # Regression guard for issue #214 (fixed by PR #216): arcpy's ValueList
    # FilterObject rejects "" in a Parameter's domain, crashing the tool dialog
    # before execute() runs. Static, arcpy-free. Resolves the indirect domains
    # this toolbox actually uses (module literals like _CAD_OUTPUT_TYPES, and
    # sorted(DEM_DATASETS) / tuple(toolbox_core.ELEVATION_CONVERSIONS)) -- an
    # unresolvable domain fails the test instead of passing vacuously.
    pyt = pathlib.Path(autogis.__file__).parent / "adapters" / "toolbox.pyt"
    tree = ast.parse(pyt.read_text(encoding="utf-8"), filename=str(pyt))
    offenders, checked = _domain_offenders(tree, _pyt_domain_names(tree))
    assert not offenders, "\n".join(offenders)
    # Floor: this toolbox has many ValueList params. A zero here would mean the
    # walk matched nothing (the original false-green shape), not that all is well.
    assert checked >= 10, f"only {checked} domain= sites inspected -- walk broke"


def test_domain_resolver_catches_indirect_empty_string():
    # The reviewer reproduced #214's gap with domains the inline-only walk
    # missed. Prove the resolver catches an empty string behind each real shape:
    # a bare module Name (the reviewer's exact repro, and _CAD_OUTPUT_TYPES),
    # sorted(Name) (DEM_DATASETS), and tuple(obj.ATTR) (ELEVATION_CONVERSIONS).
    tree = ast.parse(
        "_param('a', 'A', 'GPString', domain=BAD)\n"
        "_param('b', 'B', 'GPString', domain=sorted(BAD))\n"
        "_param('c', 'C', 'GPString', domain=tuple(obj.ATTR))\n")
    names = {"BAD": ["", "median"], "obj.ATTR": ["", "x"]}
    offenders, checked = _domain_offenders(tree, names)
    assert checked == 3
    assert len(offenders) == 3, offenders
    # And a clean indirect domain must NOT be flagged (no false positive), while
    # an unfamiliar shape must fail loud rather than pass silently.
    ok, _ = _domain_offenders(
        ast.parse("_param('d', 'D', 'GPString', domain=sorted(GOOD))"),
        {"GOOD": ["a", "b"]})
    assert ok == []
    unknown, _ = _domain_offenders(
        ast.parse("_param('e', 'E', 'GPString', domain=mystery())"), {})
    assert len(unknown) == 1
