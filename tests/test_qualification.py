import json
import sys

import pytest

from autogis.adapters import qualification
from autogis.core.qualify import (
    Check,
    QualificationReport,
    qualification_exit_code,
    write_report_files,
)


class _Filter:
    def __init__(self, reject_empty=False):
        self.type = ""
        self._list = []
        self.reject_empty = reject_empty

    @property
    def list(self):
        return self._list

    @list.setter
    def list(self, value):
        if self.reject_empty and value == [""]:
            raise ValueError("FilterObject: illegal list value")
        self._list = value


class _Parameter:
    reject_empty = False

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        self.filter = _Filter(self.reject_empty)
        self.value = None
        self.enabled = True


class _ArcPy:
    Parameter = _Parameter

    def __init__(self):
        self.imported = []
        self.extension_calls = []

    def ImportToolbox(self, path):
        self.imported.append(path)

    def GetInstallInfo(self):
        return {"Version": "3.6.1"}

    def ProductInfo(self):
        return "ArcView"

    def CheckExtension(self, code):
        self.extension_calls.append(code)
        return "Available"


def test_report_files_and_exit_contract(tmp_path):
    report = QualificationReport(
        {"version": "3.6.1"},
        (Check("one", "pass", 0.1, "ok"), Check("two", "skip")),
    )
    json_path, markdown_path = write_report_files(report, tmp_path)

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["schema"] == 1
    assert payload["summary"] == {"fail": 0, "pass": 1, "skip": 1}
    assert "do not execute tool bodies" in markdown_path.read_text(encoding="utf-8")
    assert qualification_exit_code(report) == 0

    self_test = QualificationReport({}, (
        Check("canary.parameter", "fail"),
        Check("canary.scratch-gdb", "fail"),
    ))
    assert qualification_exit_code(self_test, self_test=True) == 0


def test_environment_uses_documented_extension_codes(monkeypatch):
    arcpy = _ArcPy()
    monkeypatch.setattr(qualification, "_arcpy", lambda: arcpy)

    environment = qualification.collect_environment()

    assert environment["version"] == "3.6.1"
    assert environment["product"] == "ArcView"
    assert arcpy.extension_calls == ["Spatial", "3D", "ImageAnalyst", "GeoStats"]


def test_toolbox_probes_all_registered_tools(monkeypatch):
    arcpy = _ArcPy()
    monkeypatch.setattr(qualification, "_arcpy", lambda: arcpy)
    monkeypatch.setitem(sys.modules, "arcpy", arcpy)

    checks = qualification.check_toolbox()

    assert checks[0].id == "toolbox.import"
    assert checks[1].detail == "21 registered tool(s)"
    assert len(checks) == 23
    assert all(check.outcome == "pass" for check in checks)


def test_canary_and_scratch_failure_use_production_paths(monkeypatch):
    class RejectingParameter(_Parameter):
        reject_empty = True

    arcpy = _ArcPy()
    arcpy.Parameter = RejectingParameter
    monkeypatch.setattr(qualification, "_arcpy", lambda: arcpy)
    canary = qualification.check_toolbox(
        extra_tools=(qualification._BrokenParamCanary,),
        include_registered=False,
    )
    assert [(check.id, check.outcome) for check in canary] == [
        ("canary.parameter", "fail")]

    from autogis.core.envmon import gdb_schema, validate_database

    def create_schema(path, qa=None):
        if path.parent.is_file():
            raise OSError("parent is a file")
        path.mkdir()
        return qa

    monkeypatch.setattr(gdb_schema, "create_or_update_gdb_schema", create_schema)
    monkeypatch.setattr(
        validate_database,
        "validate_database",
        lambda *_args: {"issues": 0, "tables_checked": 7},
    )
    assert qualification.exercise_scratch_gdb().outcome == "pass"
    doomed = qualification.exercise_scratch_gdb(doomed=True)
    assert (doomed.id, doomed.outcome) == ("canary.scratch-gdb", "fail")


def test_uninitialized_license_is_precondition(monkeypatch):
    arcpy = _ArcPy()
    arcpy.ProductInfo = lambda: "NotInitialized"
    monkeypatch.setattr(qualification, "_arcpy", lambda: arcpy)

    with pytest.raises(qualification.QualificationPreconditionError):
        qualification.collect_environment()
