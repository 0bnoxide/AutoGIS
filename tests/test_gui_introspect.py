"""GUI introspection layer (ADR-0052): every leaf command must map to a
form-field list without errors, and the hardcoded XOR_PAIRS table must
resolve to real parameter names (drift guard against option renames)."""

import click

from autogis.adapters.param_types import CommaList, IsoDate, SuggestedChoice
from autogis.adapters.gui.introspect import LABEL_OVERRIDES, XOR_PAIRS, introspect_cli

KINDS = {"text", "int", "float", "flag", "choice", "path", "date", "multichoice"}


def _by_label():
    return {form.label: form for form in introspect_cli()}


def test_walk_covers_every_leaf_command_without_errors():
    forms = introspect_cli()
    # ~105 leaf commands today; floor rather than exact count so the suite
    # doesn't break every time a tool ships.
    assert len(forms) >= 100
    labels = {form.label for form in forms}
    assert "harvest" in labels  # root-level leaf
    assert "envmon reconcile-locations" in labels
    assert "agol sync-to-gdb" in labels
    # sub-subgroup leaves are reached
    assert "envmon manage-callout-overrides lock" in labels
    for form in forms:
        for field in form.fields:
            assert field.kind in KINDS, (form.label, field.name, field.kind)
            if field.kind == "choice":
                assert field.choices, (form.label, field.name)
            if field.kind != "path":
                assert field.is_path_output is False


def test_field_mapping_spot_checks():
    forms = _by_label()

    fields = {f.name: f for f in forms["envmon reconcile-locations"].fields}
    assert fields["site_config"].kind == "path"
    assert fields["site_config"].is_path_output is False  # exists=True -> open
    assert fields["site_config"].required is True
    assert fields["threshold"].kind == "float"
    assert fields["gdb"].kind == "flag"
    assert fields["fail_on"].kind == "choice"
    assert fields["fail_on"].choices == ("error", "warning")
    assert fields["fail_on"].default == "error"
    assert fields["report"].kind == "path"
    assert fields["report"].is_path_output is True  # bare click.Path() -> save

    ready = {f.name: f for f in forms["envmon evaluate-readiness"].fields}
    assert ready["required_tools"].repeatable is True
    # Task 5: --required-tool now carries a SuggestedChoice vocabulary (an
    # editable/non-restricting combo), not a bare text field.
    assert ready["required_tools"].kind == "choice"
    assert ready["required_tools"].strict is False
    assert ready["required_tools"].choices

    transform = {
        f.name: f for f in forms["envmon transform-landxml"].fields
    }
    assert "source_unit" not in transform
    assert "target_unit" not in transform
    assert transform["geographic_transformation"].kind == "text"
    assert transform["z_scale"].kind == "float"


def test_is_dir_flags_directory_only_path_params():
    """A folder-only param (click.Path(file_okay=False)) is marked is_dir so a
    GUI opens a folder picker; a file/ambiguous path or any non-path field is
    not (defaults False, keeping the descriptor backward-compatible)."""
    forms = _by_label()

    # --edd_dir is declared file_okay=False -> directory picker
    edd = {f.name: f for f in forms["envmon batch-import-workbooks"].fields}
    assert edd["edd_dir"].kind == "path"
    assert edd["edd_dir"].is_dir is True

    # a bare click.Path() output (file_okay & dir_okay default True) is ambiguous
    recon = {f.name: f for f in forms["envmon reconcile-locations"].fields}
    assert recon["report"].kind == "path"
    assert recon["report"].is_dir is False
    # a non-path field is never a directory
    assert recon["threshold"].is_dir is False


def test_directory_options_open_a_folder_picker():
    forms = _by_label()
    directory_options = (
        ("envmon well-inspection-report", "output_dir"),
        ("envmon well-inspection-report", "harvest_dir"),
        ("envmon export-snapshot", "out_dir"),
        ("envmon create-sampling-event", "out_dir"),
        ("envmon export-wqx", "out_dir"),
        ("envmon export-survey-cad", "output_dir"),
        ("envmon condition-dem", "out_dir"),
        ("envmon gen-map-series", "out_dir"),
        ("envmon merge-event-results", "results_dir"),
        ("envmon build-report-package", "out_dir"),
        ("envmon batch-import-workbooks", "output_dir"),
        ("envmon export-civil3d", "out_dir"),
    )
    for label, name in directory_options:
        field = {f.name: f for f in forms[label].fields}[name]
        assert field.is_dir is True, (label, name)


