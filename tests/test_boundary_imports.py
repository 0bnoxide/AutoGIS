"""The arcpy-free boundary, enforced mechanically.

Key invariant (CLAUDE.md / ADR-0002): every module under ``autogis/`` must
import with neither ``arcpy`` nor ``arcgis`` present. Before this test the
invariant was only enforced incidentally — a new module with a top-level
``import arcpy`` would pass CI as long as no other test happened to import it.

Works in both environments: headless (import fails loudly) and inside an
ArcGIS Pro env (the module would import, but the sys.modules assertion
catches the eager arcpy/arcgis import).

``autogis.adapters.gui.*`` (ADR-0057) requires the optional ``gui`` extra
(``PySide6``), which ``pip install -e ".[dev]"`` does not pull in — a missing
``PySide6`` is a separate, expected condition, not an arcpy/arcgis coupling.
So the GUI modules are skipped only when PySide6 is absent; when the extra IS
installed they are still checked, preserving the boundary guarantee for them.
"""
import ast
import importlib
import pkgutil
import sys
from pathlib import Path

import autogis

try:
    import PySide6  # noqa: F401
    _HAS_PYSIDE6 = True
except ImportError:
    _HAS_PYSIDE6 = False


def test_every_autogis_module_imports_headless():
    for name in ("arcpy", "arcgis"):
        sys.modules.pop(name, None)
    failed = []
    for mod in pkgutil.walk_packages(autogis.__path__, prefix="autogis."):
        if not _HAS_PYSIDE6 and mod.name.startswith("autogis.adapters.gui"):
            continue
        try:
            importlib.import_module(mod.name)
        except Exception as exc:  # noqa: BLE001 - report every failure at once
            failed.append(f"{mod.name}: {exc!r}")
    assert not failed, "not importable without arcpy/arcgis:\n" + "\n".join(failed)
    eager = [n for n in ("arcpy", "arcgis") if n in sys.modules]
    assert not eager, f"importing autogis eagerly pulled in: {eager}"


def test_pyt_toolbox_parses():
    # toolbox.pyt imports arcpy at top level (by design, ADR-0006) so it can
    # never be imported headless — but a syntax error in it must not wait for
    # an ArcGIS Pro session to be discovered.
    src = Path(autogis.__file__).parent / "adapters" / "toolbox.pyt"
    ast.parse(src.read_text(encoding="utf-8"), filename=str(src))


def test_core_does_not_import_adapters():
    core = Path(autogis.__file__).parent / "core"
    violations = []
    for path in core.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
                level = 0
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
                level = node.level
            else:
                continue
            if any(name == "autogis.adapters"
                   or name.startswith("autogis.adapters.")
                   or (level and name == "adapters")
                   for name in names):
                violations.append(str(path.relative_to(core.parent)))
    assert not violations, f"core -> adapter imports: {sorted(set(violations))}"
