from pathlib import Path
import csv
import pytest
from autogis.core.envmon.report_figure_package import (
    DeliverableFile, FigurePackageResult,
    load_deliverable_spec, assemble_figure_package,
    write_package_manifest, DELIVERABLE_ROLES,
)


def _make_spec_yaml(tmp_path: Path, files: list[dict]) -> Path:
    import yaml
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.dump({"files": files}), encoding="utf-8")
    return spec_path


def test_load_deliverable_spec(tmp_path):
    spec = _make_spec_yaml(tmp_path, [{"path": "fig.pdf", "role": "figure_pdf"}])
    entries = load_deliverable_spec(spec)
    assert len(entries) == 1
    assert entries[0]["role"] == "figure_pdf"


def test_copy_existing_file(tmp_path):
    src = tmp_path / "Fig-1A.pdf"
    src.write_bytes(b"PDF content")
    spec = _make_spec_yaml(tmp_path, [{"path": str(src), "role": "figure_pdf"}])
    out_dir = tmp_path / "deliverable"
    result = assemble_figure_package(load_deliverable_spec(spec), out_dir)
    assert result.copied_count == 1
    assert (out_dir / "figures" / "Fig-1A.pdf").exists()


def test_figure_in_figures_subdir(tmp_path):
    src = tmp_path / "fig.pdf"
    src.write_bytes(b"x")
    spec = _make_spec_yaml(tmp_path, [{"path": str(src), "role": "figure_pdf"}])
    out_dir = tmp_path / "deliverable"
    assemble_figure_package(load_deliverable_spec(spec), out_dir)
    assert (out_dir / "figures").is_dir()


def test_data_csv_in_data_subdir(tmp_path):
    src = tmp_path / "results.csv"
    src.write_text("a,b\n1,2")
    spec = _make_spec_yaml(tmp_path, [{"path": str(src), "role": "data_csv"}])
    out_dir = tmp_path / "deliverable"
    assemble_figure_package(load_deliverable_spec(spec), out_dir)
    assert (out_dir / "data" / "results.csv").exists()


def test_missing_file_warning(tmp_path):
    spec = _make_spec_yaml(tmp_path, [{"path": "nonexistent.pdf", "role": "figure_pdf"}])
    out_dir = tmp_path / "deliverable"
    result = assemble_figure_package(load_deliverable_spec(spec), out_dir)
    assert result.missing_count == 1
    assert any(r.severity == "WARNING" for r in result.qa.records)


def test_manifest_written(tmp_path):
    src = tmp_path / "fig.pdf"
    src.write_bytes(b"x")
    spec = _make_spec_yaml(tmp_path, [{"path": str(src), "role": "figure_pdf"}])
    out_dir = tmp_path / "deliverable"
    result = assemble_figure_package(load_deliverable_spec(spec), out_dir)
    manifest = result.manifest_path
    assert manifest.exists()
    with manifest.open() as fh:
        rows = list(csv.DictReader(fh))
    assert "sha256" in rows[0]


def test_readme_written(tmp_path):
    spec = _make_spec_yaml(tmp_path, [])
    out_dir = tmp_path / "deliverable"
    assemble_figure_package(load_deliverable_spec(spec), out_dir)
    assert (out_dir / "README.txt").exists()


def test_copied_plus_missing_equals_total(tmp_path):
    src = tmp_path / "real.pdf"
    src.write_bytes(b"x")
    spec = _make_spec_yaml(tmp_path, [
        {"path": str(src), "role": "figure_pdf"},
        {"path": "ghost.pdf", "role": "figure_pdf"},
    ])
    out_dir = tmp_path / "deliverable"
    result = assemble_figure_package(load_deliverable_spec(spec), out_dir)
    assert result.copied_count + result.missing_count == len(load_deliverable_spec(spec))
