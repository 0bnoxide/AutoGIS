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


@dataclass
class RunSummary:
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0

    def record(self, status: str) -> None:
        if status not in VALID_STATUSES:
            raise ValueError(f"unknown status: {status}")
        setattr(self, status, getattr(self, status) + 1)
