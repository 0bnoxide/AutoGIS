from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

import pytest


SCRIPT = (
    Path(__file__).resolve().parent.parent
    / ".claude" / "skills" / "new-adr" / "next_adr_number.py"
)
SPEC = spec_from_file_location("autogis_next_adr_number", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
adr = module_from_spec(SPEC)
sys.modules[SPEC.name] = adr
SPEC.loader.exec_module(adr)


@pytest.mark.parametrize(
    ("path", "number", "placeholder"),
    [
        ("docs/adr/0129-one.md", 129, False),
        ("docs\\adr\\0130-two.md", 130, False),
        ("docs/adr/2026-08-13-agent-decisions.md", None, False),
        ("docs/adr/logs/0129-log.md", None, False),
        ("docs/adr/README.md", None, False),
        ("docs/adr/TEMPLATE.md", None, False),
        ("docs/adr/XXXX-draft.md", None, True),
        ("other/0129-one.md", None, False),
    ],
)
def test_root_adr_recognition(path, number, placeholder):
    assert adr._adr_number(path) == number
    assert adr._is_placeholder(path) is placeholder


def test_tree_policy_reports_duplicate_number_in_one_checkout():
    assert adr._tree_policy_errors(
        ["docs/adr/0129-b.md", "docs/adr/0129-a.md"],
        allow_placeholders=False,
    ) == [
        "Duplicate ADR 0129 in checked-out tree: "
        "docs/adr/0129-a.md, docs/adr/0129-b.md."
    ]


@pytest.mark.parametrize(
    ("draft", "expected"),
    [
        (True, []),
        (
            False,
            [
                "docs/adr/XXXX-new-policy.md is unfinalized; "
                "ready PRs require numeric ADR filenames."
            ],
        ),
    ],
)
def test_pr_policy_allows_placeholder_only_for_draft_prs(draft, expected):
    assert adr._pull_request_policy_errors(
        current_pr=488,
        draft=draft,
        current_files=[adr.PRFile(488, "docs/adr/XXXX-new-policy.md", "added")],
        base_paths=[],
        other_files=[],
    ) == expected


def test_tree_policy_rejects_placeholder_on_main():
    assert adr._tree_policy_errors(
        ["docs/adr/XXXX-new-policy.md"], allow_placeholders=False
    ) == [
        "docs/adr/XXXX-new-policy.md is unfinalized; "
        "main may not contain ADR placeholders."
    ]


def test_pr_policy_rejects_current_number_already_on_base():
    assert adr._pull_request_policy_errors(
        current_pr=488,
        draft=False,
        current_files=[adr.PRFile(488, "docs/adr/0129-new.md", "added")],
        base_paths=["docs/adr/0129-existing.md"],
        other_files=[],
    ) == [
        "ADR 0129 already exists on the base branch as docs/adr/0129-existing.md; "
        "docs/adr/0129-new.md must use a different number."
    ]


def test_pr_policy_rejects_two_numeric_adrs_in_current_pr():
    assert adr._pull_request_policy_errors(
        current_pr=488,
        draft=False,
        current_files=[
            adr.PRFile(488, "docs/adr/0129-one.md", "added"),
            adr.PRFile(488, "docs/adr/0129-two.md", "added"),
        ],
        base_paths=[],
        other_files=[],
    ) == [
        "Duplicate ADR 0129 in checked-out tree: "
        "docs/adr/0129-one.md, docs/adr/0129-two.md."
    ]


def test_pr_policy_sorts_multiple_collisions():
    assert adr._pull_request_policy_errors(
        current_pr=488,
        draft=False,
        current_files=[
            adr.PRFile(488, "docs/adr/0130-current.md", "added"),
            adr.PRFile(488, "docs/adr/0129-current.md", "added"),
        ],
        base_paths=["docs/adr/0130-base.md"],
        other_files=[
            adr.PRFile(490, "docs/adr/0129-z.md", "added"),
            adr.PRFile(487, "docs/adr/0129-a.md", "added"),
        ],
    ) == [
        "ADR 0129 is also added by PR #487 as docs/adr/0129-a.md; "
        "use XXXX or finalize after that claim changes.",
        "ADR 0129 is also added by PR #490 as docs/adr/0129-z.md; "
        "use XXXX or finalize after that claim changes.",
        "ADR 0130 already exists on the base branch as docs/adr/0130-base.md; "
        "docs/adr/0130-current.md must use a different number.",
    ]


def test_pr_policy_orders_base_and_open_collisions_by_counterpart_path():
    assert adr._pull_request_policy_errors(
        current_pr=488,
        draft=False,
        current_files=[adr.PRFile(488, "docs/adr/0129-current.md", "added")],
        base_paths=["docs/adr/0129-z.md"],
        other_files=[adr.PRFile(487, "docs/adr/0129-a.md", "added")],
    ) == [
        "ADR 0129 is also added by PR #487 as docs/adr/0129-a.md; "
        "use XXXX or finalize after that claim changes.",
        "ADR 0129 already exists on the base branch as docs/adr/0129-z.md; "
        "docs/adr/0129-current.md must use a different number.",
    ]


def test_pr_policy_orders_all_diagnostics_by_adr_number_then_path_then_pr():
    assert adr._pull_request_policy_errors(
        current_pr=488,
        draft=False,
        current_files=[
            adr.PRFile(488, "docs/adr/0130-b.md", "added"),
            adr.PRFile(488, "docs/adr/0129-current.md", "added"),
            adr.PRFile(488, "docs/adr/0130-a.md", "added"),
        ],
        base_paths=["docs/adr/0129-existing.md"],
        other_files=[],
    ) == [
        "ADR 0129 already exists on the base branch as docs/adr/0129-existing.md; "
        "docs/adr/0129-current.md must use a different number.",
        "Duplicate ADR 0130 in checked-out tree: "
        "docs/adr/0130-a.md, docs/adr/0130-b.md.",
    ]


def test_pr_policy_ignores_same_path_modified_and_removed_files():
    assert adr._pull_request_policy_errors(
        current_pr=488,
        draft=False,
        current_files=[
            adr.PRFile(488, "docs/adr/0129-existing.md", "modified"),
            adr.PRFile(488, "docs/adr/0130-removed.md", "removed"),
        ],
        base_paths=["docs/adr/0129-existing.md"],
        other_files=[
            adr.PRFile(487, "docs/adr/0129-existing.md", "modified"),
            adr.PRFile(487, "docs/adr/0130-removed.md", "removed"),
        ],
    ) == []


def test_pr_policy_treats_renamed_filename_as_a_claim():
    assert adr._pull_request_policy_errors(
        current_pr=488,
        draft=False,
        current_files=[adr.PRFile(488, "docs/adr/0129-renamed.md", "renamed")],
        base_paths=[],
        other_files=[adr.PRFile(487, "docs/adr/0129-other.md", "added")],
    ) == [
        "ADR 0129 is also added by PR #487 as docs/adr/0129-other.md; "
        "use XXXX or finalize after that claim changes."
    ]


def test_issue_492_distinct_0129_slugs_cannot_both_pass():
    errors = adr._pull_request_policy_errors(
        current_pr=488,
        draft=False,
        current_files=[adr.PRFile(488, "docs/adr/0129-registry-metadata.md", "added")],
        base_paths=[],
        other_files=[adr.PRFile(487, "docs/adr/0129-connection-profile.md", "added")],
    )
    assert errors == [
        "ADR 0129 is also added by PR #487 as "
        "docs/adr/0129-connection-profile.md; use XXXX or finalize after "
        "that claim changes."
    ]
