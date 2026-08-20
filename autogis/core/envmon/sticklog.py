"""sticklog.py — GenerateBoringSticklogs (headless).

Renders a 2D sticklog per boring from the 8.0a boring-log SQLite database:
one depth-indexed lithology column (feet below ground surface), USCS labels
in-band, interval descriptions alongside, and the first groundwater
observation as a water-level marker. Reuses the 8.0a read side
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
from .boring_log_report import _safe_name, read_boring_records

_MATPLOTLIB_HINT = ('matplotlib is required to render sticklogs. '
                    'Install with: pip install "autogis[profile]"')

#: Same neutral lithology fill as render_profile — identity is carried by the
#: USCS text label, not a color series.
_LITHOLOGY_FILL = "#d9c9a3"


def _first_water_depth(groundwater: list) -> Optional[float]:
    """First recorded depth-to-water, in observation order (rows with no
    depth are skipped)."""
    for g in groundwater:
        if g.get("depth_to_water") is not None:
            return g["depth_to_water"]
    return None


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
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
    except ImportError as exc:
        raise ImportError(_MATPLOTLIB_HINT) from exc

    lithology = sorted(bundle.get("lithology", []),
                       key=lambda iv: iv["top_depth"])
    if not lithology:
        if qa is not None:
            qa.add(SEV_WARNING, "sticklog_no_lithology",
                   f"Boring {boring_id} has no lithology intervals; "
                   f"sticklog skipped.")
        return None

    loc = bundle.get("location", {})
    depth_max = max(max(iv["bottom_depth"] for iv in lithology),
                    loc.get("total_depth_ft") or 0.0)

    fig, ax = plt.subplots(figsize=(4.5, max(6.0, depth_max * 0.12)))
    for iv in lithology:
        top, bottom = iv["top_depth"], iv["bottom_depth"]
        ax.add_patch(Rectangle((0.0, top), 1.0, bottom - top,
                               edgecolor="black", facecolor=_LITHOLOGY_FILL,
                               linewidth=0.5))
        mid = (top + bottom) / 2
        if iv.get("uscs"):
            ax.text(0.5, mid, iv["uscs"], ha="center", va="center",
                    fontsize=7, fontweight="bold")
        label = ", ".join(s for s in (iv.get("primary_material"),
                                      iv.get("description")) if s)
        if label:
            ax.text(1.15, mid, label, ha="left", va="center", fontsize=6.5)

    dtw = _first_water_depth(bundle.get("groundwater", []))
    if dtw is not None:
        ax.axhline(dtw, color="#2b6cb0", linestyle="--", linewidth=0.8)
        ax.plot(-0.12, dtw, marker="v", color="#2b6cb0", clip_on=False)
        ax.text(1.15, dtw, f"DTW {dtw} ft", ha="left", va="bottom",
                fontsize=6.5, color="#2b6cb0")

    ax.set_xlim(-0.25, 4.0)
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
    qa: Optional[QACollector] = None,
) -> list:
    """Read the boring DB and render one ``sticklog_<id>.png`` per boring
    into *out_dir*. Returns the paths written (lithology-less borings are
    QA-warned and skipped by :func:`render_sticklog`)."""
    bundles = read_boring_records(Path(db_path), boring_ids=boring_ids, qa=qa)
    out = Path(out_dir)
    paths = []
    for boring_id, bundle in bundles.items():
        p = render_sticklog(boring_id, bundle,
                            out / f"sticklog_{_safe_name(boring_id)}.png",
                            qa=qa)
        if p is not None:
            paths.append(p)
    return paths
