"""Pin the frontmatter contract for .claude/agents/*.md.

Agent definitions are discovered by frontmatter. A malformed block, a missing
``name``, or a ``name`` that disagrees with the filename does not raise — the
agent simply never loads, and a prompt that dispatches it fails at runtime with
no signal here. These tests turn that silent failure into a red test.
"""
import re
from pathlib import Path

import pytest

AGENTS_DIR = Path(__file__).resolve().parent.parent / ".claude" / "agents"
FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


def _agent_files() -> list[Path]:
    return sorted(AGENTS_DIR.glob("*.md"))


def test_agents_dir_is_populated() -> None:
    """Guards against the glob silently going empty (moved/renamed dir)."""
    assert _agent_files(), f"no agent definitions found under {AGENTS_DIR}"


@pytest.mark.parametrize("path", _agent_files(), ids=lambda p: p.name)
def test_agent_frontmatter_is_valid(path: Path) -> None:
    text = path.read_text(encoding="utf-8")

    match = FRONTMATTER.match(text)
    assert match, f"{path.name}: missing or malformed YAML frontmatter block"

    keys = dict(re.findall(r"^(\w+):\s*(.+)$", match.group(1), re.MULTILINE))

    # `name` is what the Agent tool's subagent_type resolves against; a mismatch
    # with the filename makes the agent undispatchable by its own file name.
    assert "name" in keys, f"{path.name}: frontmatter has no 'name'"
    assert keys["name"].strip() == path.stem, (
        f"{path.name}: frontmatter name {keys['name'].strip()!r} != filename stem {path.stem!r}"
    )

    # Without a description the agent is invisible to selection.
    assert keys.get("description", "").strip(), f"{path.name}: frontmatter has no 'description'"

    # Body has to carry actual instructions, not just frontmatter.
    assert text[match.end():].strip(), f"{path.name}: no instruction body after frontmatter"
