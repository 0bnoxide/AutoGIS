# Installing the AutoGIS toolbox into ArcGIS Pro

The `.pyt` toolbox (`autogis/adapters/toolbox.pyt`) is a thin GUI marshaller
over the installed `autogis` package. It does **not** use a `sys.path` hack to
find the core — instead you install `autogis` into a clone of the ArcGIS Pro
Python environment so `import autogis...` resolves normally.

## 1. Clone the Pro Python environment

ArcGIS Pro ships a managed conda env named `arcgis-pro-py3` (the interpreter
is `arcgispro-py3`). Never install into the default env — clone it first so
Pro's baseline stays intact.

From the **Python Command Prompt** that ships with Pro (or via `conda`):

```bash
conda create --clone arcgispro-py3 --name autogis-py3
proswap autogis-py3          # make the clone the active Pro env
```

(`proswap` is the Pro-bundled helper; alternatively switch the active env via
Pro → Settings → Package Manager → Environments.)

## 2. Install autogis editable into the clone

With the cloned env active, install this repo in editable mode so code edits
are picked up without reinstalling:

```bash
conda activate autogis-py3        # if not already active
cd /path/to/AutoGIS
pip install -e .
```

Verify the core imports with neither `arcgis` nor `arcpy` required:

```bash
python -c "from autogis.adapters import toolbox_core; print('ok')"
```

If you need the cloud (`arcgis`) extra for AGOL harvesting outside Pro:

```bash
pip install -e ".[cloud]"
```

`arcpy` is **not** a pip dependency — it ships with Pro and is detected at
runtime. The LOCAL tools (2–8) only run inside Pro.

## 3. Add the toolbox to a Pro project

In the **Catalog** pane: right-click **Toolboxes → Add Toolbox**, browse to
`autogis/adapters/toolbox.pyt`, and select it. The **AutoGIS Suite** toolbox
(alias `autogis`) appears with its tool(s), e.g. **Harvest Attachments**.

## 4. Toolbox cache / reload gotcha

ArcGIS Pro **caches** loaded Python toolboxes. After editing the `.pyt` or any
imported `autogis` module, the running Pro process will keep executing the
stale, cached code. To reload:

- **Edited the `.pyt` itself** (params, labels, `execute` body): right-click
  the toolbox in Catalog → **Refresh**. Often enough on its own.
- **Edited an imported `autogis` module** (e.g. `toolbox_core.py`,
  anything under `autogis.core`): Pro will not re-import an already-imported
  module. **Restart ArcGIS Pro** to pick up the change. A toolbox Refresh
  alone does *not* re-import already-loaded Python modules.

When in doubt after an import-graph change, restart Pro — it is the only
reliable way to clear cached `autogis.*` modules.
