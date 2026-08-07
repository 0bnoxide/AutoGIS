"""Configuration loading and validation.

All site-, workbook-, analyte- and figure-specific behaviour lives in YAML or
JSON files under config/ (spec: General rules). YAML requires PyYAML, which
ships with the default ArcGIS Pro conda environment; JSON is always supported
as a fallback so the pipeline never hard-depends on PyYAML.

This module is the canonical home of the suite's config dataclasses. It keeps
envmon's TWO config styles (deltas C5): field-typed ``SheetProfile`` /
``ParserProfile`` and dict-backed ``__getattr__`` wrappers ``SiteConfig`` /
``FigureSpec``. ``HarvestConfig`` (the harvester job config) is re-expressed
field-typed here and re-exported from ``core/harvest/models.py`` for
back-compat.

Note: ``load_config`` here is envmon's flat YAML+JSON loader (the former
harness ``config_loader`` was retired; this is the only ``load_config`` now).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from openpyxl.utils import column_index_from_string


class ConfigError(Exception):
    """Blocking configuration problem (missing file/keys, bad column refs)."""


def load_config(path: Path) -> dict:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"Configuration file not found: {path}")
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover
            raise ConfigError(
                f"PyYAML is required to read {path.name}. Either run "
                f"'conda install pyyaml' in the ArcGIS Pro environment or "
                f"provide the same configuration as .json.") from exc
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a mapping at the top level")
    return data


def _require(data: dict, keys: List[str], context: str) -> None:
    missing = [k for k in keys if k not in data]
    if missing:
        raise ConfigError(f"{context}: missing required keys: {', '.join(missing)}")


def col_index(ref) -> Optional[int]:
    """Accept 'A', 'AB' or 1-based ints; return 1-based column index."""
    if ref is None:
        return None
    if isinstance(ref, int):
        return ref
    return column_index_from_string(str(ref).strip().upper())


# ---------------------------------------------------------------------------
# Site configuration
# ---------------------------------------------------------------------------
SITE_REQUIRED = ["site_id", "site_name", "project_number", "address", "city",
                 "state", "coordinate_system", "default_gdb",
                 "default_aprx_template", "monitoring_wells_fc",
                 "soil_borings_fc", "site_boundary_fc"]


@dataclass
class SiteConfig:
    data: dict
    path: Optional[Path] = None

    @classmethod
    def load(cls, path: Path) -> "SiteConfig":
        data = load_config(path)
        _require(data, SITE_REQUIRED, f"site config {path}")
        return cls(data=data, path=Path(path))

    # Typed accessors for SITE_REQUIRED fields — IDE-navigable, load-time validated.
    @property
    def site_id(self) -> str: return self.data["site_id"]
    @property
    def site_name(self) -> str: return self.data["site_name"]
    @property
    def project_number(self) -> str: return self.data["project_number"]
    @property
    def address(self) -> str: return self.data["address"]
    @property
    def city(self) -> str: return self.data["city"]
    @property
    def state(self) -> str: return self.data["state"]
    @property
    def coordinate_system(self) -> str: return self.data["coordinate_system"]
    @property
    def default_gdb(self) -> str: return self.data["default_gdb"]
    @property
    def default_aprx_template(self) -> str: return self.data["default_aprx_template"]
    @property
    def monitoring_wells_fc(self) -> str: return self.data["monitoring_wells_fc"]
    @property
    def soil_borings_fc(self) -> str: return self.data["soil_borings_fc"]
    @property
    def site_boundary_fc(self) -> str: return self.data["site_boundary_fc"]

    def __getattr__(self, item):
        try:
            return self.data[item]
        except KeyError as exc:
            raise AttributeError(item) from exc

    def get(self, key, default=None):
        return self.data.get(key, default)


# ---------------------------------------------------------------------------
# Parser profile
# ---------------------------------------------------------------------------
@dataclass
class SheetProfile:
    sheet_name: str
    data_type: str
    raw: dict

    # Row anchors (1-based, may be None where not applicable)
    title_rows: List[int] = field(default_factory=list)
    group_header_row: Optional[int] = None
    analyte_header_row: Optional[int] = None
    units_row: Optional[int] = None
    screening_level_row: Optional[int] = None
    data_start_row: int = 2
    data_end_detection_strategy: str = "consecutive_blank_ids:3"

    # Column anchors (1-based after resolution)
    id_column: Optional[int] = None
    sample_id_column: Optional[int] = None
    depth_column: Optional[int] = None
    screen_interval_column: Optional[int] = None
    date_column: Optional[int] = None
    mpe_column: Optional[int] = None
    dtw_column: Optional[int] = None
    gwe_column: Optional[int] = None
    analyte_columns: List[int] = field(default_factory=list)
    ignored_columns: List[int] = field(default_factory=list)
    rpd_layout: dict = field(default_factory=dict)
    source_cell_tracking_enabled: bool = True

    @classmethod
    def from_dict(cls, d: dict) -> "SheetProfile":
        _require(d, ["sheet_name", "data_type", "data_start_row"],
                 f"sheet profile {d.get('sheet_name', '?')}")
        cols = d.get("analyte_columns")
        analyte_cols: List[int] = []
        if isinstance(cols, dict) and "from" in cols and "to" in cols:
            analyte_cols = list(range(col_index(cols["from"]), col_index(cols["to"]) + 1))
        elif isinstance(cols, list):
            analyte_cols = [col_index(c) for c in cols]
        sp = cls(
            sheet_name=d["sheet_name"], data_type=d["data_type"], raw=d,
            title_rows=d.get("title_rows", []) or [],
            group_header_row=d.get("group_header_row"),
            analyte_header_row=d.get("analyte_header_row"),
            units_row=d.get("units_row"),
            screening_level_row=d.get("screening_level_row"),
            data_start_row=int(d["data_start_row"]),
            data_end_detection_strategy=d.get("data_end_detection_strategy",
                                              "consecutive_blank_ids:3"),
            id_column=col_index(d.get("id_column") or d.get("location_column")),
            sample_id_column=col_index(d.get("sample_id_column")),
            depth_column=col_index(d.get("depth_column")),
            screen_interval_column=col_index(d.get("screen_interval_column")),
            date_column=col_index(d.get("date_column")),
            mpe_column=col_index(d.get("mpe_column")),
            dtw_column=col_index(d.get("dtw_column")),
            gwe_column=col_index(d.get("gwe_column")),
            analyte_columns=analyte_cols,
            ignored_columns=[col_index(c) for c in d.get("ignored_columns", [])],
            rpd_layout=d.get("rpd_layout", {}),
            source_cell_tracking_enabled=d.get("source_cell_tracking_enabled", True),
        )
        return sp


@dataclass
class ParserProfile:
    profile_id: str
    data: dict
    sheets: Dict[str, SheetProfile]
    date_system: str = "1900"
    formula_handling: str = "use_cached_then_qa"
    path: Optional[Path] = None

    @classmethod
    def load(cls, path: Path) -> "ParserProfile":
        data = load_config(path)
        _require(data, ["profile_id", "sheets"], f"parser profile {path}")
        sheets = {}
        for sd in data["sheets"]:
            sp = SheetProfile.from_dict(sd)
            sheets[sp.sheet_name] = sp
        return cls(profile_id=data["profile_id"], data=data, sheets=sheets,
                   date_system=str(data.get("date_system", "1900")),
                   formula_handling=data.get("formula_handling",
                                             "use_cached_then_qa"),
                   path=Path(path))

    def sheets_of_type(self, data_type: str) -> List[SheetProfile]:
        return [s for s in self.sheets.values() if s.data_type == data_type]


# ---------------------------------------------------------------------------
# Analyte dictionary / screening levels
# ---------------------------------------------------------------------------

# Canonical nondetect-qualifier vocabulary, shared by every report-family
# module so a result that imports as nondetect (result_parser.py's
# QUALIFIER_FLAGS: "U"/"UJ") also reports as nondetect. "BDL" is kept for
# back-compat with lab data using that alias, even though result_parser.py
# doesn't parse it. See issue #340 -- this used to be copy-pasted into seven
# modules, none of which included "UJ".
ND_QUALIFIERS = frozenset({"ND", "U", "UJ", "BDL"})


def load_analyte_dictionary(path: Path) -> dict:
    data = load_config(path)
    analytes = data.get("analytes", data)
    for name, entry in analytes.items():
        if name.startswith("_"):
            continue
        if not isinstance(entry, dict):
            raise ConfigError(f"analyte dictionary entry '{name}' must be a mapping")
        entry.setdefault("canonical_name", name)
        entry.setdefault("aliases", [])
        entry.setdefault("abbreviation", name)
        entry.setdefault("display_order", 9999)
    return analytes


def load_screening_levels(path: Path) -> dict:
    """Returns {matrix: {canonical_analyte: {value, units, source}}}."""
    data = load_config(path)
    return data.get("screening_levels", data)


def screening_for(screening_levels: dict, matrix: str,
                  canonical: str) -> Optional[dict]:
    return (screening_levels.get(matrix, {}) or {}).get(canonical)


def load_flat_screening_levels(path: Path) -> Dict[str, float]:
    """Load a ``--screening-levels``/``--sl-path`` YAML for the matrix-agnostic
    report commands, which expect a flat ``{AnalyteName: value}`` mapping.

    Accepts two shapes:

    - Already flat: ``{AnalyteName: value}`` (legacy per-report files).
    - Matrix-nested (the shipped ``screening_levels.yaml`` shape,
      ``{matrix: {AnalyteName: {value, units, source}}}``): flattened across
      matrices, since these commands have no per-row Matrix to disambiguate.
      Raises ``ConfigError`` if the same analyte carries two different
      non-null values in different matrices -- there is no safe way to pick
      one, so this fails loudly instead of silently choosing the wrong one
      (issue #341).

    A file that *mixes* the two shapes is rejected with ``ConfigError``: the
    old "any value is a dict" test sent such a file down the nested branch,
    where every flat key was skipped and the result was silently ``{}`` --
    a screening surface with no levels reports no exceedances (issue #434).
    ``None`` values are ignored when classifying, so a blank level
    (``Benzene:``) and an empty matrix (``SO:``) stay legal in either shape.
    """
    raw = load_screening_levels(path)
    if not raw:
        return {}

    present = {k: v for k, v in raw.items() if v is not None}
    nested_keys = [k for k, v in present.items() if isinstance(v, dict)]
    if nested_keys and len(nested_keys) != len(present):
        flat_keys = [k for k in present if not isinstance(present[k], dict)]
        raise ConfigError(
            f"{path}: screening-levels file mixes matrix-nested entries "
            f"({', '.join(sorted(str(k) for k in nested_keys))}) with flat "
            f"entries ({', '.join(sorted(str(k) for k in flat_keys))}). "
            f"Use either {{matrix: {{AnalyteName: value}}}} or a flat "
            f"{{AnalyteName: value}} mapping, not both.")

    if not nested_keys:
        out = {}
        for k, v in raw.items():
            if v is None:
                continue
            try:
                out[str(k)] = float(v)
            except (TypeError, ValueError) as exc:
                raise ConfigError(
                    f"{path}: screening level for {k!r} is not a number "
                    f"({v!r}).") from exc
        return out

    flat: Dict[str, float] = {}
    sources: Dict[str, str] = {}
    for matrix, analytes in raw.items():
        if not isinstance(analytes, dict):
            continue
        for analyte, entry in analytes.items():
            value = entry.get("value") if isinstance(entry, dict) else entry
            if value is None:
                continue
            try:
                value = float(value)
            except (TypeError, ValueError) as exc:
                raise ConfigError(
                    f"{path}: screening level for {analyte!r} in matrix "
                    f"{matrix!r} is not a number ({value!r}).") from exc
            if analyte in flat and flat[analyte] != value:
                raise ConfigError(
                    f"{path}: analyte {analyte!r} has conflicting screening "
                    f"levels across matrices ({sources[analyte]}={flat[analyte]!r} "
                    f"vs {matrix}={value!r}); this command has no per-row "
                    f"Matrix to disambiguate -- provide a flat, single-matrix "
                    f"{{AnalyteName: value}} screening-levels file instead.")
            flat[analyte] = value
            sources[analyte] = matrix
    return flat


# ---------------------------------------------------------------------------
# Figure spec
# ---------------------------------------------------------------------------
FIGURE_REQUIRED = ["figure_spec_id", "map_type", "matrix", "layout_name",
                   "figure_title", "output_filename_pattern", "callout_template"]


@dataclass
class FigureSpec:
    data: dict
    path: Optional[Path] = None

    @classmethod
    def load(cls, path: Path) -> "FigureSpec":
        data = load_config(path)
        _require(data, FIGURE_REQUIRED, f"figure spec {path}")
        return cls(data=data, path=Path(path))

    def __getattr__(self, item):
        try:
            return self.data[item]
        except KeyError as exc:
            raise AttributeError(item) from exc

    def get(self, key, default=None):
        return self.data.get(key, default)

    def analyte_list(self, analyte_dictionary: dict,
                     analyte_set_name: Optional[str] = None,
                     custom_list: Optional[List[str]] = None) -> List[str]:
        """Resolve the ordered canonical analyte list for this figure."""
        if custom_list:
            names = custom_list
        else:
            sets = self.data.get("analyte_sets", {})
            set_name = analyte_set_name or self.data.get("default_analyte_set")
            if set_name and set_name in sets:
                names = sets[set_name]
            else:
                names = self.data.get("analytes", [])
        if not names:
            raise ConfigError(f"figure spec {self.data.get('figure_spec_id')}: "
                              f"no analyte set resolved")
        ordered = sorted(
            names,
            key=lambda n: analyte_dictionary.get(n, {}).get("display_order", 9999))
        return ordered


# ---------------------------------------------------------------------------
# Harvest configuration (field-typed; canonical home — deltas H1/C5)
# ---------------------------------------------------------------------------
VALID_STATUSES = ("downloaded", "skipped", "failed")


@dataclass
class HarvestConfig:
    """Attachment-harvest job config.

    The ``url``-XOR-``item_id`` invariant is validated at construction in
    ``.load`` (the single validation source per MERGE_PLAN §2). Direct
    construction stays permissive so ``layer_ref()`` can raise lazily — this
    preserves the harness's existing semantics/tests.
    """
    directory: str
    group_template: str
    filename_template: str
    item_id: str | None = None
    url: str | None = None
    # Index into the item's COMBINED layers+tables list (layers first, then
    # tables) — the same continuous numbering AGOL uses for the portal
    # ``?sublayer=N`` URL parameter and REST service sublayer ids. It is NOT
    # an index into the arcgis Python API's separate ``.layers[]`` /
    # ``.tables[]`` arrays. Only used with ``item_id``; ignored for ``url``.
    layer_index: int = 0
    # Harvest every attachment-bearing layer AND table of the item in one
    # run (each under its own sanitized-name subfolder). Requires ``item_id``;
    # mutually exclusive with ``layer_index`` and ``incremental`` — see
    # ``.load``.
    all_sublayers: bool = False
    where: str = "1=1"
    incremental: bool = False
    skip_existing: bool = True
    retries: int = 3
    backoff_seconds: float = 2

    def layer_ref(self) -> str:
        if self.url:
            return self.url
        if self.item_id:
            return self.item_id
        raise ValueError("HarvestConfig requires either url or item_id")

    @classmethod
    def load(cls, path: Path) -> "HarvestConfig":
        """Load a harvest job config from nested YAML/JSON.

        Flattens the ``connection``/``layer``/``output``/``options`` sections
        into the field-typed dataclass and validates the url-XOR-item_id
        invariant on the dataclass. Returns ONLY the config — ``connection.
        profile`` is a session concern owned by ``runtime/sessions.py`` and the
        CLI override whitelist is an adapter concern (deltas H1).
        """
        data = load_config(path)
        layer = data.get("layer") or {}
        output = data.get("output") or {}
        options = data.get("options") or {}

        _require(output, ["directory", "group_template", "filename_template"],
                 f"harvest config {path} output")

        item_id = layer.get("item_id")
        url = layer.get("url")
        if bool(item_id) == bool(url):
            raise ConfigError(
                f"harvest config {path}: layer must set exactly one of "
                f"'url' or 'item_id'")

        all_sublayers = bool(layer.get("all_sublayers", False))
        if all_sublayers:
            if url:
                raise ConfigError(
                    f"harvest config {path}: all_sublayers requires item_id, "
                    f"not url (a url targets exactly one layer/table)")
            # layer_index defaults to 0 even when absent, so check the RAW
            # YAML dict for an explicit key — the two selections are
            # mutually exclusive.
            if "layer_index" in layer:
                raise ConfigError(
                    f"harvest config {path}: all_sublayers and layer_index "
                    f"are mutually exclusive — pick one")
            if options.get("incremental", False):
                raise ConfigError(
                    f"harvest config {path}: all_sublayers cannot be "
                    f"combined with incremental — last-run state is kept "
                    f"per output directory, so one shared directory would "
                    f"conflate 'last run' across unrelated sublayers")

        where = layer.get("where")
        return cls(
            directory=output["directory"],
            group_template=output["group_template"],
            filename_template=output["filename_template"],
            item_id=item_id,
            url=url,
            # layer_index counts across layers-then-tables combined (AGOL
            # ?sublayer=N numbering), not the API's separate arrays — see the
            # field comment on the dataclass.
            layer_index=layer.get("layer_index", 0),
            all_sublayers=all_sublayers,
            where=where if where is not None else "1=1",
            incremental=options.get("incremental", False),
            skip_existing=options.get("skip_existing", True),
            retries=options.get("retries", 3),
            backoff_seconds=options.get("backoff_seconds", 2),
        )
