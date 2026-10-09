"""CLI YAML inputs are read-and-closed, not left to the garbage collector.

A bare ``open()`` inside ``yaml.safe_load(...)`` leaks the handle until GC:
a ResourceWarning in the suite, and a lingering lock on Windows for as long
as the process lives. ``build-survey-form`` is the command the suite flagged.
"""
import gc
import os
import warnings

from click.testing import CliRunner

from autogis.adapters.cli import autogis


def test_build_survey_form_closes_its_yaml_inputs(tmp_path):
    cfg = tmp_path / "site.yaml"
    cfg.write_text("site_id: S1\n", encoding="utf-8")
    empty = tmp_path / "empty.yaml"
    empty.write_text("{}\n", encoding="utf-8")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ResourceWarning)
        CliRunner().invoke(autogis, [
            "envmon", "build-survey-form",
            "--site", str(cfg), "--analytes", str(empty),
            "--event", str(empty), "--out", str(tmp_path / "form.xlsx"),
        ])
        gc.collect()

    leaked = [w for w in caught if issubclass(w.category, ResourceWarning)]
    assert not leaked, [str(w.message) for w in leaked]


def _bad_inputs(tmp_path):
    """Malformed YAML and a directory: both pass ``click.Path(exists=True)``."""
    bad = tmp_path / "bad.yaml"
    bad.write_text("site_id: [unclosed\n", encoding="utf-8")
    a_dir = tmp_path / "a dir é"
    a_dir.mkdir()
    return bad, a_dir


def test_build_survey_form_bad_yaml_is_a_clean_error(tmp_path):
    empty = tmp_path / "empty.yaml"
    empty.write_text("{}\n", encoding="utf-8")
    for bad in _bad_inputs(tmp_path):
        result = CliRunner().invoke(autogis, [
            "envmon", "build-survey-form",
            "--site", str(bad), "--analytes", str(empty),
            "--event", str(empty), "--out", str(tmp_path / "form.xlsx"),
        ])
        assert result.exit_code == 1, result.output
        assert result.exception is None or isinstance(result.exception,
                                                      SystemExit)
        assert "cannot read" in result.output and str(bad) in result.output


def test_validate_survey_form_bad_yaml_is_a_clean_error(tmp_path):
    from autogis.core.envmon.survey123_form_builder import build_xlsform
    form = tmp_path / "form.xlsx"
    build_xlsform({"site_id": "S1"}, {}, {}).save(form)
    for bad in _bad_inputs(tmp_path):
        result = CliRunner().invoke(autogis, [
            "envmon", "validate-survey-form", str(form),
            "--site-config", str(bad),
        ])
        assert result.exit_code == 1, result.output
        assert result.exception is None or isinstance(result.exception,
                                                      SystemExit)
        assert "cannot read" in result.output and str(bad) in result.output


def _build(tmp_path, site, analytes, event, out=None):
    return CliRunner().invoke(autogis, [
        "envmon", "build-survey-form",
        "--site", str(site), "--analytes", str(analytes),
        "--event", str(event), "--out", str(out or tmp_path / "form.xlsx"),
    ])


def test_build_survey_form_rejects_empty_and_non_mapping_yaml(tmp_path):
    """#549: an empty or list-shaped required input must fail loudly. Treating
    an empty file as {} would write a form with no site, wells or analytes
    and exit 0."""
    obj = tmp_path / "obj.yaml"
    obj.write_text("{}\n", encoding="utf-8")
    empty = tmp_path / "empty.yaml"
    empty.write_text("", encoding="utf-8")
    a_list = tmp_path / "list.yaml"
    a_list.write_text("- 1\n- 2\n", encoding="utf-8")
    for args, bad in [((empty, obj, obj), empty), ((a_list, obj, obj), a_list),
                      ((obj, a_list, obj), a_list), ((obj, obj, empty), empty)]:
        result = _build(tmp_path, *args)
        assert result.exit_code == 1, result.output
        assert isinstance(result.exception, SystemExit), result.exception
        assert "expected a YAML mapping" in result.output
        assert str(bad) in result.output
        assert not (tmp_path / "form.xlsx").exists()


def test_build_survey_form_out_directory_is_a_usage_error(tmp_path):
    obj = tmp_path / "obj.yaml"
    obj.write_text("{}\n", encoding="utf-8")
    out_dir = tmp_path / "out dir"
    out_dir.mkdir()
    result = _build(tmp_path, obj, obj, obj, out=out_dir)
    assert result.exit_code == 2, result.output
    assert isinstance(result.exception, SystemExit), result.exception
    assert "is a directory" in result.output


def test_validate_survey_form_empty_config_still_means_not_supplied(tmp_path):
    from autogis.core.envmon.survey123_form_builder import build_xlsform
    form = tmp_path / "form.xlsx"
    build_xlsform({"site_id": "S1"}, {}, {}).save(form)
    empty = tmp_path / "empty.yaml"
    empty.write_text("", encoding="utf-8")
    a_list = tmp_path / "list.yaml"
    a_list.write_text("- 1\n", encoding="utf-8")

    ok = CliRunner().invoke(autogis, [
        "envmon", "validate-survey-form", str(form), "--event-config", str(empty)])
    assert not isinstance(ok.exception, AttributeError), ok.exception

    for opt in ("--site-config", "--event-config", "--analyte-dict"):
        result = CliRunner().invoke(autogis, [
            "envmon", "validate-survey-form", str(form), opt, str(a_list)])
        assert result.exit_code == 1, result.output
        assert isinstance(result.exception, SystemExit), result.exception
        assert "expected a YAML mapping" in result.output


