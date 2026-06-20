import builtins, pytest
from autogis.adapters.guard import require_runtime, RuntimeUnavailable


def test_local_tool_errors_without_arcpy(monkeypatch):
    real = builtins.__import__
    def fake(name, *a, **k):
        if name == "arcpy":
            raise ModuleNotFoundError("No module named 'arcpy'")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", fake)
    with pytest.raises(RuntimeUnavailable) as e:
        require_runtime("import-gdb")
    assert "arcpy" in str(e.value).lower()


def test_cloud_ok_tool_passes_without_arcpy():
    require_runtime("inspect")   # no raise
