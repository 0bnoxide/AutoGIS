"""Wiring gaps at the `.pyt` marshalling seam — #431, #443, #446.

All three are the same class: something the toolbox declares or constructs and
then never reads. The `.pyt` itself is unimportable outside Pro (top-level
`import arcpy`), so the behavior lives in `toolbox_core` where it can be tested,
and the declaration-level invariants are checked against the `.pyt` source via
ast — the same approach test_toolbox_import.py already uses.
"""
import ast
import pathlib

import pytest

import autogis
from autogis.adapters import toolbox_core
from autogis.core.common.config import FigureSpec
from autogis.core.common.qa import QACollector, SEV_ERROR, SEV_INFO
from autogis.core.harvest.models import AttachmentResult, RunSummary

PYT = pathlib.Path(autogis.__file__).parent / "adapters" / "toolbox.pyt"


# --------------------------------------------------------------- #431 harvest
def _summary(*results):
    summary = RunSummary.from_counts(
        {s: sum(1 for r in results if (r.disposition or r.status) == s)
         for s in ("downloaded", "skipped", "failed")})
    summary.results = list(results)
    return summary


def _result(status, error=None, name="a.jpg"):
    return AttachmentResult(1, 2, name, None, None, status, error,
                            disposition=status)


@pytest.fixture
def fake_harvest(monkeypatch):
    """Patch the core harvester `run_harvest` calls, keeping the seam real."""
    def install(summary):
        from autogis.core.harvest import harvester
        monkeypatch.setattr(harvester, "harvest",
                            lambda _gis, _cfg: summary)
    return install


def _config():
    return toolbox_core.build_harvest_config(
        directory="d", group_template="{g}", filename_template="{n}",
        url="http://x")


def test_harvest_failures_reach_the_qa_collector(fake_harvest):
    """The .pyt built a QACollector, passed it to nothing, and printed only
    "N attachment(s) processed" — a run where every attachment failed looked
    identical to a clean one (#431)."""
    fake_harvest(_summary(_result("downloaded"),
                          _result("failed", "HTTP 500", "photo2.jpg")))
    qa = QACollector()

    results = toolbox_core.run_harvest(_config(), object(), qa)

    assert len(results) == 2
    failed = [r for r in qa.records
              if r.category == "attachment_download_failed"]
    assert len(failed) == 1
    assert failed[0].severity == SEV_ERROR
    assert "photo2.jpg" in failed[0].message
    assert "HTTP 500" in failed[0].message


def test_clean_harvest_records_an_informational_summary(fake_harvest):
    fake_harvest(_summary(_result("downloaded"), _result("skipped")))
    qa = QACollector()

    toolbox_core.run_harvest(_config(), object(), qa)

    summary = [r for r in qa.records if r.category == "harvest_summary"]
    assert len(summary) == 1
    assert summary[0].severity == SEV_INFO
    assert "1 downloaded, 1 skipped, 0 failed" in summary[0].message
    assert not [r for r in qa.records if r.severity == SEV_ERROR]


def test_run_harvest_without_a_collector_is_unchanged(fake_harvest):
    """`qa` is optional so existing callers (and the CLI path) are untouched."""
    fake_harvest(_summary(_result("failed", "boom")))
    assert len(toolbox_core.run_harvest(_config(), object())) == 1


# ------------------------------------------------------- #443 contours block
def test_spec_contour_kwargs_maps_the_shipped_potentiometric_spec():
    """`contours:` in the figure spec was inert — editing interval_ft did
    nothing because the pipeline called build_groundwater_contours() bare."""
    shipped = (pathlib.Path(autogis.__file__).parent / "config"
               / "figure_specs" / "CKG_GW_Potentiometric.yaml")
    kwargs = toolbox_core.spec_contour_kwargs(FigureSpec.load(shipped))

    assert kwargs == {"method": "TIN", "contour_interval": 1.0,
                      "min_valid_points": 3}
    # The mapped names must be real build_groundwater_contours parameters,
    # or the ** call raises TypeError only inside Pro.
    import inspect

    from autogis.core.envmon.groundwater_contours import (
        build_groundwater_contours,
    )
    accepted = set(inspect.signature(build_groundwater_contours).parameters)
    assert set(kwargs) <= accepted


def test_spec_contour_kwargs_omits_what_the_spec_omits():
    """Absent keys fall through to the core defaults rather than being
    re-guessed here (one source of truth for the defaults)."""
    assert toolbox_core.spec_contour_kwargs(FigureSpec(data={})) == {}
    assert toolbox_core.spec_contour_kwargs(
        FigureSpec(data={"contours": {"interval_ft": 0.5}})) == {
            "contour_interval": 0.5}


