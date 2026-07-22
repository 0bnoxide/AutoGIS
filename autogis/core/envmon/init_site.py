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

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from ..common.config import ConfigError, FigureSpec, ParserProfile, SiteConfig

_TEMPLATE_DIR = (Path(__file__).resolve().parents[2]
                 / "config" / "_templates" / "site_skeleton")


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
    return text.replace("__SITE_ID__", site_id).replace("__SITE_NAME__", site_name)


def plan_site_skeleton(site_id: str, site_name: str,
                       dest: Path) -> List[SkeletonFile]:
    """Render every family template to a target path. No writes — drives both
    the real and ``--dry-run`` paths."""
    dest = Path(dest)
    files: List[SkeletonFile] = []
    for fam in FAMILIES:
        raw = (_TEMPLATE_DIR / fam.template).read_text(encoding="utf-8")
        text = _render(raw, site_id, site_name)
        name = _render(fam.dest_name, site_id, site_name)
        files.append(SkeletonFile(fam.name, dest / fam.dest_subdir / name, text))
    return files


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
        except ConfigError as exc:
            results.append((sf.family, False, str(exc)))
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
        if sf.target.exists() and not force:
            blocked.append(sf.target)
            continue
        sf.target.parent.mkdir(parents=True, exist_ok=True)
        sf.target.write_text(sf.text, encoding="utf-8")
        written.append(sf.target)
    return written, blocked
