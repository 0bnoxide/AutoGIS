"""CLI surface for the envmon sub-group.

(a) A LOCAL tool (``import-gdb``) must fail cleanly under a no-arcpy condition
    with a message that mentions arcpy — a click error, not a traceback.
(b) A headless tool (``inspect``) must exit 0 against a real workbook.
"""
import builtins

from click.testing import CliRunner

from autogis.adapters.cli import autogis


def test_local_tool_clean_error_without_arcpy(monkeypatch, tmp_path):
    real = builtins.__import__

    def fake(name, *a, **k):
        if name == "arcpy":
            raise ModuleNotFoundError("No module named 'arcpy'")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)
    # Two existing path args so click's exists=True checks pass and we reach
    # the guard.
    site = tmp_path / "site.yaml"
    site.write_text("site_id: X\n", encoding="utf-8")
    wb = tmp_path / "wb.xlsx"
    wb.write_text("x", encoding="utf-8")

    result = CliRunner().invoke(
        autogis, ["envmon", "import-gdb", str(site), str(wb)])
    assert result.exit_code != 0
    assert "arcpy" in result.output.lower()
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_inspect_runs_headless(tmp_path):
    import openpyxl

    path = tmp_path / "synthetic.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data"
    ws["A1"] = "Well ID"
    ws["B1"] = "Date"
    ws["C1"] = "Benzene"
    ws["A2"] = "MW-1"
    ws["B2"] = "2026-01-01"
    ws["C2"] = 1.5
    wb.save(path)

    result = CliRunner().invoke(autogis, ["envmon", "inspect", str(path)])
    assert result.exit_code == 0, result.output
    assert "Data" not in result.output or "sheet" in result.output.lower()
