"""report_figure_package.py — deliverable folder assembler with manifest."""
from __future__ import annotations

import csv
import hashlib
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
    data = yaml.safe_load(Path(spec_path).read_text(encoding="utf-8"))
    return data.get("files", [])


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
                    f"{copied} files copied, {missing} missing → {out_dir}"))

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
