"""sticklog.py — GenerateBoringSticklogs (headless).

Renders a 2D sticklog per boring from the 8.0a boring-log SQLite database:
one depth-indexed lithology column (feet below ground surface) with
USCS-derived hatch patterns and in-band USCS labels, a sample-interval lane,
an optional well-construction column, interval descriptions with PID
alongside, and the first groundwater observation as a water-level marker.
Reuses the 8.0a read side
(:func:`autogis.core.envmon.boring_log_report.read_boring_records`) — no
parallel DB reader.

Rendering (matplotlib) is lazy-imported and optional (``pip install
"autogis[profile]"`` — same extra as the subsurface profile); everything
else here is arcpy-free and matplotlib-free.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..common.qa import QACollector, SEV_WARNING
from .boring_log_report import (
    _unique_safe_name, _with_depths, read_boring_records,
)

_MATPLOTLIB_HINT = ('matplotlib is required to render sticklogs. '
                    'Install with: pip install "autogis[profile]"')

#: Same neutral lithology fill as render_profile — identity is carried by the
#: USCS text label; the hatch adds a redundant texture cue (print/CVD-safe).
_LITHOLOGY_FILL = "#d9c9a3"

#: matplotlib hatch per USCS primary letter: Gravel, Sand, silt (M), Clay,
#: Organic, Peat. Dual symbols (SP-SM) key off the primary fraction.
# ponytail: first-letter heuristic, not the full USCS graphic standard —
# swap for per-symbol patterns if a deliverable requires the ASTM fills.
_USCS_HATCHES = {"G": "oo", "S": "..", "M": "||", "C": "//",
                 "O": "--", "P": "--"}

#: File formats the CLI may request (matplotlib infers from the extension).
STICKLOG_FORMATS = ("png", "svg")


def uscs_hatch(uscs: Optional[str]) -> str:
    """Hatch pattern for a USCS symbol ('' when unknown/blank)."""
    return _USCS_HATCHES.get((uscs or "")[:1].upper(), "")


def _depth_extent(lithology: list, samples: list, construction: list,
                  dtw: Optional[float], total_depth_ft) -> float:
    """Deepest drawable depth — every rendered overlay counts, not just
    lithology, so a sample or screen below the lithology column is never
    clipped by the y-limit."""
    return max(
        [iv["bottom_depth"] for iv in lithology]
        + [s["bottom_depth"] for s in samples]
        + [c["bottom_depth"] for c in construction]
        + ([dtw] if dtw is not None else [])
        + ([total_depth_ft] if total_depth_ft else []))


def _first_water_depth(groundwater: list) -> Optional[float]:
    """First recorded depth-to-water, in observation order (rows with no
    depth are skipped)."""
    for g in groundwater:
        if g.get("depth_to_water") is not None:
            return g["depth_to_water"]
    return None


def _interval_label(iv: dict) -> str:
    """'material, description — PID n ppm' from whichever fields are set."""
    label = ", ".join(s for s in (iv.get("primary_material"),
                                  iv.get("description")) if s)
    if iv.get("pid_ppm") is not None:
        pid = f"PID {iv['pid_ppm']} ppm"
        label = f"{label} — {pid}" if label else pid
    return label


def render_sticklog(
    boring_id: str,
    bundle: dict,
    out_path: Path,
    *,
    qa: Optional[QACollector] = None,
) -> Optional[Path]:
    """Render one boring's 2D sticklog to *out_path* (format from extension).

    *bundle* is a ``read_boring_records`` value. A boring with no lithology
    intervals has nothing to draw — it is skipped with a QA warning and
    ``None`` is returned rather than an empty figure.

    Layout, left to right: sample brackets, the hatched lithology column,
    the well-construction column (only when construction rows exist), then
    interval descriptions/PID and the water-level marker.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
    except ImportError as exc:
        raise ImportError(_MATPLOTLIB_HINT) from exc

    lithology = _with_depths(
        bundle.get("lithology", []), boring_id, "lithology", qa,
        warning_prefix="sticklog")
    if not lithology:
        if qa is not None:
            qa.add(SEV_WARNING, "sticklog_no_lithology",
                   f"Boring {boring_id} has no lithology intervals; "
                   f"sticklog skipped.")
        return None

    loc = bundle.get("location", {})
    samples = _with_depths(
        bundle.get("samples", []), boring_id, "sample", qa,
        warning_prefix="sticklog")
    construction = _with_depths(
        bundle.get("construction", []), boring_id, "construction", qa,
        warning_prefix="sticklog")
    dtw = _first_water_depth(bundle.get("groundwater", []))
    depth_max = _depth_extent(lithology, samples, construction, dtw,
                              loc.get("total_depth_ft"))
    text_x = 1.55 if construction else 1.15  # text shifts right of well column

    fig, ax = plt.subplots(figsize=(4.5, max(6.0, depth_max * 0.12)))
    for iv in lithology:
        top, bottom = iv["top_depth"], iv["bottom_depth"]
        ax.add_patch(Rectangle((0.0, top), 1.0, bottom - top,
                               edgecolor="black", facecolor=_LITHOLOGY_FILL,
                               hatch=uscs_hatch(iv.get("uscs")),
                               linewidth=0.5))
        mid = (top + bottom) / 2
        if iv.get("uscs"):
            ax.text(0.5, mid, iv["uscs"], ha="center", va="center",
                    fontsize=7, fontweight="bold",
                    bbox={"facecolor": "white", "edgecolor": "none",
                          "pad": 1.0})
        label = _interval_label(iv)
        if label:
            ax.text(text_x, mid, label, ha="left", va="center", fontsize=6.5)

    # sample brackets in a lane left of the column
    for s in samples:
        top, bottom, x = s["top_depth"], s["bottom_depth"], -0.2
        ax.plot([x, x], [top, bottom], color="black", linewidth=1.2)
        for depth in (top, bottom):
            ax.plot([x, x + 0.06], [depth, depth], color="black",
                    linewidth=1.2)
        if s.get("sample_id"):
            # rotated so long IDs don't run into the y-axis tick labels
            ax.text(x - 0.08, (top + bottom) / 2, s["sample_id"],
                    ha="center", va="center", fontsize=5.5, rotation=90)

    # well-construction column right of the lithology column
    for c in construction:
        top, bottom = c["top_depth"], c["bottom_depth"]
        is_screen = "screen" in (c.get("component_type") or "").lower()
        ax.add_patch(Rectangle((1.08, top), 0.35, bottom - top,
                               edgecolor="black", facecolor="white",
                               hatch="---" if is_screen else "",
                               linewidth=0.5))
        if c.get("component_type") and bottom - top > depth_max * 0.04:
            ax.text(1.255, (top + bottom) / 2, c["component_type"],
                    ha="center", va="center", fontsize=5.5, rotation=90,
                    bbox={"facecolor": "white", "edgecolor": "none",
                          "pad": 1.0})

    if dtw is not None:
        ax.axhline(dtw, color="#2b6cb0", linestyle="--", linewidth=0.8)
        ax.plot(-0.5, dtw, marker="v", color="#2b6cb0", clip_on=False)
        ax.text(text_x, dtw, f"DTW {dtw} ft", ha="left", va="bottom",
                fontsize=6.5, color="#2b6cb0")

    ax.set_xlim(-0.55, 4.3)
    # depth increases downward; pad below so the deepest interval's closing
    # edge isn't clipped by the axis limit
    ax.set_ylim(depth_max + max(1.0, depth_max * 0.02), 0)
    ax.set_xticks([])
    ax.set_ylabel("Depth (ft bgs)")
    site = loc.get("site_id") or ""
    ax.set_title(f"{boring_id}" + (f" — {site}" if site else ""), fontsize=10)
    ax.grid(True, axis="y", linestyle=":", linewidth=0.5)
    for spine in ("top", "right", "bottom"):
        ax.spines[spine].set_visible(False)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return out_path