def test_build_survey_form_creates_missing_out_directory(tmp_path):
    """#550 (owner decision: option B): an --out in a missing directory
    creates that directory instead of escaping as a raw FileNotFoundError."""
    obj = tmp_path / "obj.yaml"
    obj.write_text("{}\n", encoding="utf-8")
    out = tmp_path / "new dir é" / "nested" / "form.xlsx"
    result = _build(tmp_path, obj, obj, obj, out=out)
    assert result.exit_code == 0, result.output
    assert out.is_file()


def test_build_survey_form_unwritable_out_is_a_clean_error(tmp_path):
    """Other write failures (here: a parent that is a regular file) still
    surface as a clean error, not a traceback."""
    obj = tmp_path / "obj.yaml"
    obj.write_text("{}\n", encoding="utf-8")
    a_file = tmp_path / "a_file"
    a_file.write_text("", encoding="utf-8")
    out = a_file / "form.xlsx"
    result = _build(tmp_path, obj, obj, obj, out=out)
    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit), result.exception
    assert "cannot write" in result.output and str(out) in result.output


class _DiskFullFile:
    """A real staging file whose write lands partially, then fails (ENOSPC)."""

    def __init__(self, path, mode):
        self._fh = open(path, mode)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._fh.close()

    def write(self, data):
        self._fh.write(data[:16])
        raise OSError(28, "No space left on device")


def test_build_survey_form_failed_write_keeps_existing_form(tmp_path, monkeypatch):
    """#551: a write that dies partway must not truncate the existing form or
    leave its stage behind. The stage handle is closed before cleanup, so this
    also holds natively on Windows. A hardlink to the form at the old fixed
    stage name (#554) must not become the write target."""
    import autogis.adapters.cli as cli

    obj = tmp_path / "obj.yaml"
    obj.write_text("{}\n", encoding="utf-8")
    out = tmp_path / "form.xlsx"
    out.write_bytes(b"previous form")
    try:
        os.link(out, tmp_path / "form.xlsx.tmp")
    except OSError:  # filesystem without hardlinks: the rest still applies
        pass

    def disk_full_open(path, mode="r", *a, **kw):
        if str(path).endswith(".tmp"):
            return _DiskFullFile(path, mode)
        return open(path, mode, *a, **kw)

    monkeypatch.setattr(cli, "open", disk_full_open, raising=False)
    result = _build(tmp_path, obj, obj, obj, out=out)
    assert result.exit_code == 1, result.output
    assert "No space left on device" in result.output
    assert out.read_bytes() == b"previous form"
    leftover = {p.name for p in tmp_path.iterdir()} - {"form.xlsx", "obj.yaml"}
    assert leftover <= {"form.xlsx.tmp"}, leftover


def test_build_survey_form_never_touches_files_it_did_not_create(tmp_path):
    """#554: an input (or any file) at a stage-like sibling path survives."""
    site = tmp_path / "form.xlsx.tmp"
    site.write_text("site_id: S1\n", encoding="utf-8")
    obj = tmp_path / "obj.yaml"
    obj.write_text("{}\n", encoding="utf-8")
    out = tmp_path / "form.xlsx"
    result = _build(tmp_path, site, obj, obj, out=out)
    assert result.exit_code == 0, result.output
    assert site.read_text(encoding="utf-8") == "site_id: S1\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "form.xlsx", "form.xlsx.tmp", "obj.yaml"]


def test_build_survey_form_overlapping_runs_publish_their_own_form(
        tmp_path, monkeypatch):
    """#554: run B saves and publishes while run A sits between its save and
    its publish. Each run must publish its own workbook, from its own stage."""
    from openpyxl import load_workbook

    obj = tmp_path / "obj.yaml"
    obj.write_text("{}\n", encoding="utf-8")
    site_a = tmp_path / "a.yaml"
    site_a.write_text("site_id: SITE_A\n", encoding="utf-8")
    site_b = tmp_path / "b.yaml"
    site_b.write_text("site_id: SITE_B\n", encoding="utf-8")
    out = tmp_path / "form.xlsx"

    real_replace = os.replace
    stages, results = [], []

    def interleaved_replace(src, dst):
        stages.append(str(src))
        if len(stages) == 1:  # A is about to publish: run B to completion
            results.append(_build(tmp_path, site_b, obj, obj, out=out))
            assert load_workbook(out)["settings"]["B2"].value == "site_b_sampling"
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", interleaved_replace)
    result_a = _build(tmp_path, site_a, obj, obj, out=out)
    assert result_a.exit_code == 0, result_a.output
    assert results[0].exit_code == 0, results[0].output
    assert len(set(stages)) == 2, stages
    assert load_workbook(out)["settings"]["B2"].value == "site_a_sampling"
    assert not [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
