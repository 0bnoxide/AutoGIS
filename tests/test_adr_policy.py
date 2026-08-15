from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml


SCRIPT = (
    Path(__file__).resolve().parent.parent
    / ".claude" / "skills" / "new-adr" / "next_adr_number.py"
)
SPEC = spec_from_file_location("autogis_next_adr_number", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
adr = module_from_spec(SPEC)
sys.modules[SPEC.name] = adr
SPEC.loader.exec_module(adr)


WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml"


def _ci_workflow():
    """Load workflow syntax without YAML 1.1 coercing the `on` key."""
    return yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def test_adr_policy_workflow_contract():
    workflow = _ci_workflow()
    assert workflow["on"]["pull_request"]["types"] == [
        "opened", "synchronize", "reopened", "ready_for_review", "converted_to_draft"
    ]
    assert "workflow_dispatch" in workflow["on"]

    job = workflow["jobs"]["adr-policy"]
    assert job["name"] == (
        "${{ github.event_name == 'workflow_dispatch' && "
        "'adr-policy-manual' || 'adr-policy' }}"
    )
    assert job["if"] == "github.event_name != 'workflow_dispatch'"
    assert job["runs-on"] == "windows-2022"
    assert job["permissions"] == {"contents": "read", "pull-requests": "read"}

    assert job["steps"] == [
        {"uses": "actions/checkout@v7"},
        {
            "uses": "actions/setup-python@v7",
            "with": {"python-version": "3.11"},
        },
        {
            "name": "Enforce ADR allocation policy",
            "env": {"GH_TOKEN": "${{ github.token }}"},
            "run": "python .claude/skills/new-adr/next_adr_number.py --policy-check",
        },
    ]


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


REPOSITORY = "owner/repo"
OPEN_PULLS = f"repos/{REPOSITORY}/pulls?state=open&per_page=100"


class FakeRunner:
    """Offline `gh api` seam with endpoint-specific JSON or failures."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, args, **_kwargs):
        self.calls.append(args)
        value = self.responses[args[2]]
        if isinstance(value, BaseException):
            raise value
        return subprocess.CompletedProcess(args, 0, json.dumps(value), "")


def _pr_files(number):
    return f"repos/{REPOSITORY}/pulls/{number}/files?per_page=100"


def _event(draft=False):
    return {
        "pull_request": {
            "number": 488,
            "draft": draft,
            "base": {"sha": "1111111111111111111111111111111111111111"},
        }
    }


def _policy_runner(current=None):
    return FakeRunner(
        {
            _pr_files(488): [[current or {"filename": "docs/adr/0130-current.md", "status": "added"}]],
            f"repos/{REPOSITORY}/git/trees/1111111111111111111111111111111111111111?recursive=1": {
                "truncated": False,
                "tree": [{"path": "docs/adr/0129-base.md"}],
            },
            OPEN_PULLS: [[{"number": 488}, {"number": 489}]],
            _pr_files(489): [[{"filename": "docs/adr/0131-other.md", "status": "added"}]],
        }
    )


def test_gh_pages_flattens_open_pull_pages_and_uses_gh_pagination(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", REPOSITORY)
    runner = FakeRunner({OPEN_PULLS: [[{"number": 488}], [{"number": 489}]]})

    assert adr._open_pull_numbers(run=runner) == [488, 489]
    assert runner.calls == [["gh", "api", OPEN_PULLS, "--paginate", "--slurp"]]


def test_pull_files_maps_github_filename_and_uses_gh_pagination(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", REPOSITORY)
    endpoint = _pr_files(488)
    runner = FakeRunner(
        {endpoint: [[{"filename": "docs/adr/0129-a.md", "status": "added"}], [{"filename": "docs/adr/0130-b.md", "status": "renamed"}]]}
    )

    assert adr._pull_files(488, run=runner) == [
        adr.PRFile(488, "docs/adr/0129-a.md", "added"),
        adr.PRFile(488, "docs/adr/0130-b.md", "renamed"),
    ]
    assert runner.calls == [["gh", "api", endpoint, "--paginate", "--slurp"]]


@pytest.mark.parametrize(
    "file",
    [
        {"filename": "docs/adr/0129-secret-marker.md", "status": "not-a-status"},
        {"filename": None, "status": "added"},
        {"filename": "", "status": "added"},
    ],
)
def test_pull_files_rejects_unknown_status_and_invalid_filename_without_echoing_values(
        monkeypatch, file):
    monkeypatch.setenv("GITHUB_REPOSITORY", REPOSITORY)
    endpoint = _pr_files(488)

    with pytest.raises(adr.ADRStateUnavailable) as raised:
        adr._pull_files(488, run=FakeRunner({endpoint: [[file]]}))

    assert "secret-marker" not in str(raised.value)


def test_cli_policy_rejects_unknown_file_status_as_unavailable_state(
        monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("GITHUB_REPOSITORY", REPOSITORY)
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(_event()))

    assert adr.main(
        ["--policy-check", "--event-file", str(event_path)],
        environ={},
        run=_policy_runner(
            {"filename": "docs/adr/0129-current.md", "status": "not-a-status"}
        ),
    ) == 2
    assert "not-a-status" not in capsys.readouterr().err


@pytest.mark.parametrize("payload", [{}, [{"number": 488}], [["not-an-object"]]])
def test_gh_pages_rejects_malformed_outer_page_and_item_shapes(monkeypatch, payload):
    monkeypatch.setenv("GITHUB_REPOSITORY", REPOSITORY)
    with pytest.raises(adr.ADRStateUnavailable):
        adr._gh_pages(OPEN_PULLS, run=FakeRunner({OPEN_PULLS: payload}))


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (FileNotFoundError("gh"), "FileNotFoundError"),
        (subprocess.TimeoutExpired(["gh"], 30), "TimeoutExpired"),
        (subprocess.CalledProcessError(17, ["gh"], output="token=never-show"), "exit 17"),
    ],
)
def test_gh_reader_fails_closed_without_leaking_response_payload(monkeypatch, failure, expected):
    monkeypatch.setenv("GITHUB_REPOSITORY", REPOSITORY)
    with pytest.raises(adr.ADRStateUnavailable) as raised:
        adr._gh_pages(OPEN_PULLS, run=FakeRunner({OPEN_PULLS: failure}))
    assert expected in str(raised.value)
    assert "token=never-show" not in str(raised.value)


def test_open_pr_max_keeps_legacy_failure_class_in_fail_soft_warning(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_REPOSITORY", REPOSITORY)
    assert adr._open_pr_max(run=FakeRunner({OPEN_PULLS: FileNotFoundError("gh")})) == 0
    assert "FileNotFoundError" in capsys.readouterr().err


def test_open_pr_max_without_actions_repository_still_reports_missing_gh(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)

    def missing_gh(*_args, **_kwargs):
        raise FileNotFoundError("gh")

    assert adr._open_pr_max(run=missing_gh) == 0
    assert "FileNotFoundError" in capsys.readouterr().err


def test_legacy_numbering_fails_soft_when_repository_discovery_is_not_an_object(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    runner = FakeRunner({"view": []})

    assert adr._open_pr_max(run=runner) == 0
    assert "ADRStateUnavailable" in capsys.readouterr().err


def test_policy_rejects_hostile_base_sha_without_echoing_it(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_REPOSITORY", REPOSITORY)
    (tmp_path / "docs" / "adr").mkdir(parents=True)
    marker = "base-sha-secret-marker"
    event = _event()
    event["pull_request"]["base"]["sha"] = marker

    with pytest.raises(adr.ADRStateUnavailable) as raised:
        adr.policy_check(tmp_path, event_name="pull_request", event=event, run=FakeRunner({}))

    assert marker not in str(raised.value)


@pytest.mark.parametrize("event_name", [None, "schedule"])
def test_policy_rejects_missing_or_unsupported_event_without_github(tmp_path, event_name):
    with pytest.raises(adr.ADRStateUnavailable):
        adr.policy_check(
            tmp_path,
            event_name=event_name,
            event={},
            run=lambda *_args, **_kwargs: pytest.fail("unsupported event must not read GitHub"),
        )


def test_failed_paginated_command_cannot_return_partial_results(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", REPOSITORY)

    def partial_then_failure(_args, **_kwargs):
        # `gh` performs pagination internally; its nonzero exit means no page set is usable.
        raise subprocess.CalledProcessError(29, ["gh"], output="partial-page-token")

    with pytest.raises(adr.ADRStateUnavailable) as raised:
        adr._gh_pages(OPEN_PULLS, run=partial_then_failure)

    assert "partial-page-token" not in str(raised.value)


def test_all_open_pull_files_does_not_return_partial_results_after_later_failure(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", REPOSITORY)
    runner = FakeRunner(
        {
            OPEN_PULLS: [[{"number": 488}, {"number": 489}]],
            _pr_files(488): [[{"filename": "docs/adr/0129-a.md", "status": "added"}]],
            _pr_files(489): subprocess.CalledProcessError(23, ["gh"], output="secret"),
        }
    )

    with pytest.raises(adr.ADRStateUnavailable, match="exit 23"):
        adr._all_open_pull_files(run=runner)


def test_base_tree_rejects_truncated_response(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", REPOSITORY)
    endpoint = f"repos/{REPOSITORY}/git/trees/base?recursive=1"
    with pytest.raises(adr.ADRStateUnavailable, match="truncated"):
        adr._base_paths("base", run=FakeRunner({endpoint: {"truncated": True, "tree": []}}))


def test_pull_files_rejects_githubs_3000_file_ceiling(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", REPOSITORY)
    endpoint = _pr_files(488)
    files = [{"filename": f"docs/adr/{n:04d}-x.md", "status": "added"} for n in range(3000)]
    with pytest.raises(adr.ADRStateUnavailable, match="3,000"):
        adr._pull_files(488, run=FakeRunner({endpoint: [files]}))


def test_policy_check_reads_current_base_open_and_other_pull_state(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_REPOSITORY", REPOSITORY)
    (tmp_path / "docs" / "adr").mkdir(parents=True)
    runner = _policy_runner()

    assert adr.policy_check(tmp_path, event_name="pull_request", event=_event(), run=runner) == []
    assert [call[2] for call in runner.calls] == [
        _pr_files(488),
        f"repos/{REPOSITORY}/git/trees/1111111111111111111111111111111111111111?recursive=1",
        OPEN_PULLS,
        _pr_files(489),
    ]


def test_policy_check_excludes_current_pr_from_other_file_collection(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_REPOSITORY", REPOSITORY)
    (tmp_path / "docs" / "adr").mkdir(parents=True)
    runner = _policy_runner()

    adr.policy_check(tmp_path, event_name="pull_request", event=_event(), run=runner)
    assert [call[2] for call in runner.calls].count(_pr_files(488)) == 1


def test_policy_check_deduplicates_identical_current_tree_diagnostics(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_REPOSITORY", REPOSITORY)
    event = _event()
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    for name in ("0129-a.md", "0129-b.md"):
        (adr_dir / name).write_text("")
    runner = FakeRunner(
        {
            _pr_files(488): [[
                {"filename": "docs/adr/0129-a.md", "status": "added"},
                {"filename": "docs/adr/0129-b.md", "status": "added"},
            ]],
            f"repos/{REPOSITORY}/git/trees/1111111111111111111111111111111111?recursive=1": {
                "truncated": False,
                "tree": [],
            },
            OPEN_PULLS: [[{"number": 488}]],
        }
    )
    tree_endpoint = next(key for key in runner.responses if "/git/trees/" in key)
    runner.responses[
        f"repos/{REPOSITORY}/git/trees/{event['pull_request']['base']['sha']}?recursive=1"
    ] = runner.responses.pop(tree_endpoint)

    assert adr.policy_check(tmp_path, event_name="pull_request", event=event, run=runner) == [
        "Duplicate ADR 0129 in checked-out tree: docs/adr/0129-a.md, docs/adr/0129-b.md."
    ]


def test_policy_check_push_only_checks_local_tree_without_github(tmp_path):
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "XXXX-unfinalized.md").write_text("")

    assert adr.policy_check(
        tmp_path,
        event_name="push",
        event={},
        run=lambda *_args, **_kwargs: pytest.fail("push must not read GitHub"),
    ) == ["docs/adr/XXXX-unfinalized.md is unfinalized; main may not contain ADR placeholders."]


def test_main_policy_check_exit_codes_and_success_output(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("GITHUB_REPOSITORY", REPOSITORY)
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(_event()))

    assert adr.main(
        ["--policy-check", "--event-file", str(event_path)],
        environ={"GITHUB_EVENT_NAME": "push"},
        run=_policy_runner(),
    ) == 0
    assert "ADR policy check passed" in capsys.readouterr().out

    assert adr.main(
        ["--policy-check", "--event-file", str(event_path)],
        environ={},
        run=_policy_runner({"filename": "docs/adr/XXXX-unfinalized.md", "status": "added"}),
    ) == 1

    unavailable = FakeRunner({_pr_files(488): FileNotFoundError("gh")})
    assert adr.main(
        ["--policy-check", "--event-file", str(event_path)], environ={}, run=unavailable
    ) == 2

    malformed = FakeRunner({_pr_files(488): {}})
    assert adr.main(
        ["--policy-check", "--event-file", str(event_path)], environ={}, run=malformed
    ) == 2


def test_event_file_overrides_environment_and_selects_pull_request_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_REPOSITORY", REPOSITORY)
    event_path = tmp_path / "pr-event.json"
    event_path.write_text(json.dumps(_event()))
    runner = _policy_runner()

    assert adr.main(
        ["--policy-check", "--event-file", str(event_path)],
        environ={"GITHUB_EVENT_NAME": "push", "GITHUB_EVENT_PATH": "missing.json"},
        run=runner,
    ) == 0
    assert _pr_files(488) in [call[2] for call in runner.calls]


def test_strict_scan_combines_local_default_branch_and_open_pr_claims(
        monkeypatch, tmp_path):
    """Strict allocation reads all three sources and only live ADR paths."""
    monkeypatch.setenv("GITHUB_REPOSITORY", REPOSITORY)
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "0121-local.md").write_text("")
    default_tree = f"repos/{REPOSITORY}/git/trees/main?recursive=1"
    runner = FakeRunner(
        {
            f"repos/{REPOSITORY}": {"default_branch": "main"},
            default_tree: {
                "truncated": False,
                "tree": [
                    {"path": "docs/adr/0130-default.md"},
                    {"path": "docs/adr/2026-08-13-agent-decisions.md"},
                    {"path": "docs/adr/logs/0999-log.md"},
                    {"path": "docs/adr/XXXX-draft.md"},
                ],
            },
            OPEN_PULLS: [[{"number": 501}, {"number": 502}]],
            _pr_files(501): [[
                {"filename": "docs/adr/0141-added.md", "status": "added"},
                {"filename": "docs/adr/0142-renamed.md", "status": "renamed"},
                {"filename": "docs/adr/0998-removed.md", "status": "removed"},
                {"filename": "docs/adr/2026-08-13-pr-log.md", "status": "added"},
                {"filename": "docs/adr/logs/0997-nested.md", "status": "added"},
                {"filename": "docs/adr/XXXX-pr-draft.md", "status": "added"},
            ]],
            _pr_files(502): [[
                {"filename": "docs/adr/0151-other.md", "status": "added"},
            ]],
        }
    )

    assert adr._scan_max(tmp_path, strict=True, run=runner) == 151
    assert [call[2] for call in runner.calls] == [
        f"repos/{REPOSITORY}", default_tree, OPEN_PULLS, _pr_files(501), _pr_files(502)
    ]


@pytest.mark.parametrize("failed_endpoint", [
    f"repos/{REPOSITORY}",
    f"repos/{REPOSITORY}/git/trees/main?recursive=1",
    OPEN_PULLS,
    _pr_files(501),
])
def test_strict_scan_raises_on_any_github_failure_without_local_fallback(
        monkeypatch, tmp_path, failed_endpoint):
    monkeypatch.setenv("GITHUB_REPOSITORY", REPOSITORY)
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "0999-local-only.md").write_text("")
    responses = {
        f"repos/{REPOSITORY}": {"default_branch": "main"},
        f"repos/{REPOSITORY}/git/trees/main?recursive=1": {
            "truncated": False, "tree": [{"path": "docs/adr/0130-default.md"}]
        },
        OPEN_PULLS: [[{"number": 501}]],
        _pr_files(501): [[{"filename": "docs/adr/0141-pr.md", "status": "added"}]],
    }
    responses[failed_endpoint] = FileNotFoundError("gh")

    with pytest.raises(adr.ADRStateUnavailable):
        adr._scan_max(tmp_path, strict=True, run=FakeRunner(responses))


@pytest.mark.parametrize(
    ("local", "base_paths", "pr_files", "expected"),
    [
        ([152], [130], [{"filename": "docs/adr/0140-pr.md", "status": "added"}], 152),
        ([121], [153], [{"filename": "docs/adr/0140-pr.md", "status": "added"}], 153),
        ([121], [130], [{"filename": "docs/adr/0154-pr.md", "status": "renamed"}], 154),
        (
            [121],
            [130],
            [
                {"filename": "docs/adr/0999-removed.md", "status": "removed"},
                {"filename": "docs/adr/2026-08-13-log.md", "status": "added"},
                {"filename": "docs/adr/logs/0998-nested.md", "status": "added"},
                {"filename": "docs/adr/XXXX-draft.md", "status": "added"},
            ],
            130,
        ),
    ],
)
def test_strict_scan_isolates_each_authoritative_floor(
        monkeypatch, tmp_path, local, base_paths, pr_files, expected):
    monkeypatch.setenv("GITHUB_REPOSITORY", REPOSITORY)
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    for number in local:
        (adr_dir / f"{number:04d}-local.md").write_text("")
    default_tree = f"repos/{REPOSITORY}/git/trees/main?recursive=1"
    runner = FakeRunner(
        {
            f"repos/{REPOSITORY}": {"default_branch": "main"},
            default_tree: {
                "truncated": False,
                "tree": [{"path": f"docs/adr/{number:04d}-base.md"} for number in base_paths],
            },
            OPEN_PULLS: [[{"number": 501}]],
            _pr_files(501): [pr_files],
        }
    )

    assert adr._scan_max(tmp_path, strict=True, run=runner) == expected
    assert [call[2] for call in runner.calls] == [
        f"repos/{REPOSITORY}", default_tree, OPEN_PULLS, _pr_files(501)
    ]


# --- transactional XXXX finalization -----------------------------------------

def _finalize_repo(tmp_path, *slugs):
    root = tmp_path / "repo"
    adr_dir = root / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    rows = []
    for slug in slugs:
        name = f"XXXX-{slug}.md"
        (adr_dir / name).write_text(
            "# ADR-XXXX: Example Decision\n\nBody.\n", encoding="utf-8"
        )
        rows.append(f"| [XXXX]({name}) | Example decision | Proposed | 2026-08-13 |")
    (adr_dir / "README.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return root


def _finalize_runner(branch="feature/finalize"):
    def run(args, **_kwargs):
        assert args[-2:] == ["branch", "--show-current"]
        return subprocess.CompletedProcess(args, 0, branch + "\n", "")
    return run


def _finalize_bytes(root):
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in (root / "docs" / "adr").glob("*.md")
    }


def _uncoordinated(monkeypatch, floor=130):
    monkeypatch.setattr(adr, "_scan_max", lambda *_a, **_k: floor)
    monkeypatch.setattr(adr, "_reserved_max", lambda: 0)
    monkeypatch.setattr(adr, "_coordination", lambda *_a, **_k: None)


def test_finalize_one_placeholder_at_verified_floor(monkeypatch, tmp_path):
    root = _finalize_repo(tmp_path, "example-decision")
    _uncoordinated(monkeypatch)

    mappings = adr.finalize_placeholders(root, run=_finalize_runner())

    assert mappings == [adr.FinalizedADR(
        root / "docs" / "adr" / "XXXX-example-decision.md",
        root / "docs" / "adr" / "0131-example-decision.md",
    )]
    assert (root / "docs" / "adr" / "0131-example-decision.md").read_text(
        encoding="utf-8"
    ).startswith("# ADR-0131:")
    assert (root / "docs" / "adr" / "README.md").read_text(encoding="utf-8") == (
        "| [131](0131-example-decision.md) | Example decision | Proposed | 2026-08-13 |\n"
    )


def test_finalize_multiple_placeholders_sorts_paths_and_mappings(monkeypatch, tmp_path):
    root = _finalize_repo(tmp_path, "zeta", "alpha")
    _uncoordinated(monkeypatch)

    mappings = adr.finalize_placeholders(root, run=_finalize_runner())

    assert [(m.old_path.name, m.new_path.name) for m in mappings] == [
        ("XXXX-alpha.md", "0131-alpha.md"),
        ("XXXX-zeta.md", "0132-zeta.md"),
    ]
    readme = (root / "docs" / "adr" / "README.md").read_text(encoding="utf-8")
    assert "[131](0131-alpha.md)" in readme
    assert "[132](0132-zeta.md)" in readme


def test_finalize_uses_strict_floor_and_live_reservations(monkeypatch, tmp_path):
    root = _finalize_repo(tmp_path, "example-decision")
    calls = []

    def strict_floor(*_a, **kwargs):
        calls.append(kwargs)
        return 130

    monkeypatch.setattr(adr, "_scan_max", strict_floor)
    monkeypatch.setattr(adr, "_reserved_max", lambda: 140)
    monkeypatch.setattr(adr, "_coordination", lambda *_a, **_k: None)

    mappings = adr.finalize_placeholders(root, run=_finalize_runner())

    assert calls == [{"strict": True, "run": _finalize_runner()}] or calls[0]["strict"] is True
    assert mappings[0].new_path.name == "0141-example-decision.md"


def test_finalize_rejects_target_and_numeric_collisions_before_writes(monkeypatch, tmp_path):
    root = _finalize_repo(tmp_path, "example-decision")
    _uncoordinated(monkeypatch)
    adr_dir = root / "docs" / "adr"
    (adr_dir / "0131-already.md").write_text("# ADR-0131: Existing\n", encoding="utf-8")
    before = _finalize_bytes(root)

    with pytest.raises(adr.ADRFinalizeError):
        adr.finalize_placeholders(root, run=_finalize_runner())

    assert _finalize_bytes(root) == before


def test_finalize_releases_repeated_reservations_on_preflight_failure(monkeypatch, tmp_path):
    root = _finalize_repo(tmp_path, "alpha", "zeta")
    _uncoordinated(monkeypatch)
    released = []

    class Registry:
        def reserve_number(self, *_args):
            return 131

        def release(self, _path, _sid, kind=None, value=None):
            released.append((kind, value))

    monkeypatch.setattr(adr, "_coordination", lambda *_a, **_k: (Registry(), "claims", "s1"))

    with pytest.raises(adr.ADRFinalizeError):
        adr.finalize_placeholders(root, run=_finalize_runner())

    assert released == [("adr", "131"), ("adr", "131")]


@pytest.mark.parametrize(
    "branch, mutate",
    [
        ("main", lambda root: None),
        ("", lambda root: None),
        ("feature/x", lambda root: (root / "docs" / "adr" / "XXXX-example-decision.md").unlink()),
        ("feature/x", lambda root: (root / "docs" / "adr" / "XXXX-example-decision.md").write_text("# ADR-XXXXBROKEN\n", encoding="utf-8")),
        ("feature/x", lambda root: (root / "docs" / "adr" / "README.md").write_text("", encoding="utf-8")),
        ("feature/x", lambda root: (root / "docs" / "adr" / "README.md").write_text(
            "| [XXXX](XXXX-example-decision.md) | Example decision | Proposed | 2026-08-13 |\n"
            "| [XXXX](XXXX-example-decision.md) | Example decision | Proposed | 2026-08-13 |\n", encoding="utf-8")),
    ],
)
def test_finalize_preflight_failures_do_not_write(monkeypatch, tmp_path, branch, mutate):
    root = _finalize_repo(tmp_path, "example-decision")
    _uncoordinated(monkeypatch)
    mutate(root)
    before = _finalize_bytes(root)

    with pytest.raises(adr.ADRFinalizeError):
        adr.finalize_placeholders(root, run=_finalize_runner(branch))

    assert _finalize_bytes(root) == before


def test_finalize_strict_github_failure_does_not_write(monkeypatch, tmp_path):
    root = _finalize_repo(tmp_path, "example-decision")
    _uncoordinated(monkeypatch)
    before = _finalize_bytes(root)
    monkeypatch.setattr(adr, "_scan_max", lambda *_a, **_k: (_ for _ in ()).throw(
        adr.ADRStateUnavailable("remote unavailable")
    ))

    with pytest.raises(adr.ADRStateUnavailable):
        adr.finalize_placeholders(root, run=_finalize_runner())

    assert _finalize_bytes(root) == before


@pytest.mark.parametrize("fail_at", [2, 3])
def test_finalize_rolls_back_bytes_after_adr_or_readme_write_failure(
        monkeypatch, tmp_path, fail_at):
    root = _finalize_repo(tmp_path, "alpha", "zeta")
    _uncoordinated(monkeypatch)
    before = _finalize_bytes(root)
    calls = {"n": 0}

    def fail_once(path, data):
        calls["n"] += 1
        if calls["n"] == fail_at:
            raise OSError("injected write failure")
        Path(path).write_bytes(data)

    with pytest.raises(adr.ADRFinalizeError):
        adr.finalize_placeholders(root, run=_finalize_runner(), write_bytes=fail_once)

    assert _finalize_bytes(root) == before


def test_finalize_does_not_delete_target_created_by_another_actor(monkeypatch, tmp_path):
    root = _finalize_repo(tmp_path, "example-decision")
    _uncoordinated(monkeypatch)
    target = root / "docs" / "adr" / "0131-example-decision.md"
    target.write_bytes(b"other actor")

    with pytest.raises(adr.ADRFinalizeError):
        adr.finalize_placeholders(root, run=_finalize_runner())

    assert target.read_bytes() == b"other actor"


def test_finalize_removes_partial_target_owned_before_writer_failure(monkeypatch, tmp_path):
    root = _finalize_repo(tmp_path, "example-decision")
    _uncoordinated(monkeypatch)
    before = _finalize_bytes(root)
    target = root / "docs" / "adr" / "0131-example-decision.md"
    released = []

    class Registry:
        def reserve_number(self, _path, _sid, _kind, base):
            return base + 1

        def release(self, _path, _sid, kind=None, value=None):
            released.append((kind, value))

    monkeypatch.setattr(adr, "_coordination", lambda *_a, **_k: (Registry(), "claims", "s1"))

    def partial(path, _data):
        Path(path).write_bytes(b"partial numeric ADR")
        raise OSError("injected write failure")

    with pytest.raises(adr.ADRFinalizeError):
        adr.finalize_placeholders(root, run=_finalize_runner(), write_bytes=partial)

    assert not target.exists()
    assert _finalize_bytes(root) == before
    assert released == [("adr", "131")]


def test_finalize_rejects_existing_numeric_adr_with_mismatched_heading(monkeypatch, tmp_path):
    root = _finalize_repo(tmp_path, "example-decision")
    _uncoordinated(monkeypatch)
    existing = root / "docs" / "adr" / "0130-existing.md"
    existing.write_bytes(b"# ADR-0129: Incorrect\n")
    before = _finalize_bytes(root)

    with pytest.raises(adr.ADRFinalizeError):
        adr.finalize_placeholders(root, run=_finalize_runner())

    assert _finalize_bytes(root) == before


def test_finalize_rejects_gapped_coordinated_reservations(monkeypatch, tmp_path):
    root = _finalize_repo(tmp_path, "alpha", "zeta")
    _uncoordinated(monkeypatch)
    released = []

    class Registry:
        values = iter((131, 133))

        def reserve_number(self, *_args):
            return next(self.values)

        def release(self, _path, _sid, kind=None, value=None):
            released.append((kind, value))

    monkeypatch.setattr(adr, "_coordination", lambda *_a, **_k: (Registry(), "claims", "s1"))

    with pytest.raises(adr.ADRFinalizeError):
        adr.finalize_placeholders(root, run=_finalize_runner())

    assert released == [("adr", "131"), ("adr", "133")]


def test_finalize_reservation_is_released_on_failure_and_retained_on_success(
        monkeypatch, tmp_path):
    root = _finalize_repo(tmp_path, "example-decision")
    created, released = [], []

    class Registry:
        def reserve_number(self, _path, _sid, _kind, base):
            created.append(base + 1)
            return base + 1

        def release(self, _path, _sid, kind=None, value=None):
            released.append((kind, value))

    _uncoordinated(monkeypatch)
    monkeypatch.setattr(adr, "_coordination", lambda *_a, **_k: (Registry(), "claims", "s1"))

    with pytest.raises(adr.ADRFinalizeError):
        adr.finalize_placeholders(
            root, run=_finalize_runner(), write_bytes=lambda *_a: (_ for _ in ()).throw(OSError())
        )
    assert released == [("adr", "131")]

    root = _finalize_repo(tmp_path / "success", "success")
    created.clear()
    released.clear()
    adr.finalize_placeholders(root, run=_finalize_runner())
    assert created == [131]
    assert released == []


def test_finalize_cli_prints_sorted_mappings_and_sanitizes_errors(monkeypatch, tmp_path, capsys):
    root = _finalize_repo(tmp_path, "zeta", "alpha")
    _uncoordinated(monkeypatch)
    monkeypatch.setattr(adr, "finalize_placeholders", lambda *_a, **_k: [
        adr.FinalizedADR(root / "docs/adr/XXXX-alpha.md", root / "docs/adr/0131-alpha.md"),
        adr.FinalizedADR(root / "docs/adr/XXXX-zeta.md", root / "docs/adr/0132-zeta.md"),
    ])

    assert adr.main(["--finalize"], repo_root=root) == 0
    assert capsys.readouterr().out.splitlines() == [
        "docs/adr/XXXX-alpha.md -> docs/adr/0131-alpha.md",
        "docs/adr/XXXX-zeta.md -> docs/adr/0132-zeta.md",
        "updated docs/adr/README.md",
    ]


def test_finalize_cli_uses_real_temp_repo_relative_paths(monkeypatch, tmp_path, capsys):
    root = _finalize_repo(tmp_path, "example-decision")
    _uncoordinated(monkeypatch)

    assert adr.main(["--finalize"], repo_root=root, run=_finalize_runner()) == 0
    assert capsys.readouterr().out.splitlines() == [
        "docs/adr/XXXX-example-decision.md -> docs/adr/0131-example-decision.md",
        "updated docs/adr/README.md",
    ]
