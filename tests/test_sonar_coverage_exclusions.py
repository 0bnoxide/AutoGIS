"""`sonar.coverage.exclusions` must track the modules CI cannot cover (#491).

CI installs `.[dev]`, which has no PySide6 (it is in the `gui` extra), so every
GUI test self-skips via `pytest.importorskip("PySide6")`. Any module importing
PySide6 at module load therefore reports 0% coverage in CI and — since
`sonar.sources=autogis` — is held to a new-code coverage gate it is
structurally unable to meet. That failed the SonarCloud check on every GUI-only
PR (live on #490) while the suite itself was green.

Excluding those modules fixes it; the drift is what recurs. This pins the
exclusion list to the *reason* for it, in both directions: a new widgets module
that forgets the exclusion fails here rather than in CI three PRs later, and a
module that stops importing PySide6 loses its exemption rather than quietly
keeping it.
"""
import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_GUI = _ROOT / "autogis" / "adapters" / "gui"


def _imports_pyside6_at_module_load(path: Path) -> bool:
    """True when PySide6 is imported at module scope, not inside a def/if."""
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.ImportFrom):
            if (node.module or "").startswith("PySide6"):
                return True
        elif isinstance(node, ast.Import):
            if any(a.name.startswith("PySide6") for a in node.names):
                return True
    return False


def _declared_exclusions() -> set:
    text = (_ROOT / "sonar-project.properties").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("sonar.coverage.exclusions="):
            value = line.split("=", 1)[1]
            return {p.strip() for p in value.split(",") if p.strip()}
    return set()


def test_exclusions_are_exactly_the_uncoverable_gui_modules():
    uncoverable = {
        f"autogis/adapters/gui/{p.name}"
        for p in sorted(_GUI.glob("*.py"))
        if _imports_pyside6_at_module_load(p)
    }
    assert uncoverable, "expected at least one PySide6-at-module-load GUI module"
    assert _declared_exclusions() == uncoverable, (
        "sonar.coverage.exclusions has drifted from the modules CI cannot "
        "cover; add/remove the path in sonar-project.properties (#491)."
    )


def test_pyside6_free_gui_logic_stays_under_the_gate():
    """The exemption is for widgets, not for the GUI adapter wholesale — the
    logic modules run in CI and must keep being measured."""
    excluded = _declared_exclusions()
    for name in ("config_builder.py", "executor.py", "runner.py",
                 "introspect.py", "reachability.py", "forms.py"):
        assert f"autogis/adapters/gui/{name}" not in excluded


if __name__ == "__main__":  # ponytail self-check
    test_exclusions_are_exactly_the_uncoverable_gui_modules()
    test_pyside6_free_gui_logic_stays_under_the_gate()
    print("ok")
