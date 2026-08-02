import csv
import os
from pathlib import Path

import pytest

from autogis.core.envmon import report_package_verifier as verifier_module
from autogis.core.envmon.report_figure_package import assemble_figure_package
from autogis.core.envmon.report_package_verifier import verify_report_package


def _package(tmp_path: Path):
    source = tmp_path / "source" / "result.csv"
    source.parent.mkdir()
    source.write_text("sample,value\nA,1\n", encoding="utf-8")
    package = tmp_path / "package"
    assemble_figure_package(
        [{"path": str(source), "role": "data_csv"}], package)
    return package, package / "data" / "result.csv"


def _categories(result):
    return {record.category for record in result.qa.records}


def test_verify_clean_package(tmp_path):
    package, _ = _package(tmp_path)

    result = verify_report_package(package)

    assert (result.manifest_count, result.expected_count,
            result.verified_count, result.extra_count) == (1, 1, 1, 0)
    assert not {record.severity for record in result.qa.records} & {
        "ERROR", "WARNING"}


def test_verify_detects_missing_modified_and_extra_files(tmp_path):
    package, delivered = _package(tmp_path)
    delivered.write_text("changed", encoding="utf-8")
    (package / "extra.txt").write_text("extra", encoding="utf-8")

    modified = verify_report_package(package)

    assert "package_file_modified" in _categories(modified)
    assert "package_file_extra" in _categories(modified)
    assert modified.verified_count == 0
    assert modified.extra_count == 1

    delivered.unlink()
    missing = verify_report_package(package)
    assert "package_file_missing" in _categories(missing)


def test_verify_detects_missing_package_readme(tmp_path):
    package, _ = _package(tmp_path)
    (package / "README.txt").unlink()

    result = verify_report_package(package)

    assert "package_metadata_missing" in _categories(result)


def test_verify_rejects_normalized_duplicate_manifest_paths(tmp_path):
    package, _ = _package(tmp_path)
    manifest = package / "manifest.csv"
    with manifest.open(newline="", encoding="utf-8") as fh:
        row = next(csv.DictReader(fh))
    row["dest_path"] = "DATA\\RESULT.csv"
    with manifest.open("a", newline="", encoding="utf-8") as fh:
        csv.DictWriter(fh, fieldnames=row).writerow(row)

    result = verify_report_package(package)

    assert "manifest_path_duplicate" in _categories(result)
    assert result.manifest_count == 2
    assert result.expected_count == 1


@pytest.mark.parametrize("dest_path", [
    "../outside.txt", "/outside.txt", "C:\\outside.txt",
    "data/result.csv:hidden", "data/NUL.txt", "data/trailing.",
    "data/VERY_L~1.CSV",
])
def test_verify_rejects_traversal_and_absolute_manifest_paths(tmp_path, dest_path):
    package, _ = _package(tmp_path)
    manifest = package / "manifest.csv"
    with manifest.open(newline="", encoding="utf-8") as fh:
        row = next(csv.DictReader(fh))
    row["dest_path"] = dest_path
    with manifest.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=row)
        writer.writeheader()
        writer.writerow(row)

    result = verify_report_package(package)

    assert "manifest_path_invalid" in _categories(result)
    assert result.expected_count == 0


def test_verify_rejects_dos_short_name_alias_manifest_row(tmp_path):
    source = tmp_path / "source" / "very_long_deliverable_filename.csv"
    source.parent.mkdir()
    source.write_text("sample,value\nA,1\n", encoding="utf-8")
    package = tmp_path / "package"
    assemble_figure_package(
        [{"path": str(source), "role": "data_csv"}], package)
    manifest = package / "manifest.csv"
    with manifest.open(newline="", encoding="utf-8") as fh:
        row = next(csv.DictReader(fh))
    row["dest_path"] = "data/VERY_L~1.CSV"
    with manifest.open("a", newline="", encoding="utf-8") as fh:
        csv.DictWriter(fh, fieldnames=row).writerow(row)

    result = verify_report_package(package)

    assert "manifest_path_invalid" in _categories(result)
    assert result.manifest_count == 2
    assert result.expected_count == 1


def test_verify_detects_malformed_manifest(tmp_path):
    package, _ = _package(tmp_path)
    (package / "manifest.csv").write_text(
        "dest_path,status\ndata/result.csv,copied\n", encoding="utf-8")

    result = verify_report_package(package)

    assert "manifest_malformed" in _categories(result)
    assert result.manifest_count == 0


