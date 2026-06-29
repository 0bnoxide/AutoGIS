# RegisterSourceDocuments Design

**Date:** 2026-06-28
**Status:** Approved
**Tool:** RegisterSourceDocuments (Tool 2.5)
**Priority:** MEDIUM — gives the system auditability ("which workbook produced this map?")

---

## Problem

Maps, tables, and database records trace back to source artifacts — lab report PDFs,
workbooks, field forms — but nothing records the link. When a reviewer asks "which
workbook produced this benzene value / this figure?", the answer is tribal knowledge.
There is no document registry tying source files to import batches.

---

## Approach

**Chosen:** A document registry table + a register/scan command. The command takes a
folder (or explicit file list) plus metadata, hashes each file (SHA-256, the same
hashing already used by the harvester/seen-index, `seen.py`), and writes one
`SourceDocument` record per file. Re-running is idempotent: a file whose hash already
exists updates its metadata rather than duplicating. The registry is a CSV/table keyed
by `DocumentID` (deterministic from hash), enabling later joins from import batches and
figure exports.

**Rejected: storing the documents.** The registry stores *paths/URLs + hashes +
metadata*, not the bytes. Move/copy is out of scope.

**Rejected: a new hashing implementation.** Reuse the seen-index SHA-256 helper so a
document's identity is consistent with the harvester's.

This is a pure-core, headless table writer — no arcpy, no openpyxl required (CSV
registry; openpyxl only if an `.xlsx` registry is requested).

---

## Architecture

```
autogis/
  core/common/
    schema/envmon.py          ← add SourceDocument dataclass (or new schema/docs.py)
    seen.py                   ← EXISTS (SHA-256 hashing reused)
    records_csv.py            ← EXISTS (registry read/write)
  core/envmon/
    source_documents.py       ← NEW
  adapters/
    cli.py                    ← add register-documents command (headless)
tests/envmon/
  test_source_documents.py    ← NEW
```

---

## Public API (`source_documents.py`)

```python
@dataclass
class SourceDocument:
    document_id: str          # derived from hash (stable)
    site_id: str
    event_date: str
    document_type: str        # workbook | lab_pdf | field_form | map_output | edd | other
    path_or_url: str
    sha256: str
    import_batch_id: str | None
    reviewed_by: str | None
    review_status: str        # unreviewed | reviewed | rejected

@dataclass
class RegisterResult:
    registered: list[SourceDocument]
    updated: int
    added: int
    qa: QACollector

def register_documents(
    files: list[Path],
    *,
    site_id: str,
    event_date: str,
    document_type: str,
    existing: list[SourceDocument] | None = None,
    import_batch_id: str | None = None,
) -> RegisterResult:
    """Hash + register each file; update-in-place when hash already present."""

def load_registry(path: Path) -> list[SourceDocument]: ...
def write_registry(docs: list[SourceDocument], path: Path) -> Path: ...
```

---

## CLI Command

```
autogis envmon register-documents \
  --files <folder/ or file...> \
  --site-id H281 \
  --event-date 2026-06-15 \
  --type workbook \
  --registry <source_documents.csv> \
  [--import-batch-id H281_2026Q2] \
  [--reviewed-by "A. Analyst"] \
  [--report <register_qa.md>]
```

Headless. Idempotent against the existing registry CSV.

---

## Test Strategy

`tests/envmon/test_source_documents.py` — arcpy-free:

1. Registering 3 files yields 3 records with distinct `document_id`s.
2. `document_id` is deterministic from file hash (re-register → same id).
3. Re-registering an unchanged file updates metadata, `added == 0`, `updated == 1`.
4. A changed file (new hash) registers as a new document.
5. Missing file path → QA error, skipped.
6. `load_registry` round-trips `write_registry` output.
7. `review_status` defaults to `unreviewed`.
