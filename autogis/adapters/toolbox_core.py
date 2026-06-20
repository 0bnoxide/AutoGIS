"""Pure (arcpy-free) marshalling helpers for the .pyt GUI adapter.

The Esri ``.pyt`` toolbox imports ``arcpy`` at module top level, so the
param-marshalling + core-wiring logic lives here instead — importable and
unit-testable with neither ``arcgis`` nor ``arcpy`` present. Both the GUI
(`toolbox.pyt`) and the test suite go through this single seam.

Single validation source (MERGE_PLAN §2): construct AND validate the same
``HarvestConfig`` dataclass the CLI uses, including the url-XOR-item_id
invariant — enforced here at build time, not deferred to ``layer_ref()``.
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
    # The harvester records per-attachment results on its manifest; surface
    # them so the GUI renderer has something to report.
    manifest = getattr(summary, "manifest", None)
    if manifest is not None:
        return list(getattr(manifest, "results", []))
    return list(getattr(summary, "results", []))
