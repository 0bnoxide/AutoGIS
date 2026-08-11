"""Site onboarding bootstrap — scaffold a new site's config skeleton.

Headless and arcpy-free (Tool-1 class). Renders the four config-family
templates with the site identity substituted, guards against overwriting
existing files, surfaces every ``_TODO`` anchor an operator must complete, and
runs the existing config loaders as structural validators.

Substitution uses two sentinel tokens, ``__SITE_ID__`` and ``__SITE_NAME__``.
Sentinels (not ``{site_id}``) are required because figure specs and parser
profiles legitimately carry ``{site_id}`` / ``{figure_spec_id}`` as *runtime*
placeholders that the figure engine resolves per invocation — init-site must
leave those intact. See docs/superpowers/specs/2026-07-22-site-onboarding-
bootstrap-design.md.
"""
from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Callable, List, Optional, Tuple

_SENTINELS = ("__SITE_ID__", "__SITE_NAME__")
_SENTINEL_RE = re.compile("|".join(_SENTINELS))

from ..common.config import FigureSpec, ParserProfile, SiteConfig

# Templates ship as package data of the `autogis` package (see
# pyproject [tool.setuptools.package-data]); load them via importlib.resources
# so a wheel install works the same as an editable checkout -- Path(__file__)
# traversal to ../../config would only find them on-disk in a source tree.
_TEMPLATE_PARTS = ("config", "_templates", "site_skeleton")


def _read_template(name: str) -> str:
    return (files("autogis").joinpath(*_TEMPLATE_PARTS, name)
            .read_text(encoding="utf-8"))


# These guards live in core so EVERY caller (CLI and any library caller of
# plan_site_skeleton) is protected -- not just the CLI callbacks. They raise
# ValueError; the CLI callbacks translate that to click.BadParameter.
def check_site_id(site_id: str) -> None:
    """site_id flows into filenames under --dest: letters/digits/'-'/'_' only,
    to block '../' traversal and path separators. Raises ValueError."""
    if not site_id.replace("-", "").replace("_", "").isalnum():
        raise ValueError("site id must be letters/digits with '-' or '_' only "
                         "(no path separators or dots)")
    if any(tok in site_id for tok in _SENTINELS):
        # e.g. site_id="__SITE_NAME__" passes the alnum test but would collide
        # with substitution; forbid the sentinels outright.
        raise ValueError("site id must not contain the substitution tokens "
                         "__SITE_ID__ / __SITE_NAME__")


def check_site_name(site_name: str) -> None:
    """site_name lands in double-quoted YAML scalars: reject the scalar
    metacharacters ('"', '\\') and any non-printable (control/DEL/C1/line &
    paragraph separators, via str.isprintable()). Raises ValueError."""
    _check_yaml_scalar(site_name, "site name")


def _check_yaml_scalar(value: str, field: str) -> None:
    """Shared guard for any operator string landing in a double-quoted YAML
    scalar. ``field`` names the offending input, so the message is right
    whichever caller rejected it."""
    if '"' in value or "\\" in value or not value.isprintable():
        raise ValueError(f"{field} must be printable text without "
                         "double-quotes or backslashes")
    if any(tok in value for tok in _SENTINELS):
        raise ValueError(f"{field} must not contain the substitution tokens "
                         "__SITE_ID__ / __SITE_NAME__")


def _validate_event(path: Path) -> None:
    # load_event_config is the event family's existing validator; it wraps
    # load_config (checks a top-level mapping). Imported lazily to keep this
    # module's import graph minimal.
    from .create_sampling_event import load_event_config
    load_event_config(path)


@dataclass(frozen=True)
class _Family:
    """A config family init-site scaffolds: which template, where it lands, and
    which existing loader validates the generated file."""
    name: str
    template: str          # filename under _TEMPLATE_DIR
    dest_subdir: str       # subdir under the config root
    dest_name: str         # output filename (may contain __SITE_ID__)
    validate: Callable[[Path], None]


# One entry per config family (design scope: all four).
FAMILIES: Tuple[_Family, ...] = (
    _Family("site", "site.yaml", "sites",
            "__SITE_ID__.yaml", lambda p: SiteConfig.load(p)),
    _Family("event", "event_config.yaml", "event_configs",
            "__SITE_ID___event_config.yaml", _validate_event),
    _Family("parser", "parser_profile.yaml", "parser_profiles",
            "__SITE_ID___DataTables.yaml", lambda p: ParserProfile.load(p)),
    _Family("figure", "figure_spec.yaml", "figure_specs",
            "__SITE_ID___GW_Analytical.yaml", lambda p: FigureSpec.load(p)),
)


@dataclass(frozen=True)
class SkeletonFile:
    family: str
    target: Path
    text: str


def _render(text: str, site_id: str, site_name: str) -> str:
    # Single pass: each sentinel in the TEMPLATE is replaced exactly once and
    # substituted values are never re-scanned. Chained str.replace() would let a
    # value that itself contains the other sentinel (e.g. site_id="__SITE_NAME__")
    # be re-substituted -- an injection the guards also reject, but this makes
    # the render correct by construction.
    repl = {"__SITE_ID__": site_id, "__SITE_NAME__": site_name}
    return _SENTINEL_RE.sub(lambda m: repl[m.group(0)], text)


_TEMPLATE_ID_RE = re.compile(r"^(\s*template_id:).*$", re.MULTILINE)


def check_callout_template_id(value: str) -> None:
    """The callout template id lands in a double-quoted YAML scalar, same
    trust boundary as ``site_name``. Raises ValueError."""
    _check_yaml_scalar(value, "callout template id")


