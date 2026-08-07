"""Verify report-package contents against ``manifest.csv``."""
from __future__ import annotations

import csv
import ntpath
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..common.qa import QACollector, SEV_ERROR, SEV_INFO, SEV_WARNING
from .report_figure_package import (
    _is_link_or_reparse,
    _named_streams,
    _sha256_tree,
    _validate_windows_destination_component,
)
from .source_registry import compute_sha256

_MANIFEST_FIELDS = {"source_path", "dest_path", "role", "sha256", "status"}
_METADATA_PATHS = {"manifest.csv", "readme.txt"}
_SHA256_RE = re.compile(r"[0-9a-fA-F]{64}")


@dataclass
class ReportPackageVerificationResult:
    package_dir: Path
    manifest_path: Path
    manifest_count: int
    expected_count: int
    verified_count: int
    extra_count: int
    qa: QACollector


def _path_key(value: str) -> str:
    """Portable, case-insensitive manifest path identity."""
    return ntpath.normcase(ntpath.normpath(value))


def _destination_parts(value: str) -> tuple[str, ...] | None:
    """Return safe relative path parts, or ``None`` for malformed input."""
    portable = value.replace("\\", "/")
    if (not value.strip() or "\x00" in value or ntpath.isabs(value)
            or ntpath.splitdrive(value)[0]):
        return None
    parts = tuple(portable.split("/"))
    if any(part in {"", ".", ".."} for part in parts):
        return None
    try:
        for part in parts:
            _validate_windows_destination_component(part)
    except ValueError:
        return None
    return parts


def _within_manifested_dir(key: str, manifested_dirs: set) -> bool:
    """Is *key* a path inside a directory the manifest already accounts for?

    A directory deliverable is manifested as one row, so its contents are
    covered by that row's tree digest rather than being unmanifested extras.
    They are still walked -- the symlink, named-stream, hard-link and portable
    -path checks must apply inside a packaged geodatabase too.
    """
    return any(key.startswith(parent + ntpath.sep) for parent in manifested_dirs)


def _outside_root(path: Path, root: Path) -> bool:
    try:
        return not path.resolve(strict=False).is_relative_to(root)
    except (OSError, RuntimeError):
        return True


