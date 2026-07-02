# Implementation moved to table_normalizer; this file is a re-export shim.
# Kept as an import-stable seam: import_to_gdb.py and tests/ import this
# module path directly -- do not delete without checking those callers.
from .table_normalizer import normalize_ibi_table as normalize_ibi_table  # noqa: F401
