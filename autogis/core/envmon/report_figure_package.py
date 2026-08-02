"""report_figure_package.py — deliverable folder assembler with manifest."""
from __future__ import annotations

import csv
import hashlib
import ntpath
import os
import re
import stat
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..common.qa import QACollector, QARecord, SEV_INFO, SEV_WARNING

DELIVERABLE_ROLES = (
    "figure_pdf", "figure_png", "data_csv",
    "qa_report", "compliance_table", "boring_log",
    "source_gdb", "coc", "other",
)

_ROLE_SUBDIR = {
    "figure_pdf": "figures", "figure_png": "figures",
    "data_csv": "data", "compliance_table": "data",
    "qa_report": "qa", "boring_log": "data",
    "source_gdb": "data", "coc": "data", "other": ".",
}

_MANIFEST_FIELDS = ["source_path", "dest_path", "role", "sha256", "status"]

_WIN32_INVALID_COMPONENT = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_DOS_SHORT_NAME = re.compile(
    r"^(?=[^.]{1,8}(?:\.|$))[^. ]{1,6}~[0-9]{1,6}(?:\.[^. ]{1,3})?$",
    re.IGNORECASE,
)
_WIN32_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL", "CLOCK$", "CONIN$", "CONOUT$",
    *(f"COM{n}" for n in "123456789¹²³"),
    *(f"LPT{n}" for n in "123456789¹²³"),
}


@dataclass
class DeliverableFile:
    source_path: str
    dest_subdir: str
    role: str
    sha256: str
    status: str


@dataclass
class FigurePackageResult:
    out_dir: Path
    manifest_path: Path
    files: list
    copied_count: int
    missing_count: int
    qa: QACollector


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_deliverable_spec(spec_path: Path) -> list:
    import yaml
    # safe_load returns None for an empty / comment-only file — fall back to {}.
    data = yaml.safe_load(Path(spec_path).read_text(encoding="utf-8")) or {}
    return data.get("files", [])


def _validate_windows_destination_component(name: str) -> None:
    """Reject names Win32 rejects or aliases to a reserved device."""
    if (not name or name in {".", ".."}
            or _WIN32_INVALID_COMPONENT.search(name)
            or _DOS_SHORT_NAME.fullmatch(name)
            or name.endswith((".", " "))
            or name.split(".", 1)[0].upper() in _WIN32_RESERVED_NAMES):
        raise ValueError(f"Invalid Windows destination component: {name!r}")


def _is_link_or_reparse(path: Path) -> bool:
    """Return whether an existing path redirects filesystem writes."""
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise ValueError(f"Cannot inspect package destination {path}: {exc}") from exc
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return (stat.S_ISLNK(metadata.st_mode)
            or bool(getattr(metadata, "st_file_attributes", 0) & reparse_flag))