def test_verify_rejects_external_symlink_target(tmp_path):
    package, delivered = _package(tmp_path)
    outside = tmp_path / "outside.csv"
    outside.write_text("outside", encoding="utf-8")
    delivered.unlink()
    try:
        delivered.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    result = verify_report_package(package)

    assert "package_external_symlink" in _categories(result)
    assert result.verified_count == 0


def test_verify_rejects_actual_portable_path_collision(tmp_path, monkeypatch):
    package, _ = _package(tmp_path)
    real_walk = list(os.walk(package))

    def colliding_walk(*_args, **_kwargs):
        for current, dirnames, filenames in real_walk:
            names = list(filenames)
            if Path(current) == package / "data":
                names.append("RESULT.csv")
            yield current, list(dirnames), names

    monkeypatch.setattr(
        "autogis.core.envmon.report_package_verifier.os.walk",
        colliding_walk)

    result = verify_report_package(package)

    assert "package_path_collision" in _categories(result)


def test_verify_rejects_actual_nonportable_path(tmp_path, monkeypatch):
    package, _ = _package(tmp_path)
    real_walk = list(os.walk(package))

    def unsafe_walk(*_args, **_kwargs):
        for current, dirnames, filenames in real_walk:
            names = list(filenames)
            if Path(current) == package / "data":
                names.append("result.csv:hidden")
            yield current, list(dirnames), names

    monkeypatch.setattr(
        "autogis.core.envmon.report_package_verifier.os.walk", unsafe_walk)

    result = verify_report_package(package)

    assert "package_path_invalid" in _categories(result)


def test_verify_rejects_unmanifested_named_stream(tmp_path, monkeypatch):
    package, delivered = _package(tmp_path)

    monkeypatch.setattr(
        "autogis.core.envmon.report_package_verifier._named_streams",
        lambda path: [":hidden:$DATA"] if path == delivered else [])

    result = verify_report_package(package)

    assert "package_named_stream" in _categories(result)


@pytest.mark.skipif(os.name != "nt", reason="NTFS alternate streams are Windows-only")
def test_verify_detects_real_ntfs_named_stream(tmp_path):
    package, delivered = _package(tmp_path)
    stream = Path(f"{delivered}:hidden")
    try:
        stream.write_text("unmanifested", encoding="utf-8")
    except OSError as exc:
        pytest.skip(f"filesystem does not support named streams: {exc}")

    result = verify_report_package(package)

    assert "package_named_stream" in _categories(result)


def test_verify_inspects_package_root_named_streams(tmp_path, monkeypatch):
    package, _ = _package(tmp_path)

    monkeypatch.setattr(
        "autogis.core.envmon.report_package_verifier._named_streams",
        lambda path: [":hidden:$DATA"] if path == package else [])

    result = verify_report_package(package)

    assert "package_named_stream" in _categories(result)


@pytest.mark.skipif(os.name != "nt", reason="NTFS alternate streams are Windows-only")
@pytest.mark.parametrize("directory_name", [None, "data"])
def test_verify_detects_real_ntfs_directory_stream(tmp_path, directory_name):
    package, _ = _package(tmp_path)
    directory = package if directory_name is None else package / directory_name
    stream = Path(f"{directory}:hidden")
    try:
        stream.write_text("unmanifested", encoding="utf-8")
    except OSError as exc:
        pytest.skip(f"filesystem does not support directory streams: {exc}")

    result = verify_report_package(package)

    assert "package_named_stream" in _categories(result)


def test_verify_rejects_external_reparse_directory(tmp_path, monkeypatch):
    package, _ = _package(tmp_path)
    junction = package / "junction"
    junction.mkdir()
    real_redirect = verifier_module._is_link_or_reparse
    real_outside = verifier_module._outside_root
    monkeypatch.setattr(
        "autogis.core.envmon.report_package_verifier._is_link_or_reparse",
        lambda path: path == junction or real_redirect(path))
    monkeypatch.setattr(
        "autogis.core.envmon.report_package_verifier._outside_root",
        lambda path, root: path == junction or real_outside(path, root))

    result = verify_report_package(package)

    assert "package_external_symlink" in _categories(result)


def test_verify_rejects_hardlinked_package_file(tmp_path):
    package, delivered = _package(tmp_path)
    outside = tmp_path / "outside.csv"
    outside.write_bytes(delivered.read_bytes())
    delivered.unlink()
    try:
        os.link(outside, delivered)
    except OSError as exc:
        pytest.skip(f"hard links unavailable: {exc}")

    result = verify_report_package(package)

    assert "package_hard_link" in _categories(result)
