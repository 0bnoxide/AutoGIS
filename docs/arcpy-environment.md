# Running AutoGIS with arcpy — the two-environment model

AutoGIS deliberately lives in **two Python environments** on a dev machine.
Neither replaces the other.

| | Dev environment | ArcGIS Pro environment |
|---|---|---|
| Interpreter | `python` (3.14, on PATH) | Pro's conda Python (3.13.7) |
| Has arcpy | **No — and never can** | Yes (arcpy 3.6.1, Pro 3.6.1) |
| Used for | the full test suite, all headless tools, everything in `core/`/`adapters/` | Tools 2–8 (LOCAL), the `.pyt` toolbox, functional QA that actually calls arcpy |
| AutoGIS install | `pip install -e` (dev venv) | editable install in the **cloned** env (below) |

**Why arcpy can't go in the dev env:** arcpy is not on PyPI. It ships only
inside ArcGIS Pro's bundled conda runtime (`arcgispro-py3`) and only supports
that runtime's Python version. The dev suite runs arcpy-free *by design* —
the repo invariant is that `core/` and `adapters/` import with neither
`arcpy` nor `arcgis` present, and the tests enforce it.

## The cloned Pro env (set up 2026-07-17)

Esri warns against pip-installing into the default `arcgispro-py3` (a Pro
upgrade wipes it, and breaking it breaks Pro). So AutoGIS is installed into a
**clone**:

```
%LOCALAPPDATA%\ESRI\conda\envs\arcgispro-py3-autogis
```

How it was created (repeat after a Pro upgrade — upgrades orphan old clones):

```bat
"C:\Program Files\ArcGIS\Pro\bin\Python\Scripts\conda.exe" create --yes ^
    --name arcgispro-py3-autogis ^
    --clone "C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3"
%LOCALAPPDATA%\ESRI\conda\envs\arcgispro-py3-autogis\python.exe ^
    -m pip install -e C:\Users\ichbi\AutoGIS --no-deps
```

`--no-deps` is deliberate: every AutoGIS dependency (click, openpyxl, pyyaml,
…) already ships in the Pro env, and letting pip "upgrade" conda-managed
packages (numpy, pandas) inside a Pro env is the classic way to break arcpy.

Known cosmetic issue: `pip check` in this env complains that `arcgis` wants
`pyarrow`/`pywin32`. That's pre-existing in Esri's base env, not caused by
the AutoGIS install.

## How to run things

**CLI with arcpy, main checkout** (editable install → tracks whatever branch
`C:\Users\ichbi\AutoGIS` has checked out):

```bat
%LOCALAPPDATA%\ESRI\conda\envs\arcgispro-py3-autogis\Scripts\autogis.exe envmon <command> ...
```

**CLI with arcpy, any worktree / uninstalled checkout** — `PYTHONPATH` wins
over the installed package, so pin it (`autogis/__main__.py` exists for
exactly this — console scripts only exist where the package is installed):

```bat
set PYTHONPATH=C:\Users\ichbi\AutoGIS\.claude\worktrees\<wt>
%LOCALAPPDATA%\ESRI\conda\envs\arcgispro-py3-autogis\python.exe -m autogis envmon <command> ...
```

**Inside ArcGIS Pro** (the `.pyt` toolbox, GUI-driven QA like issue #238):
switch Pro's active environment to the clone (Package Manager → Environments,
or `proswap arcgispro-py3-autogis`), restart Pro, add
`autogis\adapters\toolbox.pyt`. Note `propy.bat` always resolves to Pro's
*active* env — after a proswap it launches the clone.

**GUI LOCAL-tool runs** (`autogis-gui`): point the `local_python` picker at
the clone's `python.exe`.

**The test suite stays on the dev env.** Never run `pytest` from the Pro env
as "the" suite — it would mask arcpy-free-invariant violations (imports that
only succeed because arcpy happens to be present).

## Quick sanity check

```bat
%LOCALAPPDATA%\ESRI\conda\envs\arcgispro-py3-autogis\python.exe ^
    -c "import arcpy, autogis; print(arcpy.GetInstallInfo()['Version'], autogis.__file__)"
```

Expected: the Pro version and `C:\Users\ichbi\AutoGIS\autogis\__init__.py`.
If `autogis` fails to import after a Pro upgrade, the clone is stale —
recreate it with the commands above.
