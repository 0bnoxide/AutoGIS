from pathlib import Path
import csv
import os
import pytest
from autogis.core.envmon.report_figure_package import (
    DeliverableFile, FigurePackageResult,
    load_deliverable_spec, assemble_figure_package,
    write_package_manifest, DELIVERABLE_ROLES, _is_link_or_reparse,
    _named_streams,
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


def test_destination_collision_is_rejected_before_output_write(tmp_path):
    first = tmp_path / "first" / "result.csv"
    second = tmp_path / "second" / "RESULT.csv"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")
    entries = [
        {"path": str(first), "role": "data_csv"},
        {"path": str(second), "role": "compliance_table"},
    ]
    for index, ordered in enumerate((entries, list(reversed(entries)))):
        out_dir = tmp_path / f"deliverable-{index}"
        with pytest.raises(ValueError, match="destination collision"):
            assemble_figure_package(ordered, out_dir)
        assert not out_dir.exists()


@pytest.mark.parametrize("name", ["manifest.csv", "README.txt"])
def test_generated_metadata_destination_is_reserved(tmp_path, name):
    source = tmp_path / name
    source.write_text("deliverable", encoding="utf-8")
    out_dir = tmp_path / "deliverable"

    with pytest.raises(ValueError, match="destination collision"):
        assemble_figure_package([
            {"path": str(source), "role": "other"},
        ], out_dir)

    assert not out_dir.exists()


def test_same_basename_in_different_subdirectories_is_valid(tmp_path):
    figure = tmp_path / "figure" / "result.pdf"
    data = tmp_path / "data-source" / "result.pdf"
    figure.parent.mkdir()
    data.parent.mkdir()
    figure.write_bytes(b"figure")
    data.write_bytes(b"data")
    out_dir = tmp_path / "deliverable"

    result = assemble_figure_package([
        {"path": str(figure), "role": "figure_pdf"},
        {"path": str(data), "role": "data_csv"},
    ], out_dir)

    assert result.copied_count == 2
    assert (out_dir / "figures" / "result.pdf").read_bytes() == b"figure"
    assert (out_dir / "data" / "result.pdf").read_bytes() == b"data"


@pytest.mark.parametrize("name", [
    "data.csv:stream", "bad?.csv", "trailing.", "trailing ",
    "NUL.txt", "com1.csv", "LPT².log", "CONOUT$.txt", "VERY_L~1.CSV",
])
def test_win32_unsafe_destination_is_rejected_before_output_write(tmp_path, name):
    out_dir = tmp_path / "deliverable"

    with pytest.raises(ValueError, match="Invalid Windows destination component"):
        assemble_figure_package([
            {"path": str(tmp_path / name), "role": "other"},
        ], out_dir)

    assert not out_dir.exists()


def test_dos_short_name_alias_is_rejected_in_both_orders(tmp_path):
    long_source = tmp_path / "long" / "very_long_deliverable_filename.csv"
    short_source = tmp_path / "short" / "VERY_L~1.CSV"
    long_source.parent.mkdir()
    short_source.parent.mkdir()
    long_source.write_text("long", encoding="utf-8")
    short_source.write_text("short", encoding="utf-8")
    entries = [
        {"path": str(long_source), "role": "data_csv"},
        {"path": str(short_source), "role": "data_csv"},
    ]

    for index, ordered in enumerate((entries, list(reversed(entries)))):
        out_dir = tmp_path / f"short-alias-package-{index}"
        with pytest.raises(ValueError, match="Invalid Windows destination"):
            assemble_figure_package(ordered, out_dir)
        assert not out_dir.exists()


def _symlink(link: Path, target: Path, *, directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")


def test_destination_symlink_blocks_entire_batch_in_both_orders(tmp_path):
    safe = tmp_path / "sources" / "safe.csv"
    unsafe = tmp_path / "sources" / "unsafe.csv"
    safe.parent.mkdir()
    safe.write_text("safe", encoding="utf-8")
    unsafe.write_text("unsafe", encoding="utf-8")
    entries = [
        {"path": str(safe), "role": "data_csv"},
        {"path": str(unsafe), "role": "data_csv"},
    ]

    for index, ordered in enumerate((entries, list(reversed(entries)))):
        out_dir = tmp_path / f"deliverable-{index}"
        data_dir = out_dir / "data"
        data_dir.mkdir(parents=True)
        external = tmp_path / f"external-{index}.csv"
        external.write_text("external", encoding="utf-8")
        _symlink(data_dir / "unsafe.csv", external)

        with pytest.raises(ValueError, match="symlink or reparse point"):
            assemble_figure_package(ordered, out_dir)

        assert external.read_text(encoding="utf-8") == "external"
        assert not (data_dir / "safe.csv").exists()
        assert not (out_dir / "manifest.csv").exists()
        assert not (out_dir / "README.txt").exists()


def test_intermediate_directory_symlink_cannot_escape_package(tmp_path):
    source = tmp_path / "result.csv"
    source.write_text("source", encoding="utf-8")
    out_dir = tmp_path / "deliverable"
    out_dir.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    _symlink(out_dir / "data", external, directory=True)

    with pytest.raises(ValueError, match="symlink or reparse point"):
        assemble_figure_package([
            {"path": str(source), "role": "data_csv"},
        ], out_dir)

    assert not (external / "result.csv").exists()
    assert not (out_dir / "manifest.csv").exists()
    assert not (out_dir / "README.txt").exists()


def test_symlinked_output_ancestor_is_rejected_before_mkdir(tmp_path):
    external = tmp_path / "external"
    external.mkdir()
    linked_parent = tmp_path / "linked-parent"
    _symlink(linked_parent, external, directory=True)
    out_dir = linked_parent / "deliverable"

    with pytest.raises(ValueError, match="symlink or reparse point"):
        assemble_figure_package([], out_dir)

    assert not (external / "deliverable").exists()


@pytest.mark.parametrize("metadata_name", ["manifest.csv", "README.txt"])
def test_generated_metadata_symlink_cannot_mutate_external_file(
        tmp_path, metadata_name):
    out_dir = tmp_path / "deliverable"
    out_dir.mkdir()
    external = tmp_path / f"external-{metadata_name}"
    external.write_text("external", encoding="utf-8")
    _symlink(out_dir / metadata_name, external)

    with pytest.raises(ValueError, match="symlink or reparse point"):
        assemble_figure_package([], out_dir)

    assert external.read_text(encoding="utf-8") == "external"


def test_windows_reparse_attribute_is_treated_as_redirect():
    class ReparsePath:
        @staticmethod
        def lstat():
            return type("Metadata", (), {
                "st_mode": 0,
                "st_file_attributes": 0x400,
            })()

    assert _is_link_or_reparse(ReparsePath())


def test_lexical_parent_segment_cannot_bypass_symlink_preflight(tmp_path):
    safe = tmp_path / "safe"
    safe.mkdir()
    external = tmp_path / "external"
    nested = external / "nested"
    nested.mkdir(parents=True)
    _symlink(safe / "link", nested, directory=True)
    out_dir = safe / "link" / ".." / "package"

    with pytest.raises(ValueError, match="must not contain"):
        assemble_figure_package([], out_dir)

    assert not (external / "package").exists()
    assert not (safe / "package").exists()


def test_normal_absolute_and_relative_output_paths_still_work(tmp_path, monkeypatch):
    absolute = tmp_path / "absolute-package"
    assemble_figure_package([], absolute)
    assert (absolute / "manifest.csv").exists()

    monkeypatch.chdir(tmp_path)
    relative = Path("relative-package")
    assemble_figure_package([], relative)
    assert (relative / "README.txt").exists()


def test_named_stream_source_blocks_entire_batch_in_both_orders(tmp_path):
    if os.name != "nt":
        pytest.skip("NTFS named streams require Windows")
    safe = tmp_path / "safe.csv"
    streamed = tmp_path / "streamed.csv"
    safe.write_text("safe", encoding="utf-8")
    streamed.write_text("visible", encoding="utf-8")
    try:
        Path(f"{streamed}:hidden").write_text("hidden", encoding="utf-8")
    except OSError as exc:
        pytest.skip(f"named streams unavailable: {exc}")
    assert ":hidden:$DATA" in _named_streams(streamed)
    entries = [
        {"path": str(safe), "role": "data_csv"},
        {"path": str(streamed), "role": "data_csv"},
    ]

    for index, ordered in enumerate((entries, list(reversed(entries)))):
        out_dir = tmp_path / f"stream-package-{index}"
        with pytest.raises(ValueError, match="NTFS named streams"):
            assemble_figure_package(ordered, out_dir)
        assert not out_dir.exists()


def test_existing_destination_hardlink_is_rejected_before_copy(tmp_path):
    safe = tmp_path / "sources" / "safe.csv"
    linked = tmp_path / "sources" / "linked.csv"
    safe.parent.mkdir()
    safe.write_text("safe", encoding="utf-8")
    linked.write_text("linked", encoding="utf-8")
    external = tmp_path / "external.csv"
    external.write_text("external", encoding="utf-8")
    out_dir = tmp_path / "hardlink-package"
    data_dir = out_dir / "data"
    data_dir.mkdir(parents=True)
    try:
        os.link(external, data_dir / "linked.csv")
    except OSError as exc:
        pytest.skip(f"hard links unavailable: {exc}")

    with pytest.raises(ValueError, match="hard link"):
        assemble_figure_package([
            {"path": str(safe), "role": "data_csv"},
            {"path": str(linked), "role": "data_csv"},
        ], out_dir)

    assert external.read_text(encoding="utf-8") == "external"
    assert not (data_dir / "safe.csv").exists()
    assert not (out_dir / "manifest.csv").exists()
