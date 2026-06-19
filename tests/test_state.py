from autogis.core.state import read_last_run, write_last_run


def test_read_missing_returns_none(tmp_path):
    assert read_last_run(str(tmp_path)) is None


def test_write_then_read(tmp_path):
    write_last_run(str(tmp_path), 1718000000000)
    assert read_last_run(str(tmp_path)) == 1718000000000


def test_write_creates_directory(tmp_path):
    nested = tmp_path / "deep" / "dir"
    write_last_run(str(nested), 42)
    assert read_last_run(str(nested)) == 42
