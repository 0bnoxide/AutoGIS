import pytest
from autogis.core.common.seen import FilesystemSeenIndex, SetSeenIndex


class TestSetSeenIndex:
    def test_empty_by_default(self):
        idx = SetSeenIndex()
        assert not idx.seen("a")
        assert len(idx) == 0

    def test_mark_then_seen(self):
        idx = SetSeenIndex()
        idx.mark("key1")
        assert idx.seen("key1")
        assert not idx.seen("key2")

    def test_initial_population(self):
        idx = SetSeenIndex(["x", "y", "z"])
        assert idx.seen("x")
        assert idx.seen("y")
        assert not idx.seen("w")
        assert len(idx) == 3

    def test_duplicate_mark_is_idempotent(self):
        idx = SetSeenIndex()
        idx.mark("dup")
        idx.mark("dup")
        assert len(idx) == 1

    def test_len_grows_with_marks(self):
        idx = SetSeenIndex()
        for i in range(5):
            idx.mark(str(i))
        assert len(idx) == 5


class TestFilesystemSeenIndex:
    def test_missing_path_not_seen(self, tmp_path):
        idx = FilesystemSeenIndex()
        assert not idx.seen(str(tmp_path / "nonexistent.txt"))

    def test_existing_file_is_seen(self, tmp_path):
        p = tmp_path / "exists.txt"
        p.write_text("hi")
        idx = FilesystemSeenIndex()
        assert idx.seen(str(p))

    def test_mark_is_noop(self, tmp_path):
        idx = FilesystemSeenIndex()
        path = str(tmp_path / "noop.txt")
        idx.mark(path)
        assert not idx.seen(path)

    def test_existing_directory_is_seen(self, tmp_path):
        idx = FilesystemSeenIndex()
        assert idx.seen(str(tmp_path))


def test_set_seen_index_satisfies_protocol():
    from autogis.core.common.seen import SeenIndex
    idx = SetSeenIndex()
    assert isinstance(idx, SeenIndex)


def test_filesystem_seen_index_satisfies_protocol():
    from autogis.core.common.seen import SeenIndex
    idx = FilesystemSeenIndex()
    assert isinstance(idx, SeenIndex)
