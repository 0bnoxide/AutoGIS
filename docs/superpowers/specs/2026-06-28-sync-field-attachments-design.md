# SyncFieldAttachments Design

**Date:** 2026-06-28
**Status:** Approved
**Tool:** SyncFieldAttachments (Tool 6.5)
**Priority:** MEDIUM — pulls field photos/forms off AGOL into a catalogued local store
**Runtime:** CLI ✓ / AGOL ✓ — `arcgis` (cloud extra), never arcpy

---

## Problem

Field crews attach photos, well-condition images, sampling forms, and lab PDFs to
Survey123/Field Maps feature layers. To use them in reports (e.g.
`GenerateWellInspectionPhotoReport`, 7.4) they must be downloaded and indexed locally.
Today that's manual. The attachment *harvester* already exists for a different domain
(`core/harvest/`), but nothing pulls **AGOL feature-layer attachments** into an envmon
attachment index.

---

## Approach

**Chosen:** An AGOL attachment downloader on the injected-`gis` / lazy-`arcgis` contract.
For a hosted layer it enumerates attachments per feature, downloads each into a structured
folder (`<site>/<event>/<location>/`), and writes an attachment index table linking each
file to its location/feature/event with a SHA-256 hash (reusing `seen.py`, so re-runs are
idempotent and skip unchanged files). Index rows are envmon-side records the photo-report
tool consumes.

**Rejected: reusing `core/harvest/` directly.** That harvester targets file-system/email
sources with its own config (`HarvestConfig`); AGOL REST attachments are a different
source. This tool shares the *hashing/seen-index* and the index-table shape, not the
harvest pipeline.

**Rejected: storing attachments inside the gdb.** Files land on disk; the index table
holds paths + hashes (same philosophy as `RegisterSourceDocuments`, 2.5).

**Rejected: `GIS()` in core.** Injected; tests use a fake gis returning canned attachment
metadata + bytes.

---

## Architecture

```
autogis/
  core/common/
    seen.py                   ← EXISTS (SHA-256 + skip-unchanged reused)
  core/agol/
    sync_attachments.py       ← NEW (injected gis, lazy arcgis)
  adapters/
    cli.py                    ← add `agol sync-attachments` command
tests/
  test_agol_sync_attachments.py  ← NEW (fake gis)
```

---

## Public API (`sync_attachments.py`)

```python
@dataclass
class AttachmentRecord:
    location_id: str
    feature_oid: int
    event_date: str
    file_name: str
    local_path: str
    sha256: str
    content_type: str

@dataclass
class SyncResult:
    records: list[AttachmentRecord]
    downloaded: int
    skipped_unchanged: int
    qa: QACollector

def sync_field_attachments(
    gis,                          # injected GIS
    *,
    layer_item_id: str,
    out_dir: Path,
    site_id: str,
    location_field: str = "LocationID",
    event_field: str = "EventDate",
    existing_index: list[AttachmentRecord] | None = None,
) -> SyncResult:
    """Download + index hosted-layer attachments; skip files whose hash is unchanged."""

def write_attachment_index(records: list[AttachmentRecord], path: Path) -> Path: ...
```

---

## CLI Command

```
autogis agol sync-attachments \
  --profile <agol_profile.yaml> \
  --layer-item <itemid> \
  --site-id H281 \
  --out-dir <attachments/> \
  --index <attachment_index.csv> \
  [--report <sync_qa.md>]
```

---

## Test Strategy

`tests/test_agol_sync_attachments.py` — fake injected `gis`:

1. Module imports without `arcgis` installed.
2. Two features with one attachment each → two `AttachmentRecord`s, correct folders.
3. Re-sync with an unchanged hash → `skipped_unchanged == 1`, no re-download.
4. Changed attachment hash → re-downloaded.
5. Index round-trips through `write_attachment_index`/load.
6. Feature missing the location field → WARNING, attachment still downloaded under `unknown`.
