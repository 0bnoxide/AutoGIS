from pathlib import Path

from autogis.core.common.qa import QACollector
from autogis.core.envmon import validate_database as mod
from autogis.core.envmon.gdb_schema import FEATURE_SCHEMAS, TABLE_SCHEMAS


class _Field:
    def __init__(self, name):
        self.name = name


class _Cursor:
    def __enter__(self):
        return iter(())

    def __exit__(self, *_args):
        return None


class _ArcPy:
    class da:
        SearchCursor = staticmethod(lambda *_args: _Cursor())

    @staticmethod
    def Exists(_path):
        return True

    @staticmethod
    def ListFields(path):
        name = Path(path).name
        schema = TABLE_SCHEMAS.get(name)
        if schema is None:
            _geometry, schema = FEATURE_SCHEMAS[name]
        return [_Field(field[0]) for field in schema]


def test_schema_validation_unwraps_feature_class_geometry(monkeypatch):
    monkeypatch.setattr(mod, "_arcpy", lambda: _ArcPy())

    qa = QACollector()
    summary = mod.validate_database(Path("scratch.gdb"), qa, {})

    assert summary == {
        "tables_checked": len(TABLE_SCHEMAS) + len(FEATURE_SCHEMAS),
        "issues": 0,
    }
