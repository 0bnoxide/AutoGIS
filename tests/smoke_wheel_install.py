"""Build and exercise a base-only wheel outside the checkout (no pytest needed)."""
from __future__ import annotations

import importlib.metadata
import importlib.resources
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import sysconfig
import tempfile


def run(*args: str | Path, expected: int = 0, cwd: Path | None = None) -> str:
    result = subprocess.run(
        [str(arg) for arg in args], capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=180, cwd=cwd,
    )
    output = result.stdout + result.stderr
    print(output, end="", flush=True)
    assert result.returncode == expected, (args, result.returncode, output)
    return output


def check_install(checkout: Path) -> None:
    import autogis
    from autogis.adapters.gui.executor import build_argv
    from autogis.core.common.workflow_recipe import load_recipe, save_recipe

    assert sys.prefix != sys.base_prefix, "smoke must use a disposable venv"
    assert not Path.cwd().resolve().is_relative_to(checkout)
    assert not any(Path(p).resolve().is_relative_to(checkout) for p in sys.path)
    installed = Path(sysconfig.get_path("purelib")).resolve()
    assert Path(autogis.__file__).resolve().is_relative_to(installed), autogis.__file__
    print(f"Installed package: {autogis.__file__}", flush=True)

    scripts = {ep.name: ep.value for ep in
               importlib.metadata.distribution("autogis").entry_points
               if ep.group == "console_scripts"}
    assert scripts == {
        "autogis": "autogis.adapters.cli:autogis",
        "autogis-harvest": "autogis.adapters.cli:harvest_cmd",
        "autogis-gui": "autogis.adapters.gui.app:main",
    }, scripts
    package = importlib.resources.files("autogis")
    resources = [
        "config/_templates/site_skeleton/site.yaml",
        "config/_templates/site_skeleton/event_config.yaml",
        "config/_templates/site_skeleton/parser_profile.yaml",
        "config/_templates/site_skeleton/figure_spec.yaml",
        "config/recipes/monitoring_event_processing.yaml",
        "config/recipes/rtk_to_cad.yaml",
        "core/common/report_assets/report.css",
    ]
    for resource in resources:
        assert package.joinpath(resource).read_text(encoding="utf-8").strip(), resource
    for resource in resources[4:6]:
        recipe = load_recipe(Path(str(package.joinpath(resource))))
        for step in recipe["steps"]:
            if step.get("command"):
                build_argv(step["command"], step.get("values") or {})
    print("Packaged templates, recipes and CSS: OK", flush=True)

    executables = Path(sys.executable).parent
    suffix = ".exe" if os.name == "nt" else ""
    cli = executables / f"autogis{suffix}"
    run(cli, "--help")
    run(executables / f"autogis-harvest{suffix}", "--help")
    # Base install only: prove the GUI launcher reaches its optional-dependency seam.
    for optional in ("PySide6", "arcpy", "arcgis"):
        assert importlib.util.find_spec(optional) is None, optional
    gui = run(executables / f"autogis-gui{suffix}", "--help", expected=1)
    assert "ModuleNotFoundError: No module named 'PySide6'" in gui, gui
    run(cli, "envmon", "list-tools")

    dest = Path.cwd() / "site"
    run(cli, "envmon", "init-site", "--site-id", "WHEEL_SMOKE",
        "--site-name", "Wheel smoke fixture", "--dest", dest)
    assert len(list(dest.rglob("*.yaml"))) == 4
    recipe = save_recipe({"name": "Wheel smoke setup", "steps": [{
        "command": ["envmon", "init-site"],
        "values": {"site_id": "RECIPE_SMOKE", "site_name": "Recipe smoke fixture",
                   "dest": str(Path.cwd() / "recipe-site"), "dry_run": True},
    }]}, Path.cwd() / "recipe.yaml")
    run(cli, "envmon", "validate-recipe", recipe)
    assert "Final: done" in run(cli, "envmon", "run-recipe", recipe,
                               "--job-root", Path.cwd() / "job")
    assert not (Path.cwd() / "recipe-site").exists()
    for name, module in tuple(sys.modules.items()):
        if name == "autogis" or name.startswith("autogis."):
            if getattr(module, "__file__", None):
                assert Path(module.__file__).resolve().is_relative_to(installed), name
    print("Installed-wheel smoke: PASS (GUI optional dependency only)", flush=True)


def main() -> None:
    script = Path(__file__).resolve()
    checkout = script.parents[1]
    # Console launchers do not use -I, so remove inherited import overrides too.
    for key in ("PYTHONPATH", "PYTHONHOME", "PYTHONUSERBASE"):
        os.environ.pop(key, None)
    os.environ["PYTHONNOUSERSITE"] = "1"
    with tempfile.TemporaryDirectory(prefix="autogis-wheel-smoke-") as directory:
        root = Path(directory)
        assert not root.resolve().is_relative_to(checkout), "temp cwd must be outside checkout"
        os.environ["AUTOGIS_RUN_HISTORY"] = str(root / "run_history.csv")
        wheels = root / "wheels"
        run(sys.executable, "-I", "-m", "pip", "wheel", checkout,
            "--no-deps", "--no-cache-dir", "--wheel-dir", wheels, cwd=root)
        wheel, = wheels.glob("autogis-*.whl")
        run(sys.executable, "-I", "-m", "venv", root / "venv", cwd=root)
        python = root / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        run(python, "-I", "-m", "pip", "install", "--no-cache-dir", wheel, cwd=root)
        run(python, "-I", script, checkout, cwd=root)


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    if sys.argv[1:]:
        check_install(Path(sys.argv[1]).resolve())
    else:
        main()