def generate_sticklogs(
    db_path: Path,
    out_dir: Path,
    *,
    boring_ids: Optional[list] = None,
    fmt: str = "png",
    qa: Optional[QACollector] = None,
) -> list:
    """Read the boring DB and render one ``sticklog_<id>.<fmt>`` per boring
    into *out_dir* (*fmt*: one of ``STICKLOG_FORMATS``). Returns the paths
    written (lithology-less borings are QA-warned and skipped by
    :func:`render_sticklog`)."""
    if fmt not in STICKLOG_FORMATS:
        raise ValueError(f"fmt must be one of {STICKLOG_FORMATS}, got {fmt!r}")
    bundles = read_boring_records(Path(db_path), boring_ids=boring_ids, qa=qa)
    out = Path(out_dir)
    paths = []
    taken: set = set()
    for boring_id, bundle in bundles.items():
        final, collided = _unique_safe_name(boring_id, taken)
        if collided and qa is not None:
            qa.add(SEV_WARNING, "sticklog_filename_collision",
                   f"Boring {boring_id!r} sanitizes to the same filename as "
                   f"an earlier boring; writing sticklog_{final}.{fmt} "
                   f"instead.")
        p = render_sticklog(boring_id, bundle,
                            out / f"sticklog_{final}.{fmt}", qa=qa)
        if p is not None:
            paths.append(p)
    return paths
