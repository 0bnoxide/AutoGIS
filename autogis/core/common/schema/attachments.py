# autogis/core/common/schema/attachments.py
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import ClassVar, Optional


@dataclass
class AttachmentIndex:
    """One harvested AGOL attachment, joinable from envmon records (tool 6.5).

    Populated from the attachment harvester's manifest (``core/harvest/``);
    field names map from ``harvest.models.AttachmentResult``.
    """
    table_name: ClassVar[str] = "AttachmentIndex"
    attachment_id: int
    related_table: str          # source feature layer/table of the parent record
    related_id: str             # parent OBJECTID in that table
    original_name: str = ""
    local_path: str = ""
    attachment_type: str = ""   # photo | document | spreadsheet | other
    size_bytes: Optional[int] = None
    checksum: str = ""
    status: str = ""            # downloaded | skipped | failed
    synced_date: Optional[datetime] = None

    def to_row(self) -> dict:
        return asdict(self)
