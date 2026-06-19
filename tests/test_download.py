import os
import pytest
from autogis.core.download import download_one


class FakeAttachments:
    def __init__(self, fail_times=0, returns_list=False):
        self.fail_times = fail_times
        self.calls = 0
        self.returns_list = returns_list

    def download(self, oid, attachment_id, save_path):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("network blip")
        tmp = os.path.join(save_path, f"raw_{attachment_id}.bin")
        with open(tmp, "wb") as fh:
            fh.write(b"data")
        return [tmp] if self.returns_list else tmp


class FakeLayer:
    def __init__(self, attachments):
        self.attachments = attachments


def test_download_success(tmp_path):
    layer = FakeLayer(FakeAttachments())
    dest = tmp_path / "G" / "final.jpg"
    download_one(layer, 1, 10, str(dest), retries=3, backoff_seconds=0,
                 sleep=lambda s: None)
    assert dest.exists()
    assert dest.read_bytes() == b"data"


def test_download_normalizes_list_return(tmp_path):
    layer = FakeLayer(FakeAttachments(returns_list=True))
    dest = tmp_path / "final.jpg"
    download_one(layer, 1, 10, str(dest), retries=3, backoff_seconds=0,
                 sleep=lambda s: None)
    assert dest.exists()


def test_download_retries_then_succeeds(tmp_path):
    attachments = FakeAttachments(fail_times=2)
    layer = FakeLayer(attachments)
    dest = tmp_path / "final.jpg"
    download_one(layer, 1, 10, str(dest), retries=3, backoff_seconds=0,
                 sleep=lambda s: None)
    assert dest.exists()
    assert attachments.calls == 3


def test_download_exhausts_retries_and_raises(tmp_path):
    attachments = FakeAttachments(fail_times=99)
    layer = FakeLayer(attachments)
    dest = tmp_path / "final.jpg"
    with pytest.raises(RuntimeError):
        download_one(layer, 1, 10, str(dest), retries=2, backoff_seconds=0,
                     sleep=lambda s: None)
    assert attachments.calls == 3  # initial + 2 retries
