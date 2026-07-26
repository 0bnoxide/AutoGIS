"""Pin the frontmatter contract for .claude/agents/*.md.

Agent definitions are discovered by frontmatter. A malformed block, a missing
``name``, or a ``name`` that disagrees with the filename does not raise — the
agent simply never loads, and a prompt that dispatches it fails at runtime with
no signal here. These tests turn that silent failure into a red test.

The block is parsed with PyYAML rather than a key/value regex on purpose: a
regex happily accepts YAML-invalid text that merely *looks* like fields (e.g.
``description: an unquoted: colon``), so the test would pass on a definition the
real loader rejects — precisely the silent failure this file exists to catch
(PR #324 review).
"""
from pathlib import Path

import pytest
import yaml

AGENTS_DIR = Path(__file__).resolve().parent.parent / ".claude" / "agents"
DELIM = "---\n"
PR_REVIEW_PROBE_IDS = (
    "BOUNDARY_SHAPE",
    "CONTRACT_REACHABILITY",
    "IDENTITY_PROVENANCE",
    "SIDE_EFFECT_SAFETY",
    "ENVIRONMENT_SEAM",
)


def _agent_files() -> list[Path]:
    return sorted(AGENTS_DIR.glob("*.md"))


def test_agents_dir_is_populated() -> None:
    """Guards against the glob silently going empty (moved/renamed dir)."""
    assert _agent_files(), f"no agent definitions found under {AGENTS_DIR}"


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Return (frontmatter_block, body). Raises AssertionError if undelimited."""
    assert text.startswith(DELIM), "file does not open with a '---' frontmatter delimiter"
    end = text.find(f"\n{DELIM}", len(DELIM) - 1)
    assert end != -1, "frontmatter block is never closed with '---'"
    return text[len(DELIM):end + 1], text[end + 1 + len(DELIM):]


@pytest.mark.parametrize("path", _agent_files(), ids=lambda p: p.name)
def test_agent_frontmatter_is_valid(path: Path) -> None:
    text = path.read_text(encoding="utf-8")

    try:
        block, body = _split_frontmatter(text)
    except AssertionError as exc:
        pytest.fail(f"{path.name}: {exc}")

    # Parse as real YAML — the loader does, and a regex would accept text YAML
    # rejects, letting a silently-undiscoverable agent through this test.
    try:
        meta = yaml.safe_load(block)
    except yaml.YAMLError as exc:
        pytest.fail(f"{path.name}: frontmatter is not valid YAML: {exc}")

    assert isinstance(meta, dict), f"{path.name}: frontmatter is not a YAML mapping"

    # `name` is what the Agent tool's subagent_type resolves against; a mismatch
    # with the filename makes the agent undispatchable by its own file name.
    assert "name" in meta, f"{path.name}: frontmatter has no 'name'"
    assert str(meta["name"]).strip() == path.stem, (
        f"{path.name}: frontmatter name {str(meta['name']).strip()!r} "
        f"!= filename stem {path.stem!r}"
    )

    # Without a description the agent is invisible to selection.
    assert str(meta.get("description", "")).strip(), f"{path.name}: frontmatter has no 'description'"

    # Body has to carry actual instructions, not just frontmatter.
    assert body.strip(), f"{path.name}: no instruction body after frontmatter"


def test_pr_reviewer_requires_recurring_failure_mode_evidence() -> None:
    """Keep issue #332's adversarial probes in the review output contract."""
    text = (AGENTS_DIR / "pr-reviewer.md").read_text(encoding="utf-8")
    _, body = _split_frontmatter(text)
    audit_path = (
        AGENTS_DIR.parent.parent / "docs" / "pr-review-failure-mode-audit.md"
    )

    for probe_id in PR_REVIEW_PROBE_IDS:
        assert f"`{probe_id}`" in body, f"pr-reviewer is missing {probe_id}"

    assert audit_path.is_file()
    assert "docs/pr-review-failure-mode-audit.md" in body
    assert "## Output" in body
    output_contract = body.split("## Output", 1)[1]
    assert "PASS / FAIL / N/A" in output_contract
    assert "evidence" in output_contract.lower()