def test_gdb_params_open_a_folder_picker():
    """Every gdb param is a bare click.Path() (file_okay left True), so the
    generic file_okay=False test can't see that a .gdb is a *directory*. The
    gdb-name recognition marks it is_dir so Browse opens a folder picker, not a
    save-file dialog (a .gdb's internal files aren't selectable there). Covers
    both param spellings and an input vs an output/created gdb."""
    forms = _by_label()

    def field(label, name):
        return {f.name: f for f in forms[label].fields}[name]

    # input gdb, arg named "gdb" (validate-db); output/created gdb (upgrade-schema)
    assert field("envmon validate-db", "gdb").is_dir is True
    assert field("envmon upgrade-schema", "gdb").is_dir is True
    # the "gdb_path" spelling (import-drone-products) is recognised too
    assert field("envmon import-drone-products", "gdb_path").is_dir is True


def test_xor_pairs_resolve_to_real_params():
    forms = _by_label()
    for label, pair in XOR_PAIRS.items():
        assert label in forms, f"XOR_PAIRS references unknown command {label!r}"
        names = {f.name for f in forms[label].fields}
        missing = set(pair) - names
        assert not missing, f"{label}: XOR params not on command: {missing}"
        group_id = "/".join(pair)
        marked = {f.name for f in forms[label].fields if f.xor_group == group_id}
        assert marked == set(pair), f"{label}: xor_group not set on both fields"


def test_label_overrides_win_over_title_case_heuristic():
    """Cryptic Click dest names (e.g. ``fmt``, ``out_dir``) get a friendlier
    curated label instead of a raw title-cased identifier."""
    forms = _by_label()

    fmt = {f.name: f for f in forms["envmon run-history"].fields}
    assert fmt["fmt"].label == LABEL_OVERRIDES["fmt"] == "Format"

    edd = {f.name: f for f in forms["envmon batch-import-workbooks"].fields}
    assert edd["edd_dir"].label == LABEL_OVERRIDES["edd_dir"] == "EDD Directory"


def test_unreachable_marking():
    reasons = {
        "envmon optimize-callouts": "ADR-0039 dead end",
        "envmon manage-callout-overrides lock": "ADR-0039 dead end",
    }
    forms = {form.label: form
             for form in introspect_cli(unreachable=reasons)}
    for label, reason in reasons.items():
        assert forms[label].unreachable_reason == reason
        assert forms[label].fields is not None  # still described, not omitted
    assert forms["envmon inspect"].unreachable_reason is None


def _only_field(param_decls, **kw):
    """Build a one-option command and return its non-help FormField."""
    @click.group()
    def root():
        pass

    @root.command("probe")
    @click.option(*param_decls, **kw)
    def probe(**_):
        pass

    form = next(f for f in introspect_cli(root) if f.path == ("probe",))
    return form.fields[0]


def test_comma_list_becomes_multichoice_with_choices():
    f = _only_field(["--features"], type=CommaList(("a", "b")), default="")
    assert f.kind == "multichoice"
    assert f.choices == ("a", "b")


def test_suggested_choice_is_a_non_strict_choice():
    f = _only_field(["--matrix"], type=SuggestedChoice(("GW", "SOIL")))
    assert f.kind == "choice"
    assert f.choices == ("GW", "SOIL")
    assert f.strict is False


def test_plain_click_choice_stays_strict():
    f = _only_field(["--fmt"], type=click.Choice(["a", "b"]))
    assert f.kind == "choice"
    assert f.strict is True


def test_iso_date_becomes_date_kind():
    f = _only_field(["--event-date"], type=IsoDate())
    assert f.kind == "date"
    assert f.allow_time is False


def test_iso_datetime_exposes_allow_time():
    f = _only_field(["--since"], type=IsoDate(allow_time=True))
    assert f.kind == "date"
    assert f.allow_time is True


def test_int_range_exposes_bounds():
    f = _only_field(["--limit"], type=click.IntRange(min=0, max=99))
    assert f.kind == "int"
    assert (f.minimum, f.maximum) == (0, 99)


def test_unbounded_int_has_no_bounds():
    f = _only_field(["--limit"], type=int)
    assert (f.minimum, f.maximum) == (None, None)


def test_nargs_defaults_to_one():
    f = _only_field(["--x"], type=str)
    assert f.nargs == 1


def test_nargs_greater_than_one_is_captured():
    f = _only_field(["--bbox"], nargs=4, type=float, default=None)
    assert f.nargs == 4


def test_real_bbox_and_profile_endpoints_are_nargs():
    """#351: download-dem --bbox and generate-subsurface-profile's
    --start/--end are the 3 real nargs>1 params in the CLI today."""
    forms = _by_label()
    bbox = {f.name: f for f in forms["envmon download-dem"].fields}["bbox"]
    assert bbox.nargs == 4
    ends = {f.name: f
           for f in forms["envmon generate-subsurface-profile"].fields}
    assert ends["start"].nargs == 2
    assert ends["end"].nargs == 2
