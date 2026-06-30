"""CLI tests for envmon register-source-doc command."""
from pathlib import Path

from click.testing import CliRunner

from autogis.adapters.cli import autogis


def _make_file(tmp_path: Path, name: str = "lab.xlsx", content: bytes = b"data") -> Path:
    f = tmp_path / name
    f.write_bytes(content)
    return f


def test_register_source_doc_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "register-source-doc" in result.output


def test_register_source_doc_basic(tmp_path):
    f = _make_file(tmp_path)
    reg = tmp_path / "source_docs.csv"
    result = CliRunner().invoke(autogis, [
        "envmon", "register-source-doc",
        "--file", str(f), "--site", "H281", "--event", "2026-Q2",
        "--tool", "import-edd", "--registry", str(reg),
    ])
    assert result.exit_code == 0, result.output
    assert "Registered:" in result.output
    assert "lab.xlsx" in result.output
    assert reg.exists()


def test_register_source_doc_skip_if_registered(tmp_path):
    f = _make_file(tmp_path)
    reg = tmp_path / "source_docs.csv"
    runner = CliRunner()
    args = [
        "envmon", "register-source-doc",
        "--file", str(f), "--site", "H281", "--event", "2026-Q2",
        "--tool", "import-edd", "--registry", str(reg), "--skip-if-registered",
    ]
    r1 = runner.invoke(autogis, args)
    assert r1.exit_code == 0
    assert "Registered:" in r1.output

    r2 = runner.invoke(autogis, args)
    assert r2.exit_code == 0
    assert "Already registered, skipped." in r2.output

    lines = reg.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2  # header + 1 record


def test_register_source_doc_without_skip_allows_duplicate(tmp_path):
    f = _make_file(tmp_path)
    reg = tmp_path / "source_docs.csv"
    runner = CliRunner()
    args = [
        "envmon", "register-source-doc",
        "--file", str(f), "--site", "H281", "--event", "2026-Q2",
        "--tool", "import-edd", "--registry", str(reg),
    ]
    runner.invoke(autogis, args)
    runner.invoke(autogis, args)
    lines = reg.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3  # header + 2 records


def test_register_source_doc_with_notes(tmp_path):
    f = _make_file(tmp_path)
    reg = tmp_path / "source_docs.csv"
    result = CliRunner().invoke(autogis, [
        "envmon", "register-source-doc",
        "--file", str(f), "--site", "H281", "--event", "2026-Q2",
        "--tool", "import-edd", "--registry", str(reg),
        "--notes", "manual re-import after QA correction",
    ])
    assert result.exit_code == 0
    assert "manual re-import" in reg.read_text(encoding="utf-8")
