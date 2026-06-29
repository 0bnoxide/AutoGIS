# BuildReportFigurePackage Design

**Date:** 2026-06-28
**Status:** Approved
**Tool:** BuildReportFigurePackage (Phase 3 / Tool 5.7)
**Priority:** MEDIUM — standardizes deliverable folder structure; simplifies QC before submission

---

## Problem

After figures are generated and approved, the analyst assembles a deliverable
folder: PDFs, PNGs, data tables, QA reports. Currently the folder structure
is ad hoc — different analysts name subfolders differently, include different
files, and forget to include the QA summary or data manifest. Reviewers and
clients receiving the deliverable can't tell what version of data produced the
figures, or which files are the authoritative deliverable vs. working copies.

---

## Approach

**Chosen:** Deliverable manifest builder + folder assembler. Reads a YAML
deliverable spec (figure PDFs, data CSVs, QA reports, optional GDB path)
and assembles a standardized output folder:

```
<out_dir>/
  figures/          ← PDF and PNG figure files
  data/             ← analytical results, max-result, compliance tables
  qa/               ← QA reports (markdown or CSV)
  manifest.csv      ← file list with sha256 and role
  README.txt        ← auto-generated event summary
```

Files are copied (not moved) to preserve originals. The manifest is the
authoritative record of what's in the deliverable.

**Rejected: ZIP archive output.** ZIP makes revision harder. A folder is
easier to QC, diff, and selectively update.

**Rejected: Requiring all inputs exist.** Missing files → WARNING in QA;
manifest entry gets `status=missing`. Delivery is permitted with warnings.

---

## Architecture

```
autogis/
  core/envmon/
    report_figure_package.py       ← NEW
  adapters/
    cli.py                         ← add build-report-package command (headless)
tests/envmon/
  test_report_figure_package.py    ← NEW
```

---

## Public API (`report_figure_package.py`)

```python
DELIVERABLE_ROLES = (
    "figure_pdf", "figure_png", "data_csv",
    "qa_report", "compliance_table", "boring_log",
    "source_gdb", "coc", "other",
)

@dataclass
class DeliverableFile:
    source_path: str     # original path (may not exist)
    dest_subdir: str     # figures | data | qa | root
    role: str            # from DELIVERABLE_ROLES
    sha256: str          # empty if missing
    status: str          # copied | missing | error

@dataclass
class FigurePackageResult:
    out_dir: Path
    manifest_path: Path
    files: list[DeliverableFile]
    copied_count: int
    missing_count: int
    qa: QACollector

def load_deliverable_spec(spec_path: Path) -> list[dict]:
    """
    Read YAML spec:
    files:
      - path: output/figures/Fig-1A.pdf
        role: figure_pdf
      - path: output/data/merged_results.csv
        role: data_csv
    """

def assemble_figure_package(
    spec_entries: list[dict],
    out_dir: Path,
    *,
    site_id: str = "",
    event_label: str = "",
    qa: QACollector | None = None,
) -> FigurePackageResult:
    """Copy files to out_dir subfolders; write manifest.csv + README.txt."""

def write_package_manifest(
    files: list[DeliverableFile],
    manifest_path: Path,
) -> None:
```

---

## Deliverable Spec YAML Example

```yaml
site_id: H281-Eureka
event_label: Q1-2026
files:
  - path: output/figures/Fig-1A_GW_Benzene.pdf
    role: figure_pdf
  - path: output/figures/Fig-1A_GW_Benzene.png
    role: figure_png
  - path: output/data/merged_results_Q1-2026.csv
    role: data_csv
  - path: output/qa/qa_report.md
    role: qa_report
```

---

## CLI Command

```
autogis envmon build-report-package \
  --spec <deliverable_spec.yaml> \
  --out-dir <deliverable/> \
  [--site <site_id>] \
  [--event-label <label>] \
  [--report <qa.md>]
```

Headless.

---

## Test Strategy

`tests/envmon/test_report_figure_package.py` — arcpy-free:

1. `load_deliverable_spec` parses YAML into list of dicts with path + role
2. `assemble_figure_package` copies existing file to correct subfolder
3. `figures/` subfolder created for `figure_pdf` role
4. `data/` subfolder for `data_csv`; `qa/` for `qa_report`
5. Missing source file → `status=missing`, WARNING in QA, not an error
6. `manifest.csv` written with sha256 of copied files
7. `README.txt` written to out_dir root
8. `copied_count` + `missing_count` sum equals total spec entries
