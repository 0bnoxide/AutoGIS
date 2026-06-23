# AGOL Publish / Overwrite Feature Layer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans
> to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** `core/agol/publish.py` with `publish_or_overwrite_layer(gis, config,
source_path, qa)` — idempotently creates or overwrites a hosted AGOL feature
service. CLI subcommand `autogis agol publish-layer`.

**Architecture:** New `core/agol/` sub-package; `adapters/cli.py` gains an
`agol` click group with one command. Fully injected; no live AGOL in tests.

**Tech Stack:** `arcgis` (cloud extra), `click`, `dataclasses`, `QACollector`.

**Source spec:** `docs/superpowers/specs/2026-06-23-agol-publish-layer.md`
**Repo integration source:** `docs/repo-integration-roadmap.md` Tier 1A
**Envmon roadmap:** §6.1 `PublishEnvironmentalLayersToAGOL`

## Global Constraints

- `core/agol/publish.py` MUST NOT import `arcpy` or `arcgis` at module level.
  All arcgis surface is lazy (inside function bodies).
- `gis` is always injected; never instantiated inside `publish.py`. This keeps
  the module testable without credentials.
- All publish outcomes flow through `QACollector`; the function does not raise
  unless the pre-condition check fails (e.g. source file does not exist).
- `adapters/cli.py` is the only place that calls `agol_from_profile` to build
  the GIS. Core stays runtime-agnostic.
- All existing 127 tests must stay green.

## File Structure

- **Create:** `autogis/core/agol/__init__.py`
- **Create:** `autogis/core/agol/publish.py`
- **Modify:** `autogis/adapters/cli.py` — add `agol` click group + `publish-layer` command
- **Create:** `tests/test_agol_publish.py`

---

### Task 1: Scaffold `core/agol/` package

**Files:**
- Create: `autogis/core/agol/__init__.py`
- Create: `autogis/core/agol/publish.py`

**Interfaces:**
- Consumes: `autogis.core.common.qa.QACollector`, `autogis.core.common.qa.SEV_*`
- Produces: `PublishConfig` dataclass, `publish_or_overwrite_layer` function

- [ ] **Step 1: Create the package init**

  ```python
  # autogis/core/agol/__init__.py
  ```
  (empty — package marker only)

- [ ] **Step 2: Write `publish.py`**

  ```python
  """Publish or overwrite a hosted AGOL feature service.

  Requires the ``cloud`` extra (arcgis). All arcgis imports are lazy.
  """
  from __future__ import annotations
  from dataclasses import dataclass, field
  from pathlib import Path
  from typing import List, Optional

  from ..common.qa import QACollector, SEV_INFO, SEV_ERROR


  @dataclass
  class PublishConfig:
      title: str
      tags: List[str]
      description: str = ""
      folder: Optional[str] = None
      share_with: str = "org"    # "private" | "org" | "everyone"
      overwrite: bool = True


  def publish_or_overwrite_layer(
      gis,
      config: PublishConfig,
      source_path: str,
      qa: Optional[QACollector] = None,
  ) -> Optional[object]:
      """Publish or overwrite a hosted feature service.

      Returns the published Item on success, None on failure (error in qa).
      ``source_path`` must be a zip of an FGDB or a JSON FeatureSet — the
      caller is responsible for preparing it.
      """
      qa = qa or QACollector()
      src = Path(source_path)
      if not src.exists():
          qa.add(SEV_ERROR, "publish_source_missing",
                 f"source file does not exist: {src}")
          return None

      try:
          matches = gis.content.search(f'title:"{config.title}"', item_type="Feature Service")
          existing = next((m for m in matches if m.title == config.title), None)

          if existing and config.overwrite:
              try:
                  from arcgis.features.managers import FeatureLayerManager
                  mgr = FeatureLayerManager(existing.layers[0].url, gis)
                  mgr.overwrite(str(src))
                  qa.add(SEV_INFO, "publish_overwritten",
                         f"overwritten hosted feature service: {config.title}",
                         recommended_action="verify symbology and sharing in AGOL")
                  return existing
              except Exception as exc:
                  qa.add(SEV_ERROR, "publish_overwrite_failed",
                         f"overwrite failed for '{config.title}': {exc}")
                  return None

          item_props = {
              "title": config.title,
              "tags": ",".join(config.tags),
              "description": config.description,
              "type": "File Geodatabase",
          }
          item = gis.content.add(item_props, data=str(src),
                                 folder=config.folder)
          published = item.publish()
          if config.share_with != "private":
              everyone = config.share_with == "everyone"
              published.share(org=True, everyone=everyone)
          qa.add(SEV_INFO, "publish_created",
                 f"created hosted feature service: {config.title}",
                 recommended_action="verify symbology and sharing in AGOL")
          return published

      except Exception as exc:
          qa.add(SEV_ERROR, "publish_failed",
                 f"publish failed for '{config.title}': {exc}")
          return None
  ```

