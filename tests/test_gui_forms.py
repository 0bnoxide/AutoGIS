"""Form-values -> Step builder (ADR-0056).

Synthetic CommandForm/FormField fixtures cover the validation rules in
isolation; one integration test drives the real ``introspect_cli()`` output
for ``envmon reconcile-locations`` (a real xor_group pair) all the way
through to ``executor.build_argv``, proving the whole
form -> Step -> argv chain is actually wired correctly, not just internally
consistent.
"""
import pytest

from autogis.adapters.gui.executor import Decision, build_argv
from autogis.adapters.gui.forms import FormValidationError, build_step
from autogis.adapters.gui.introspect import CommandForm, FormField, introspect_cli


def _field(name, kind="text", required=False, xor_group=None, repeatable=False,
          nargs=1):
    return FormField(name=name, label=name.replace("_", " ").title(), kind=kind,
                     required=required, default=None, xor_group=xor_group,
                     repeatable=repeatable, nargs=nargs)


def _form(fields, path=("tool",), unreachable_reason=None):
    return CommandForm(path=path, help_text=None, fields=tuple(fields),
                       unreachable_reason=unreachable_reason)


def test_missing_required_field_raises():
    form = _form([_field("workbook", required=True)])
    with pytest.raises(FormValidationError, match="required") as exc:
        build_step(form, {})
    assert exc.value.field == "workbook"


def test_blank_string_required_field_raises():
    form = _form([_field("workbook", required=True)])
    with pytest.raises(FormValidationError, match="required"):
        build_step(form, {"workbook": "   "})


def test_optional_blank_field_omitted_from_step_values():
    form = _form([_field("workbook", required=True), _field("threshold")])
    step = build_step(form, {"workbook": "wb.xlsx", "threshold": ""})
    assert step.values == {"workbook": "wb.xlsx"}


def test_unreachable_command_raises():
    form = _form([_field("x")], unreachable_reason="Pro-only in this build")
    with pytest.raises(FormValidationError, match="Pro-only"):
        build_step(form, {"x": "1"})


def test_unknown_field_raises():
    form = _form([_field("known")])
    with pytest.raises(FormValidationError, match="unknown field"):
        build_step(form, {"nope": "1"})


def test_flag_false_is_kept_not_omitted():
    """A GUI checkbox unchecked (False) may override a default=True flag --
    it must survive to argv as an explicit --no-flag, not be silently
    dropped as though the field were never touched."""
    form = _form([_field("incremental", kind="flag")])
    step = build_step(form, {"incremental": False})
    assert step.values == {"incremental": False}


def test_flag_missing_is_omitted():
    form = _form([_field("incremental", kind="flag")])
    step = build_step(form, {})
    assert step.values == {}


def test_repeatable_single_value_wrapped_into_tuple():
    form = _form([_field("profiles", repeatable=True)])
    step = build_step(form, {"profiles": "p1.yaml"})
    assert step.values == {"profiles": ("p1.yaml",)}


def test_repeatable_list_passed_through():
    form = _form([_field("profiles", repeatable=True)])
    step = build_step(form, {"profiles": ["p1.yaml", "p2.yaml"]})
    assert step.values == {"profiles": ["p1.yaml", "p2.yaml"]}


def test_xor_group_neither_filled_raises():
    form = _form([_field("wells_csv", xor_group="wells_csv/gdb"),
                 _field("gdb", xor_group="wells_csv/gdb")])
    with pytest.raises(FormValidationError, match="choose exactly one"):
        build_step(form, {})


def test_xor_group_both_filled_raises():
    form = _form([_field("wells_csv", xor_group="wells_csv/gdb"),
                 _field("gdb", xor_group="wells_csv/gdb")])
    with pytest.raises(FormValidationError, match="choose exactly one"):
        build_step(form, {"wells_csv": "w.csv", "gdb": "site.gdb"})


def test_xor_group_unchecked_flag_sibling_does_not_count_as_filled():
    """reconcile-locations' real shape: --gdb is a flag, --wells-csv is a
    path. An unchecked box submitted as an explicit False must not read as
    "chosen" -- otherwise an empty wells_csv + gdb=False would wrongly pass
    as "exactly one filled" when the user picked neither."""
    form = _form([_field("wells_csv", xor_group="wells_csv/gdb"),
                 _field("gdb", kind="flag", xor_group="wells_csv/gdb")])
    with pytest.raises(FormValidationError, match="choose exactly one"):
        build_step(form, {"gdb": False})

    step = build_step(form, {"gdb": True})
    assert step.values == {"gdb": True}


def test_xor_group_exactly_one_filled_passes():
    form = _form([_field("wells_csv", xor_group="wells_csv/gdb"),
                 _field("gdb", xor_group="wells_csv/gdb")])
    step = build_step(form, {"wells_csv": "w.csv"})
    assert step.values == {"wells_csv": "w.csv"}


def test_nargs_splits_whitespace_and_wraps_in_tuple():
    form = _form([_field("bbox", kind="float", nargs=4)])
    step = build_step(form, {"bbox": "-105 39 -104 40"})
    assert step.values == {"bbox": ("-105", "39", "-104", "40")}


def test_nargs_blank_is_omitted():
    form = _form([_field("bbox", kind="float", nargs=4)])
    step = build_step(form, {"bbox": ""})
    assert step.values == {}


def test_nargs_wrong_count_raises():
    form = _form([_field("bbox", kind="float", nargs=4)])
    with pytest.raises(FormValidationError, match="expected 4") as exc:
        build_step(form, {"bbox": "-105 39 -104"})
    assert exc.value.field == "bbox"


def test_command_path_and_workflow_options_passthrough():
    form = _form([_field("workbook", required=True)], path=("envmon", "inspect"))
    step = build_step(form, {"workbook": "wb.xlsx"},
                      fail_on="warning", pause_on_warning=True)
    assert step.command == ("envmon", "inspect")
    assert step.fail_on == "warning"
    assert step.pause_on_warning is True


# ---- integration: real introspect_cli() output through to build_argv -----

def test_real_reconcile_locations_form_end_to_end():
    forms = {f.label: f for f in introspect_cli()}
    form = forms["envmon reconcile-locations"]

    with pytest.raises(FormValidationError, match="choose exactly one"):
        build_step(form, {"site_config": "s.yaml", "workbook": "wb.xlsx",
                          "profile_path": "p.yaml"})  # neither wells_csv nor gdb

    step = build_step(form, {"site_config": "s.yaml", "workbook": "wb.xlsx",
                             "profile_path": "p.yaml", "wells_csv": "w.csv"})
    argv = build_argv(step.command, step.values)
    assert argv[2:6] == ["autogis.adapters.cli", "envmon",
                        "reconcile-locations", "s.yaml"]
    assert "wb.xlsx" in argv
    assert argv[argv.index("--profile") + 1] == "p.yaml"
    assert argv[argv.index("--wells-csv") + 1] == "w.csv"
    assert "--gdb" not in argv
