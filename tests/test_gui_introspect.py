"""GUI introspection layer (ADR-0052): every leaf command must map to a
form-field list without errors, and the hardcoded XOR_PAIRS table must
resolve to real parameter names (drift guard against option renames)."""

from autogis.adapters.gui.introspect import LABEL_OVERRIDES, XOR_PAIRS, introspect_cli

KINDS = {"text", "int", "float", "flag", "choice", "path"}


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
    assert ready["required_tools"].kind == "text"


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
