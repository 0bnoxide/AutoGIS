"""Pure (arcpy-free) marshalling helpers for the .pyt GUI adapter.

The Esri ``.pyt`` toolbox imports ``arcpy`` at module top level, so the
param-marshalling + core-wiring logic lives here instead — importable and
unit-testable with neither ``arcgis`` nor ``arcpy`` present. Both the GUI
(`toolbox.pyt`) and the test suite go through this single seam.

Single validation source (MERGE_PLAN §2): construct AND validate the same
``HarvestConfig`` dataclass the CLI uses, including the url-XOR-item_id
invariant — enforced here at build time, not deferred to ``layer_ref()``.

Today this module covers only the harvester (``build_harvest_config`` /
``run_harvest``); the ten envmon ``.pyt`` tools still marshal parameters
inline in their own ``execute()`` bodies, which is fine while that logic
stays a thin pass-through to a core function. When an envmon tool's
``execute()`` grows beyond a pass-through (branching, multi-step
orchestration, error handling that isn't just "call core, print QA") --
e.g. ``FullPipeline``, ``toolbox.pyt`` -- move its marshalling into this
module per the harvester's pattern, so it becomes unit-testable outside
Pro instead of only discoverable by running the tool inside ArcGIS Pro.
See issue #108 / the fable-architecture-review finding M2.
"""
from autogis.core.harvest.models import HarvestConfig, AttachmentResult


def build_harvest_config(
    *,
    directory: str,
    group_template: str,
    filename_template: str,
    item_id: str | None = None,
    url: str | None = None,
    where: str = "1=1",
    incremental: bool = False,
    skip_existing: bool = True,
    retries: int = 3,
    backoff_seconds: float = 2,
) -> HarvestConfig:
    """Build + validate a HarvestConfig from marshalled GUI params.

    Enforces the (item_id XOR url) invariant up front (single validation
    source on the dataclass) rather than leaving it to ``layer_ref()``.
    """
    if bool(item_id) == bool(url):
        raise ValueError(
            "HarvestConfig requires exactly one of 'url' or 'item_id'.")
    config = HarvestConfig(
        directory=directory,
        group_template=group_template,
        filename_template=filename_template,
        item_id=item_id,
        url=url,
        where=where if where is not None else "1=1",
        incremental=incremental,
        skip_existing=skip_existing,
        retries=retries,
        backoff_seconds=backoff_seconds,
    )
    # Trip the dataclass's own validation now so a bad config fails at build
    # time, in either adapter, before any session work.
    config.layer_ref()
    return config


def run_harvest(config: HarvestConfig, session) -> list[AttachmentResult]:
    """Run the core harvester for ``config`` against an active GIS ``session``.

    Thin pass-through to ``core.harvest.harvest``; kept here so the .pyt's
    ``execute()`` stays pure marshalling.
    """
    from autogis.core.harvest.harvester import harvest

    summary = harvest(session, config)
    return list(summary.results)
