from dataclasses import dataclass

VALID_STATUSES = ("downloaded", "skipped", "failed")


@dataclass
class HarvestConfig:
    directory: str
    group_template: str
    filename_template: str
    item_id: str | None = None
    url: str | None = None
    where: str = "1=1"
    incremental: bool = False
    skip_existing: bool = True
    retries: int = 3
    backoff_seconds: float = 2

    def layer_ref(self) -> str:
        if self.url:
            return self.url
        if self.item_id:
            return self.item_id
        raise ValueError("HarvestConfig requires either url or item_id")


@dataclass
class AttachmentResult:
    objectid: int
    attachment_id: int
    original_name: str
    saved_path: str | None
    size: int | None
    status: str
    error: str | None = None
    # Explicit outcome axis (deltas H2): downloaded/skipped/failed. Distinct
    # from `status` so the summary view groups by disposition, not QA severity.
    disposition: str | None = None
    # Reserved provenance columns (deltas §5). Empty now; filled post-merge.
    checksum: str | None = None
    algorithm: str | None = None
    geometry: str | None = None
    source_table: str | None = None
    relationship_id: str | None = None


def summary_counts(results) -> dict:
    """Group results by disposition (falling back to status). deltas H2."""
    out = {s: 0 for s in VALID_STATUSES}
    for r in results:
        key = r.disposition or r.status
        if key in out:
            out[key] += 1
    return out


@dataclass
class RunSummary:
    """Thin back-compat shim over the disposition-based summary view."""
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0

    def record(self, status: str) -> None:
        if status not in VALID_STATUSES:
            raise ValueError(f"unknown status: {status}")
        setattr(self, status, getattr(self, status) + 1)

    @classmethod
    def from_counts(cls, counts: dict) -> "RunSummary":
        return cls(downloaded=counts.get("downloaded", 0),
                   skipped=counts.get("skipped", 0),
                   failed=counts.get("failed", 0))