def _named_streams(path: Path) -> list[str]:
    """Return non-default NTFS stream names attached to *path*."""
    if os.name != "nt":
        return []

    import ctypes
    from ctypes import wintypes

    class FindStreamData(ctypes.Structure):
        _fields_ = [
            ("stream_size", ctypes.c_int64),
            ("stream_name", wintypes.WCHAR * 296),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    find_first = kernel32.FindFirstStreamW
    find_first.argtypes = [wintypes.LPCWSTR, ctypes.c_int,
                           ctypes.POINTER(FindStreamData), wintypes.DWORD]
    find_first.restype = wintypes.HANDLE
    find_next = kernel32.FindNextStreamW
    find_next.argtypes = [wintypes.HANDLE, ctypes.POINTER(FindStreamData)]
    find_next.restype = wintypes.BOOL
    find_close = kernel32.FindClose
    find_close.argtypes = [wintypes.HANDLE]
    find_close.restype = wintypes.BOOL

    data = FindStreamData()
    handle = find_first(str(Path(path).absolute()), 0, ctypes.byref(data), 0)
    if handle == ctypes.c_void_p(-1).value:
        error = ctypes.get_last_error()
        # No streams / a filesystem without stream support cannot hide ADS.
        if error in {1, 38, 50, 87}:
            return []
        raise ctypes.WinError(error)

    streams: list[str] = []
    try:
        while True:
            name = data.stream_name
            if name and name.upper() != "::$DATA":
                streams.append(name)
            if find_next(handle, ctypes.byref(data)):
                continue
            error = ctypes.get_last_error()
            if error != 38:  # ERROR_HANDLE_EOF
                raise ctypes.WinError(error)
            return streams
    finally:
        find_close(handle)


def _reject_link_or_reparse(path: Path) -> None:
    if _is_link_or_reparse(path):
        raise ValueError(
            f"Package destination is a symlink or reparse point: {path}")
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise ValueError(f"Cannot inspect package destination {path}: {exc}") from exc
    if stat.S_ISREG(metadata.st_mode) and metadata.st_nlink > 1:
        raise ValueError(f"Package destination is a hard link: {path}")


def _validate_package_destinations(spec_entries: list, out_dir: Path) -> None:
    """Reject unsafe or colliding destinations before package writes begin."""
    if ".." in out_dir.parts:
        raise ValueError("Package output path must not contain '..'")
    seen = {
        ntpath.normcase("manifest.csv"): "generated manifest.csv",
        ntpath.normcase("README.txt"): "generated README.txt",
    }
    destinations = {out_dir / "manifest.csv", out_dir / "README.txt"}
    for entry in spec_entries:
        src = Path(entry.get("path", ""))
        _validate_windows_destination_component(src.name)
        if src.is_file():
            try:
                streams = _named_streams(src)
            except OSError as exc:
                raise ValueError(
                    f"Cannot inspect named streams on source {src}: {exc}") from exc
            if streams:
                raise ValueError(
                    f"Source has NTFS named streams that cannot be packaged: "
                    f"{src} ({', '.join(streams)})")
        subdir = _ROLE_SUBDIR.get(entry.get("role", "other"), ".")
        dest = str(Path(subdir) / src.name)
        # Packages move between Windows and POSIX hosts.  Match Windows' path
        # identity on every host so case/separator variants cannot overwrite.
        key = ntpath.normcase(ntpath.normpath(dest))
        if key in seen:
            raise ValueError(
                f"Deliverable destination collision: {seen[key]!r} and "
                f"{str(src)!r} both resolve to {dest!r}")
        seen[key] = str(src)
        dest_dir = out_dir / subdir if subdir != "." else out_dir
        destinations.update((dest_dir, dest_dir / src.name))

    # Resolve no links: inspect the lexical output path and every existing
    # ancestor so mkdir/copy/open cannot escape through a pre-existing redirect.
    absolute_out = Path(os.path.abspath(out_dir))
    for candidate in (absolute_out, *absolute_out.parents):
        _reject_link_or_reparse(candidate)
    for destination in destinations:
        _reject_link_or_reparse(destination)


def assemble_figure_package(
    spec_entries: list,
    out_dir: Path,
    *,
    site_id: str = "",
    event_label: str = "",
    qa: Optional[QACollector] = None,
) -> FigurePackageResult:
    if qa is None:
        qa = QACollector()
    out_dir = Path(out_dir)
    _validate_package_destinations(spec_entries, out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    files: list[DeliverableFile] = []
    copied = missing = 0

    for entry in spec_entries:
        src_str = entry.get("path", "")
        role = entry.get("role", "other")
        subdir_name = _ROLE_SUBDIR.get(role, ".")
        src = Path(src_str)

        if not src.exists():
            qa.add(QARecord(SEV_WARNING, "missing_deliverable",
                            f"Source not found: {src_str}"))
            files.append(DeliverableFile(
                source_path=src_str, dest_subdir=subdir_name,
                role=role, sha256="", status="missing",
            ))
            missing += 1
            continue

        dest_dir = out_dir / subdir_name if subdir_name != "." else out_dir
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src.name
        shutil.copy2(str(src), str(dest))
        sha = _sha256_file(dest)
        files.append(DeliverableFile(
            source_path=src_str, dest_subdir=subdir_name,
            role=role, sha256=sha, status="copied",
        ))
        copied += 1

    # Write manifest
    manifest_path = out_dir / "manifest.csv"
    write_package_manifest(files, manifest_path)

    # Write README
    readme = out_dir / "README.txt"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    readme.write_text(
        f"Report Figure Package\n"
        f"Site: {site_id or '(not specified)'}\n"
        f"Event: {event_label or '(not specified)'}\n"
        f"Generated: {now}\n"
        f"Files: {copied} copied, {missing} missing\n"
        f"See manifest.csv for file inventory.\n",
        encoding="utf-8",
    )

    qa.add(QARecord(SEV_INFO, "package_assembled",
                    f"{copied} files copied, {missing} missing -> {out_dir}"))

    return FigurePackageResult(
        out_dir=out_dir, manifest_path=manifest_path,
        files=files, copied_count=copied, missing_count=missing, qa=qa,
    )


def write_package_manifest(files: list, manifest_path: Path) -> None:
    with Path(manifest_path).open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=_MANIFEST_FIELDS)
        w.writeheader()
        for f in files:
            dest = str(Path(f.dest_subdir) / Path(f.source_path).name)
            w.writerow({
                "source_path": f.source_path, "dest_path": dest,
                "role": f.role, "sha256": f.sha256, "status": f.status,
            })