@pytest.mark.parametrize("block,fragment", [
    ({"method": "Kriging"}, "not one of"),
    ({"interval_ft": "wide"}, "must be numeric"),
    ({"min_valid_points": "three"}, "must be numeric"),
    ("TIN", "must be a mapping"),
])
def test_spec_contour_kwargs_rejects_unusable_values(block, fragment):
    """A silent fallback would put us back where we started: a spec key that
    reads as authoritative and changes nothing."""
    with pytest.raises(ValueError, match=fragment):
        toolbox_core.spec_contour_kwargs(FigureSpec(data={"contours": block}))


# ------------------------------------------- #446 declared-but-unread params
def _tool_classes():
    tree = ast.parse(PYT.read_text(encoding="utf-8"), filename=str(PYT))
    return [c for c in tree.body
            if isinstance(c, ast.ClassDef)
            and any(isinstance(m, ast.FunctionDef) and m.name == "execute"
                    for m in c.body)]


def _uses_named_lookup(cls: ast.ClassDef) -> bool:
    """True for the `p = {q.name: q for q in parameters}` idiom.

    Tools 1/9/10 index `parameters[0]` positionally instead; a name never
    appears there, so they cannot be checked this way and are skipped rather
    than reported as false positives.
    """
    return any(isinstance(n, ast.DictComp) for n in ast.walk(cls))


def test_no_pyt_tool_declares_a_parameter_its_body_never_reads():
    """FullPipeline required an "Export folder" that execute() never read, so
    Pro blocked the run on a value it then threw away (#446). Declared-and-
    unread is also how #431's dropped QACollector survived review.
    """
    orphans = {}
    for cls in _tool_classes():
        if not _uses_named_lookup(cls):
            continue
        declared, declaration_nodes = [], set()
        for node in ast.walk(cls):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "_param" and node.args
                    and isinstance(node.args[0], ast.Constant)):
                declared.append(node.args[0].value)
                declaration_nodes.add(id(node.args[0]))
        # The declaration itself is a string constant naming the parameter;
        # excluding it by node identity is what makes "referenced elsewhere"
        # mean something (otherwise every parameter references itself and
        # this assertion can never fail).
        referenced = {n.value for n in ast.walk(cls)
                      if isinstance(n, ast.Constant)
                      and isinstance(n.value, str)
                      and id(n) not in declaration_nodes}
        unread = [n for n in declared if n not in referenced]
        if unread:
            orphans[cls.name] = sorted(unread)
    assert not orphans, (
        f".pyt parameters declared but never read by the tool body: {orphans}")


# ------------------- #459/#461/#462 figure-spec keys and the .pyt skeleton
#
# The scopes that read a FigureSpec on the export path, as
# (filename, enclosing class or None, function). Scoped this precisely because
# `spec` names an unrelated dict elsewhere -- generate-job-queue's manifest --
# and because EVERY .pyt tool class has an `execute`, so matching on the
# function name alone would sweep in all of them.
_FIGURE_SPEC_SCOPES = {
    ("toolbox.pyt", "ExportFigures", "execute"),
    ("cli.py", None, "gen_map_series_cmd"),
    ("layout_manager.py", None, "prepare_figure_aprx"),
}

# `template_aprx` is the schema key; `aprx_template` is its documented
# fallback alias, read as `spec.get("template_aprx") or spec.get(...)`.
_FIGURE_SPEC_ALIASES = {"aprx_template"}


def _shipped_figure_spec_keys():
    import yaml
    cfg = pathlib.Path(autogis.__file__).parent / "config"
    keys = set()
    for p in list((cfg / "figure_specs").glob("*.y*ml")) + [
            cfg / "_templates" / "site_skeleton" / "figure_spec.yaml"]:
        keys |= set(yaml.safe_load(p.read_text(encoding="utf-8")) or {})
    return keys