def verify_report_package(
    package_dir: Path,
    *,
    qa: Optional[QACollector] = None,
) -> ReportPackageVerificationResult:
    """Check one assembled report package without modifying it.

    Structural, missing, modified, traversal, and external-link findings are
    errors. Unmanifested files are warnings so the CLI's standard ``fail-on``
    threshold can make extras blocking when desired.
    """
    if qa is None:
        qa = QACollector()
    raw_root = Path(package_dir)
    root = raw_root.absolute()
    manifest = root / "manifest.csv"

    def result(manifest_count=0, expected_count=0, verified_count=0,
               extra_count=0):
        return ReportPackageVerificationResult(
            package_dir=root, manifest_path=manifest,
            manifest_count=manifest_count, expected_count=expected_count,
            verified_count=verified_count, extra_count=extra_count, qa=qa)

    try:
        root_redirects = _is_link_or_reparse(raw_root)
    except ValueError as exc:
        qa.add(SEV_ERROR, "package_path_unreadable", str(exc))
        return result()
    if root_redirects:
        qa.add(SEV_ERROR, "package_reparse_point",
               f"Package root is a symlink or reparse point: {raw_root}")
        return result()

    root = raw_root.resolve(strict=False)
    manifest = root / "manifest.csv"
    if not raw_root.is_dir():
        qa.add(SEV_ERROR, "package_missing",
               f"Package directory not found: {raw_root}")
        return result()
    if manifest.is_symlink() and _outside_root(manifest, root):
        qa.add(SEV_ERROR, "package_external_symlink",
               f"Manifest resolves outside package root: {manifest}")
        return result()
    if not manifest.exists():
        qa.add(SEV_ERROR, "manifest_missing",
               f"Package manifest not found: {manifest}")
        return result()
    readme = root / "README.txt"
    if not readme.is_file():
        qa.add(SEV_ERROR, "package_metadata_missing",
               f"Package README not found: {readme}")

    try:
        with manifest.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            fields = reader.fieldnames or []
            if len(fields) != len(set(fields)) or not _MANIFEST_FIELDS <= set(fields):
                qa.add(SEV_ERROR, "manifest_malformed",
                       "manifest.csv has missing or duplicate columns")
                return result()
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as exc:
        qa.add(SEV_ERROR, "manifest_malformed",
               f"Cannot read manifest.csv: {exc}")
        return result()

    expected: set[str] = set()
    expected_dirs: set[str] = set()
    verified = 0
    external_links: set[str] = set()

    for row_number, row in enumerate(rows, start=2):
        if None in row or any(row.get(field) is None for field in _MANIFEST_FIELDS):
            qa.add(SEV_ERROR, "manifest_malformed",
                   f"Manifest row {row_number} has the wrong number of columns")
            continue
        dest_value = row.get("dest_path", "")
        parts = _destination_parts(dest_value)
        if parts is None:
            qa.add(SEV_ERROR, "manifest_path_invalid",
                   f"Manifest row {row_number} has unsafe dest_path: "
                   f"{dest_value!r}")
            continue

        key = _path_key(dest_value)
        if key in _METADATA_PATHS:
            qa.add(SEV_ERROR, "manifest_path_invalid",
                   f"Manifest row {row_number} names package metadata: "
                   f"{dest_value}")
            continue
        if key in expected:
            qa.add(SEV_ERROR, "manifest_path_duplicate",
                   f"Manifest row {row_number} duplicates destination: "
                   f"{dest_value}")
            continue
        expected.add(key)
        target = root.joinpath(*parts)

        if _outside_root(target, root):
            qa.add(SEV_ERROR, "package_external_symlink",
                   f"Package path resolves outside package root: {dest_value}")
            external_links.add(key)
            continue

        status = row.get("status", "").strip().lower()
        if status == "missing":
            qa.add(SEV_ERROR, "package_file_missing",
                   f"Manifest records a missing deliverable: {dest_value}")
            if target.exists() or target.is_symlink():
                qa.add(SEV_ERROR, "manifest_status_mismatch",
                       f"Manifest marks an existing path missing: {dest_value}")
            continue
        if status != "copied":
            qa.add(SEV_ERROR, "manifest_status_invalid",
                   f"Manifest row {row_number} has unknown status: {status!r}")
            continue
        # A `source_gdb` deliverable is a directory (issue #426), so requiring
        # is_file() here reported every successfully assembled GDB package as
        # missing *and* flagged its contents as extras -- the advertised
        # build-then-verify workflow could never pass for that role.
        is_directory = target.is_dir() and not target.is_symlink()
        if is_directory:
            expected_dirs.add(key)
        elif not target.is_file():
            qa.add(SEV_ERROR, "package_file_missing",
                   f"Manifest file not found: {dest_value}")
            continue

        expected_sha = row.get("sha256", "")
        if not _SHA256_RE.fullmatch(expected_sha):
            qa.add(SEV_ERROR, "manifest_hash_invalid",
                   f"Manifest row {row_number} has invalid SHA-256")
            continue
        try:
            # Same digest function the packager used, so the two cannot drift.
            actual_sha = (_sha256_tree(target) if is_directory
                          else compute_sha256(target))
        except OSError as exc:
            qa.add(SEV_ERROR, "package_file_unreadable",
                   f"Cannot read {dest_value}: {exc}")
            continue
        if actual_sha.lower() != expected_sha.lower():
            qa.add(SEV_ERROR, "package_file_modified",
                   f"Checksum mismatch: {dest_value}")
            continue
        verified += 1

    extra = 0
    def walk_error(exc: OSError) -> None:
        qa.add(SEV_ERROR, "package_path_unreadable",
               f"Cannot inspect package path: {exc}")

    def inspect_streams(path: Path, relative: str) -> None:
        try:
            streams = _named_streams(path)
        except OSError as exc:
            qa.add(SEV_ERROR, "package_path_unreadable",
                   f"Cannot inspect package streams for {relative}: {exc}")
        else:
            if streams:
                qa.add(SEV_ERROR, "package_named_stream",
                       f"Package path has unmanifested named stream(s): "
                       f"{relative}: {', '.join(streams)}")

    inspect_streams(root, ".")
    actual_paths: dict[str, str] = {}
    for current, dirnames, filenames in os.walk(
            root, followlinks=False, onerror=walk_error):
        current_path = Path(current)
        redirect_dirs = []
        named_entries = ([(name, True) for name in list(dirnames)]
                         + [(name, False) for name in filenames])
        for name, is_dir in named_entries:
            path = current_path / name
            relative = path.relative_to(root).as_posix()
            key = _path_key(relative)
            try:
                _validate_windows_destination_component(name)
            except ValueError:
                qa.add(SEV_ERROR, "package_path_invalid",
                       f"Package contains a non-portable path: {relative}")
            previous = actual_paths.get(key)
            if previous is not None and previous != relative:
                qa.add(SEV_ERROR, "package_path_collision",
                       "Package contains paths with the same portable identity: "
                       f"{previous} and {relative}")
            else:
                actual_paths[key] = relative

            outside = _outside_root(path, root)
            try:
                redirects = _is_link_or_reparse(path)
            except ValueError as exc:
                qa.add(SEV_ERROR, "package_path_unreadable", str(exc))
                redirects = True
            if is_dir and redirects:
                dirnames.remove(name)
                redirect_dirs.append(path)
            if outside and key not in external_links:
                qa.add(SEV_ERROR, "package_external_symlink",
                       f"Package path resolves outside package root: {relative}")
                external_links.add(key)
            elif redirects:
                qa.add(SEV_ERROR, "package_reparse_point",
                       f"Package path is a symlink or reparse point: {relative}")
            else:
                if not is_dir:
                    try:
                        hard_linked = path.stat().st_nlink > 1
                    except OSError as exc:
                        qa.add(SEV_ERROR, "package_path_unreadable",
                               f"Cannot inspect package path {relative}: {exc}")
                        hard_linked = False
                    if hard_linked:
                        qa.add(SEV_ERROR, "package_hard_link",
                               f"Package file has multiple hard links: {relative}")
                inspect_streams(path, relative)

        inventory_entries = [current_path / name for name in filenames]
        inventory_entries.extend(redirect_dirs)
        for path in inventory_entries:
            relative = path.relative_to(root).as_posix()
            key = _path_key(relative)
            if (key in _METADATA_PATHS or key in expected
                    or _within_manifested_dir(key, expected_dirs)):
                continue
            extra += 1
            qa.add(SEV_WARNING, "package_file_extra",
                   f"File is not listed in manifest.csv: {relative}")

    qa.add(SEV_INFO, "package_verification_complete",
           f"Verified {verified} of {len(expected)} manifest destinations; "
           f"{extra} extra files")
    return result(len(rows), len(expected), verified, extra)
