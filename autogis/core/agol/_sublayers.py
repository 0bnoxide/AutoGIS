"""Shared AGOL sublayer resolution — id-matched across layers AND tables.

``layer_index`` throughout core/agol is AGOL's REST/portal sublayer id (the
continuous ``?sublayer=N`` numbering across a service's layers+tables
combined), NOT a positional index into the arcgis API's separate
``.layers[]``/``.tables[]`` arrays. Positional ``item.layers[layer_index]``
has two failure modes: it can never reach a table at all, and on a service
with gappy/interleaved sublayer ids it silently resolves the wrong sublayer
(the arcgis API guarantees neither id-sorted arrays nor a layers-then-tables
layout). Match on each sublayer's own ``.properties.id`` instead — the same
fix as ``core/harvest/harvester.resolve_layer``.

No arcgis import: this operates only on an already-fetched Item object, so
it stays importable (and headlessly testable) without arcgis installed.
"""


def _prop(props, key, default=None):
    """Read ``key`` from a dict-like or attribute-style ``.properties``."""
    if isinstance(props, dict):
        return props.get(key, default)
    return getattr(props, key, default)


def resolve_sublayer(item, layer_index, item_id):
    """Return the sublayer of ``item`` whose REST sublayer id == layer_index.

    Searches ``item.layers`` and ``item.tables`` combined. Raises ValueError
    naming ``item_id`` and the sublayer ids that do exist when nothing
    matches.
    """
    sublayers = list(item.layers or []) + list(item.tables or [])
    by_id = {_prop(s.properties, "id"): s for s in sublayers}
    if layer_index not in by_id:
        raise ValueError(
            f"layer_index {layer_index} does not match any sublayer id for "
            f"item {item_id}: available ids are "
            f"{sorted(i for i in by_id if i is not None)}")
    return by_id[layer_index]