def _spec_get_keys(path: pathlib.Path):
    """Every `spec.get("KEY")` inside a scope that holds a FigureSpec."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found, scopes = set(), set()
    # (enclosing class or None, function) for every function in the module.
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for m in node.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    scopes.add((node.name, m))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            scopes.add((None, node))
    for cls_name, fn in scopes:
        if (path.name, cls_name, fn.name) not in _FIGURE_SPEC_SCOPES:
            continue
        for n in ast.walk(fn):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "get"
                    and isinstance(n.func.value, ast.Name)
                    and n.func.value.id == "spec"
                    and n.args and isinstance(n.args[0], ast.Constant)):
                found.add(n.args[0].value)
    return found


def test_every_figure_spec_key_read_on_the_export_path_exists():
    """Both export call sites read `spec["layouts"]` — a key defined by no
    spec, no template and no doc — so layout_names was always None,
    export_layouts fell through its filter and every APRX layout was exported
    unconfigured under one colliding filename stem (#459). The same class as
    #443 (`contours`) and the dead `combined_pdf_name` (#463).

    A key that reads as authoritative and resolves to nothing is the bug; this
    asserts every key read is one a spec can actually supply.
    """
    from autogis.core.common.config import FIGURE_REQUIRED

    adapters = pathlib.Path(autogis.__file__).parent / "adapters"
    envmon = pathlib.Path(autogis.__file__).parent / "core" / "envmon"
    read = set()
    for p in (PYT, adapters / "cli.py", envmon / "layout_manager.py"):
        read |= _spec_get_keys(p)
    # The scopes must actually have been found, or this passes vacuously.
    assert "layout_name" in read and "required_layers" in read

    known = (set(FIGURE_REQUIRED) | _shipped_figure_spec_keys()
             | _FIGURE_SPEC_ALIASES)
    assert not (read - known), (
        f"figure-spec keys read but defined nowhere: {sorted(read - known)}")


def test_pyt_figure_spec_skeleton_loads_through_figure_spec_load(tmp_path):
    """LoadFigureSpec's only output was rejected by FigureSpec.load — it
    omitted the required `figure_title` and offered `analyte_set_name`, a
    Python parameter name rather than a config key. The tool reported
    "Template written" anyway (#461)."""
    from autogis.core.envmon.init_site import render_figure_spec_template

    out = tmp_path / "fs.yaml"
    out.write_text(render_figure_spec_template(callout_template_id="CKG_GW"),
                   encoding="utf-8")
    spec = FigureSpec.load(out)          # raises ConfigError if it regresses
    assert spec.get("callout_template")["template_id"] == "CKG_GW"
    assert spec.get("figure_title")
    assert "analyte_set_name" not in spec.data
    # analyte_list() must resolve, i.e. the skeleton offers the keys it reads.
    assert spec.analyte_list({})


def test_pyt_load_figure_spec_does_not_carry_its_own_skeleton():
    """One skeleton, rendered from the shipped template. The second hardcoded
    copy is exactly what drifted into being unloadable (#461)."""
    src = PYT.read_text(encoding="utf-8")
    assert "render_figure_spec_template" in src
    assert "analyte_set_name" not in src


@pytest.mark.parametrize("value,expected", [
    ("CKG_GW", "CKG_GW"),
    ("NO", "NO"),        # unquoted, YAML 1.1 would read this as the bool False
    ("ZT42_SOIL", "ZT42_SOIL"),
])
def test_figure_spec_template_quotes_the_callout_template_id(value, expected):
    """The id lands in a YAML scalar. Unquoted, `NO`/`on`/`123` come back as
    bool/int rather than the id the operator picked in the .pyt dropdown."""
    import yaml
    from autogis.core.envmon.init_site import render_figure_spec_template

    data = yaml.safe_load(render_figure_spec_template(callout_template_id=value))
    assert data["callout_template"]["template_id"] == expected


@pytest.mark.parametrize("bad", [
    'X"quote', "X\\backslash", "X\n  base_font_points: 999", "X\ttab",
])
def test_figure_spec_template_rejects_an_unsafe_callout_template_id(bad):
    """render_figure_spec_template is core API now, not just the .pyt dropdown:
    a newline injects a sibling key into callout_template, and a quote breaks
    out of the scalar. Same trust boundary site_name already guards."""
    from autogis.core.envmon.init_site import render_figure_spec_template

    with pytest.raises(ValueError, match="callout template id"):
        render_figure_spec_template(callout_template_id=bad)


def test_figure_spec_template_leaves_the_other_template_values_intact():
    """The substitution must hit template_id and nothing else in the block."""
    import yaml
    from autogis.core.envmon.init_site import render_figure_spec_template

    ct = yaml.safe_load(
        render_figure_spec_template(callout_template_id="CKG_GW")
    )["callout_template"]
    assert ct["base_font_points"] == 6
    assert ct["standoff_points"] == 18
    assert ct["point_buffer_points"] == 10