- [ ] **Step 3: Run tests**

  `python -m pytest tests/ -q` — 127 tests must pass (new module, no tests yet).

---

### Task 2: Write `tests/test_agol_publish.py`

**Files:**
- Create: `tests/test_agol_publish.py`

**Interfaces:**
- Consumes: `PublishConfig`, `publish_or_overwrite_layer`, `QACollector`
- Produces: 5+ test cases covering create, overwrite, missing source, failed overwrite, share

- [ ] **Step 1: Write the test module**

  Use a `MockGIS` object that records `.content.search()`, `.content.add()`, and
  `.item.publish()` calls. No live AGOL needed.

  Cover:
  1. `test_publish_creates_new_item` — search returns empty, add+publish called.
  2. `test_publish_overwrites_existing` — search returns a match, overwrite called.
  3. `test_publish_missing_source_emits_qa_error` — source file absent → SEV_ERROR,
     returns None.
  4. `test_publish_overwrite_failure_emits_qa_error` — overwrite raises → SEV_ERROR.
  5. `test_publish_qa_info_on_success` — successful path emits SEV_INFO record.

- [ ] **Step 2: Run tests**

  `python -m pytest tests/test_agol_publish.py -v` — all 5 must pass.
  `python -m pytest tests/ -q` — still 127 + 5 = 132 total passing.

---

### Task 3: Wire CLI command `autogis agol publish-layer`

**Files:**
- Modify: `autogis/adapters/cli.py`

**Interfaces:**
- Consumes: `agol_from_profile` (from `runtime/sessions.py`),
  `PublishConfig`, `publish_or_overwrite_layer`, `QACollector`
- Produces: `autogis agol publish-layer --title ... --source ... --tags ...`

- [ ] **Step 1: Add `agol` click group to `cli.py`**

  Below the existing `envmon` group, add:

  ```python
  @autogis.group()
  def agol():
      """AGOL / cloud tools."""

  @agol.command("publish-layer")
  @click.option("--profile", default=None, help="ArcGIS API for Python profile name")
  @click.option("--title", required=True, help="Hosted service title")
  @click.option("--source", required=True, type=click.Path(exists=True),
                help="Zip of FGDB or JSON FeatureSet to publish")
  @click.option("--tags", default="autogis", help="Comma-separated AGOL tags")
  @click.option("--folder", default=None, help="AGOL content folder (default: root)")
  @click.option("--share-with", default="org",
                type=click.Choice(["private", "org", "everyone"]),
                help="Sharing level after publish")
  @click.option("--no-overwrite", is_flag=True, default=False,
                help="Fail if a service with this title already exists")
  def publish_layer(profile, title, source, tags, folder, share_with, no_overwrite):
      """Publish or overwrite a hosted AGOL feature service."""
      from autogis.core.agol.publish import PublishConfig, publish_or_overwrite_layer
      from autogis.core.common.qa import QACollector
      gis = agol_from_profile(profile)
      cfg = PublishConfig(
          title=title,
          tags=[t.strip() for t in tags.split(",")],
          folder=folder,
          share_with=share_with,
          overwrite=not no_overwrite,
      )
      qa = QACollector()
      result = publish_or_overwrite_layer(gis, cfg, source, qa)
      for rec in qa.records:
          click.echo(f"[{rec.severity}] {rec.message}")
      if result is None:
          raise SystemExit(1)
  ```

- [ ] **Step 2: Smoke-test the CLI wiring**

  `python -m pytest tests/ -q` — all 132 must still pass.
  `autogis agol --help` must print the publish-layer command.

---

### Task 4: Commit

- [ ] `git add autogis/core/agol/ autogis/adapters/cli.py tests/test_agol_publish.py`
- [ ] Commit: `"feat: add AGOL publish/overwrite feature layer — core/agol/publish.py + CLI"`

---

## Self-Review

**Spec coverage:** All 5 spec goals addressed — `core/agol/publish.py` (Task 1),
testable with mock (Task 2), CLI subcommand (Task 3), arcpy-free (Global Constraints),
QA-emitting (Task 1 Step 2). Non-goals (multi-layer, sync) not touched. Covered.

**Placeholder scan:** Mock GIS is described by behavior, not "TBD". CLI options
are enumerated. No empty sections.

**Type consistency:** `publish_or_overwrite_layer` signature is identical in spec,
plan, and code stub. `PublishConfig` fields are the same everywhere. `QACollector`
injection pattern mirrors existing envmon modules.
