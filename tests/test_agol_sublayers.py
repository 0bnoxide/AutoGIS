"""Direct tests for the shared sublayer-id resolver (autogis.core.agol._sublayers).

Same precedent as tests/test_harvester.py's resolve_layer coverage: a gappy/
non-zero id, a table reached through the combined layers+tables list, and
the out-of-range error message.
"""
import pytest

from autogis.core.agol._sublayers import resolve_sublayer


class _Sub:
    def __init__(self, **props):
        self.properties = props


class _Item:
    def __init__(self, layers=(), tables=()):
        self.layers = list(layers)
        self.tables = list(tables)


def test_resolve_sublayer_matches_by_id_not_position():
    # Position 0 carries id=7 -- resolving layer_index=7 must match by id,
    # not treat 7 as an out-of-bounds position in a 1-element list.
    target = _Sub(id=7)
    item = _Item(layers=[target])
    assert resolve_sublayer(item, 7, "item-1") is target


def test_resolve_sublayer_reaches_table_in_combined_list():
    # layer_index counts across layers-then-tables combined (AGOL
    # ?sublayer=N numbering): 2 layers + 1 table before the target means
    # index 3 = tables[1].
    target = _Sub(id=3)
    item = _Item(layers=[_Sub(id=0), _Sub(id=1)],
                 tables=[_Sub(id=2), target])
    assert resolve_sublayer(item, 3, "item-1") is target


def test_resolve_sublayer_out_of_range_raises_with_available_ids():
    item = _Item(layers=[_Sub(id=0), _Sub(id=7)])
    with pytest.raises(ValueError, match="does not match any sublayer id"):
        resolve_sublayer(item, 5, "item-42")
    with pytest.raises(ValueError, match=r"item-42.*\[0, 7\]"):
        resolve_sublayer(item, 5, "item-42")