def render_figure_spec_template(site_id: str = "_TODO_SITE_ID",
                                site_name: str = "_TODO Site Name",
                                callout_template_id: str = "") -> str:
    """Render the shipped figure-spec skeleton, optionally pinning the callout
    template id.

    Exists so there is exactly ONE figure-spec skeleton. ``init-site`` (CLI)
    and ``LoadFigureSpec`` (.pyt) both render this file. The .pyt previously
    carried a second, hardcoded copy that had drifted from it: that copy
    omitted ``figure_title`` (a FIGURE_REQUIRED key) and offered
    ``analyte_set_name``, which is the name of a Python parameter on
    ``analyte_list()``, not a config key. So everything the tool wrote was
    rejected by ``FigureSpec.load`` while the tool reported "Template
    written" — the operator only found out one tool later (#461).

    Raises ValueError on an unsafe identity, same as ``plan_site_skeleton``.
    """
    check_site_id(site_id)
    check_site_name(site_name)
    text = _render(_read_template("figure_spec.yaml"), site_id, site_name)
    if callout_template_id:
        check_callout_template_id(callout_template_id)
        # Quoted, like the template's own site_id: an unquoted scalar makes
        # YAML read "NO"/"on"/"123" as bool/int rather than the id the operator
        # picked, and a value carrying a newline would inject a sibling key
        # into callout_template.
        # No count= : subn must report EXACTLY one match. With count=1 it
        # returns 1 on the first hit however many exist, so a second
        # template_id: block added above this one would be silently missed.
        text, n = _TEMPLATE_ID_RE.subn(
            lambda m: f'{m.group(1)} "{callout_template_id}"', text)
        if n != 1:
            raise ValueError(
                f"figure-spec template has {n} template_id: lines, expected 1")
    return text


def plan_site_skeleton(site_id: str, site_name: str,
                       dest: Path) -> List[SkeletonFile]:
    """Render every family template to a target path. No writes — drives both
    the real and ``--dry-run`` paths. Raises ValueError on unsafe identity."""
    check_site_id(site_id)
    check_site_name(site_name)
    dest = Path(dest)
    planned: List[SkeletonFile] = []
    for fam in FAMILIES:
        raw = _read_template(fam.template)
        text = _render(raw, site_id, site_name)
        name = _render(fam.dest_name, site_id, site_name)
        planned.append(SkeletonFile(fam.name, dest / fam.dest_subdir / name, text))
    return planned


# Regulatory content init-site deliberately does NOT scaffold: screening files
# are passed explicitly to the tools (no per-site convention exists), so a new
# site has none. Surfaced by the command so an operator configures it before
# production rather than shipping figures with no exceedance criteria.
REGULATORY_TODO: Tuple[str, ...] = (
    "screening levels: author a screening-levels YAML covering this site's "
    "analytes (cite the governing regulatory table in each entry's `source`) "
    "and validate it with `envmon manage-screening-levels`. The importer's "
    "primary source is the workbook RBSL row; this file is the secondary "
    "fallback. A result with NO screening level is left unevaluated — figures "
    "render it as detected, never as an exceedance, and only the importer logs "
    "a QA warning — so without screening levels, exceedances silently never "
    "appear on figures.",
)


def regulatory_gaps() -> List[str]:
    """Regulatory content a freshly scaffolded site still needs but that
    init-site does not create. A function (not just the constant) so a later
    slice can make it dest-aware without changing callers."""
    return list(REGULATORY_TODO)


def scan_anchors(text: str) -> List[Tuple[int, str]]:
    """Return (line_no, stripped_line) for every ``_TODO`` anchor in *text*."""
    return [(i, line.strip())
            for i, line in enumerate(text.splitlines(), 1)
            if "_TODO" in line]


def validate_skeleton(files: List[SkeletonFile]) -> List[Tuple[str, bool, str]]:
    """Run each family's existing loader against its rendered text (via a temp
    file, so this works for --dry-run too). Returns (family, ok, message)."""
    validators = {f.name: f.validate for f in FAMILIES}
    results: List[Tuple[str, bool, str]] = []
    for sf in files:
        try:
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td) / sf.target.name
                tmp.write_text(sf.text, encoding="utf-8")
                validators[sf.family](tmp)
            results.append((sf.family, True, ""))
        except Exception as exc:  # noqa: BLE001 - a report tool must degrade to
            # a FAIL line, never crash: ConfigError from the loader, but also a
            # yaml.YAMLError (load_config doesn't wrap safe_load) from a template
            # that renders to invalid YAML.
            results.append((sf.family, False, f"{type(exc).__name__}: {exc}"))
    return results


def write_skeleton(files: List[SkeletonFile], *, force: bool
                   ) -> Tuple[List[Path], List[Path]]:
    """Write each file. Existing targets are NOT overwritten unless *force*.

    Returns (written, blocked) — blocked = pre-existing targets left untouched.
    The overwrite guard is the data-loss boundary and is never bypassed without
    an explicit --force.
    """
    written: List[Path] = []
    blocked: List[Path] = []
    for sf in files:
        sf.target.parent.mkdir(parents=True, exist_ok=True)
        try:
            # "x" = exclusive create: atomically raises FileExistsError if the
            # target already exists, closing the check-then-write race so two
            # concurrent runs can't both slip past the no-force guard.
            with open(sf.target, "w" if force else "x", encoding="utf-8") as fh:
                fh.write(sf.text)
        except FileExistsError:
            blocked.append(sf.target)
            continue
        written.append(sf.target)
    return written, blocked
