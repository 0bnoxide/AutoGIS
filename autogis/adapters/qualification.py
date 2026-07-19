"""Live ArcGIS Pro qualification adapter (ADR-0091)."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import shutil
import sys
import tempfile
import traceback
from pathlib import Path
from time import perf_counter as _clock

import autogis
from autogis.core.qualify import (
    Check,
    QualificationReport,
    qualification_exit_code,
    write_report_files,
)


_EXTENSIONS = ("Spatial", "3D", "ImageAnalyst", "GeoStats")


class QualificationPreconditionError(RuntimeError):
    """The installed ArcGIS Pro runtime cannot start qualification."""


def _arcpy():
    from autogis.runtime.sessions import arcpy_env
    return arcpy_env()


def _seconds(started: float) -> float:
    return _clock() - started


def collect_environment() -> dict:
    try:
        arcpy = _arcpy()
        install = arcpy.GetInstallInfo()
        product = arcpy.ProductInfo()
        if product == "NotInitialized":
            raise RuntimeError("the ArcGIS Pro product license is not initialized")
        extensions = {code: arcpy.CheckExtension(code) for code in _EXTENSIONS}
    except Exception as exc:
        raise QualificationPreconditionError(
            f"ArcGIS Pro preflight failed: {exc}. Open Pro, initialize its "
            "license, and rerun with the cloned arcgispro-py3-autogis Python."
        ) from exc
    return {
        "version": install.get("Version", ""),
        "product": product,
        "extensions": extensions,
        "python": sys.executable,
        "autogis": str(Path(autogis.__file__).resolve()),
    }


def _toolbox_path() -> Path:
    return Path(autogis.__file__).parent / "adapters" / "toolbox.pyt"


def _load_toolbox(path: Path):
    loader = importlib.machinery.SourceFileLoader(
        "_autogis_qualification_toolbox", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise ImportError(f"could not create a module spec for {path}")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _check_tool(tool_class) -> Check:
    started = _clock()
    check_id = getattr(
        tool_class, "qualification_id", f"toolbox.{tool_class.__name__}")
    try:
        tool = tool_class()
        parameters = list(tool.getParameterInfo())
        names = [parameter.name for parameter in parameters]
        if any(not name for name in names):
            raise ValueError("parameter names must be non-empty")
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"duplicate parameter names: {duplicates}")
        update = getattr(tool, "updateParameters", None)
        if update is not None:
            update(parameters)
        return Check(check_id, "pass", _seconds(started),
                     f"{len(parameters)} parameter(s)")
    except Exception:
        return Check(check_id, "fail", _seconds(started), traceback.format_exc())


def check_toolbox(*, extra_tools=(), include_registered=True) -> list[Check]:
    checks: list[Check] = []
    tool_classes = []
    if include_registered:
        path = _toolbox_path()
        started = _clock()
        try:
            _arcpy().ImportToolbox(str(path))
            checks.append(Check("toolbox.import", "pass", _seconds(started),
                                str(path)))
        except Exception:
            checks.append(Check("toolbox.import", "fail", _seconds(started),
                                traceback.format_exc()))

        started = _clock()
        try:
            module = _load_toolbox(path)
            tool_classes.extend(module.Toolbox().tools)
            checks.append(Check("toolbox.load", "pass", _seconds(started),
                                f"{len(tool_classes)} registered tool(s)"))
        except Exception:
            checks.append(Check("toolbox.load", "fail", _seconds(started),
                                traceback.format_exc()))
    tool_classes.extend(extra_tools)
    checks.extend(_check_tool(tool_class) for tool_class in tool_classes)
    return checks


class _BrokenParamCanary:
    qualification_id = "canary.parameter"

    def getParameterInfo(self):
        arcpy = _arcpy()
        parameter = arcpy.Parameter(
            displayName="Broken value-list parameter",
            name="broken_value_list",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        parameter.filter.type = "ValueList"
        parameter.filter.list = [""]
        return [parameter]


def exercise_scratch_gdb(*, doomed=False) -> Check:
    started = _clock()
    check_id = "canary.scratch-gdb" if doomed else "scratch-gdb.round-trip"
    root = Path(tempfile.mkdtemp(prefix="autogis-qualification-"))
    try:
        parent = root
        if doomed:
            parent = root / "not-a-directory"
            parent.write_text("canary", encoding="utf-8")
        gdb = parent / "qualification.gdb"
        from autogis.core.common.qa import QACollector
        from autogis.core.envmon.gdb_schema import create_or_update_gdb_schema
        from autogis.core.envmon.validate_database import validate_database

        qa = QACollector()
        create_or_update_gdb_schema(gdb, qa=qa)
        summary = validate_database(gdb, qa, {})
        if summary["issues"]:
            raise RuntimeError(
                f"scratch validation reported {summary['issues']} issue(s)")
        return Check(check_id, "pass", _seconds(started),
                     f"validated {summary['tables_checked']} dataset(s)")
    except Exception:
        return Check(check_id, "fail", _seconds(started), traceback.format_exc())
    finally:
        # FileGDB handles can outlive the call on Windows; cleanup is evidence
        # hygiene, not part of the qualification outcome.
        shutil.rmtree(root, ignore_errors=True)


def run_qualification(out_dir: Path, *, self_test=False):
    environment = collect_environment()
    if self_test:
        checks = check_toolbox(
            extra_tools=(_BrokenParamCanary,), include_registered=False)
        checks.append(exercise_scratch_gdb(doomed=True))
    else:
        checks = check_toolbox()
        checks.append(exercise_scratch_gdb())
    report = QualificationReport(environment, tuple(checks))
    paths = write_report_files(report, out_dir)
    return report, paths, qualification_exit_code(report, self_test=self_test)
