"""Attachment-harvester core (arcpy-free).

Regular package (not a PEP 420 namespace package) on purpose: the
codebase-memory indexer only walks directories that contain an ``__init__.py``,
so without this file the harvester source is silently absent from the knowledge
graph while its tests still index — every sibling ``core`` subpackage has one.
``HarvestConfig`` is canonical in ``autogis.core.common.config`` and re-exported
from ``.models`` for back-compat.
"""
