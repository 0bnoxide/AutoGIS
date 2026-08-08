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
