# arcgis Session Consolidation + Version Pin — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans
> to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Retire the legacy `gis_session.py` wrapper, consolidate on
`runtime/sessions.py`, and pin the `arcgis` cloud extra to Pro 3.5.x range.

**Architecture:** Thin shim replaces the old module; canonical builder is
`agol_from_profile` in `runtime/sessions.py`. `pyproject.toml` gains a
version bound on the `cloud` extra.

**Tech Stack:** Python `pyproject.toml`, stdlib only — no new runtime deps.

**Source spec:** `docs/superpowers/specs/2026-06-23-arcgis-session-consolidation.md`
**Repo integration source:** `docs/repo-integration-roadmap.md` Tier 1A + Tier 2

## Global Constraints

- `runtime/sessions.py` is the canonical builder. Do NOT add logic there.
- `core/harvest/gis_session.py` MUST remain importable (shim, not deleted) —
  tests import `from autogis.core import gis_session` via `core/__init__.py`.
- Version pin must be verified against `arcgis-dist.json` before committing.
- All 127 tests must pass after every task.
- Do NOT modify `runtime/sessions.py` — it is already correct.

## File Structure

- **Modify:** `autogis/core/harvest/gis_session.py` — replace with thin shim
- **Modify:** `pyproject.toml` — add version pin on `cloud` extra
- **Read-only audit:** `autogis/core/__init__.py` — confirm re-export is safe
- **Read-only audit:** `tests/test_gis_session.py` — confirm tests use shim API

---

### Task 1: Verify arcgis version for Pro 3.5.x via arcgis-dist.json

**Files:** read-only (fetch external)

**Interfaces:**
- Consumes: `Esri/arcpy` GitHub repo, path `docs/arcgis-dist.json` (public repo)
- Produces: confirmed version string (e.g. `"2.4.0"`) → used in Task 3 pin

- [ ] **Step 1: Fetch `arcgis-dist.json`**

  Use `mcp__github__get_file_contents` on `owner=Esri, repo=arcpy,
  path=docs/arcgis-dist.json`. Locate the entry for ArcGIS Pro 3.5.x and
  extract the `arcgis` package version.

  If the file does not exist at that path, try `arcgis-versions.json` or
  search the repo root. Record the confirmed version for Task 3.

- [ ] **Step 2: Decide the pin range**

  `arcgis>=<major>.<minor>,<<major+1>` where `<major>.<minor>` is the version
  for Pro 3.5.x. Example: if version is `2.4.0` → pin is `arcgis>=2.4,<3`.

---

### Task 2: Audit existing callers of `gis_session`

**Files:** read-only

**Interfaces:**
- Consumes: `autogis/core/__init__.py`, `tests/test_gis_session.py`,
  any other file referencing `gis_session`
- Produces: confirmed shim API surface (which functions must be re-exported)

- [ ] **Step 1: List every caller**

  `grep -rn "gis_session\|build_gis\|build_gis_from_env" autogis/ tests/`
  and record each.

- [ ] **Step 2: Confirm the shim API**

  The shim must expose at minimum: `build_gis(...)` and `build_gis_from_env(...)`.
  Confirm against `tests/test_gis_session.py` function signatures.

---

### Task 3: Replace `gis_session.py` with a thin shim

**Files:**
- Modify: `autogis/core/harvest/gis_session.py`

**Interfaces:**
- Consumes: `runtime/sessions.py:agol_from_profile` (canonical builder)
- Produces: `build_gis`, `build_gis_from_env` delegates — same signatures as today

- [ ] **Step 1: Write the shim**

  Replace the contents of `gis_session.py` with:

  ```python
  """Back-compat shim. Canonical builder: autogis.runtime.sessions.agol_from_profile."""
  from autogis.runtime.sessions import agol_from_profile as _agol

  AGOL_URL = "https://www.arcgis.com"


  def build_gis(profile=None, username=None, password=None, gis_factory=None):
      return _agol(profile=profile, url=AGOL_URL if username else None,
                   username=username, password=password, gis_factory=gis_factory)


  def build_gis_from_env(profile, gis_factory=None):
      import os
      return build_gis(profile=profile,
                       username=os.environ.get("AGOL_USER"),
                       password=os.environ.get("AGOL_PASS"),
                       gis_factory=gis_factory)
  ```

- [ ] **Step 2: Run tests**

  `python -m pytest tests/ -q` — all 127 must pass.

---

### Task 4: Pin arcgis version in `pyproject.toml`

**Files:**
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: confirmed pin range from Task 1
- Produces: `cloud` extra with version constraint

- [ ] **Step 1: Update the cloud extra**

  Change:
  ```toml
  cloud = ["arcgis"]
  ```
  to:
  ```toml
  cloud = ["arcgis>=2.4,<3"]   # Pro 3.5.x (verified via arcgis-dist.json)
  ```
  (substitute the actual version from Task 1)

- [ ] **Step 2: Run tests**

  `python -m pytest tests/ -q` — all 127 must pass.

---

### Task 5: Commit

- [ ] `git add autogis/core/harvest/gis_session.py pyproject.toml`
- [ ] Commit: `"refactor: retire gis_session shim; pin arcgis cloud extra to Pro 3.5.x range"`

---

## Self-Review

**Spec coverage:** All three spec goals addressed — canonical builder (Task 3),
version pin (Task 4), back-compat shim (Task 3 Step 1). Non-goal (no AGOL
feature work) respected. Covered.

**Placeholder scan:** Task 1 Step 2 has a concrete example for the pin range.
"substitute the actual version" is the only open item and it is gated on Task 1.

**Type consistency:** `build_gis` / `build_gis_from_env` signatures preserved
throughout; `agol_from_profile` is the canonical reference everywhere.
