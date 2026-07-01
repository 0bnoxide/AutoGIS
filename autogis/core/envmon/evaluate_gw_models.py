"""Cross-validate groundwater interpolation model predictions (headless).

Compares observed GW elevations at control/withheld wells against one or more
model-predicted values (e.g. TIN, IDW, EBK columns from a groundwater surface
model run) and ranks models by RMSE. Pure stdlib (``csv`` + ``math``) — this
tool consumes prediction values already computed elsewhere; it does not
interpolate rasters itself, so it has no arcpy/scipy/kriging dependency.
"""
from __future__ import annotations

import csv
import dataclasses
import math
from pathlib import Path
from typing import Dict, List

from autogis.core.common.qa import QACollector, SEV_ERROR, SEV_INFO, SEV_WARNING


@dataclasses.dataclass
class ObservationRow:
    """One control well: observed elevation plus each model's prediction."""
    well_id: str
    observed_ft: float
    predictions: Dict[str, float]


@dataclasses.dataclass
class ModelStats:
    """Cross-validation stats for one interpolation model."""
    model_name: str
    n_points: int
    rmse: float
    mean_error: float             # signed bias: mean(predicted - observed)
    mae: float                    # mean(abs(predicted - observed))
    pct_within_tolerance: float
    rank: int                     # 1 = best fit (lowest RMSE)


def read_gw_model_csv(path: Path) -> List[ObservationRow]:
    """Read a wide CSV: well_id, observed_ft, then one column per model.

    Any column other than well_id/observed_ft is treated as a model's
    predicted elevation for that well. A blank cell means that model has no
    prediction for that well (skipped from that model's stats, not an error).
    """
    rows: List[ObservationRow] = []
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        model_names = [f for f in (reader.fieldnames or [])
                       if f not in ("well_id", "observed_ft")]
        for row in reader:
            predictions = {}
            for model in model_names:
                raw = (row.get(model) or "").strip()
                if raw:
                    predictions[model] = float(raw)
            rows.append(ObservationRow(
                well_id=row["well_id"],
                observed_ft=float(row["observed_ft"]),
                predictions=predictions,
            ))
    return rows


def evaluate_gw_models(
    observations: List[ObservationRow],
    *,
    tolerance_ft: float = 0.5,
    qa: QACollector,
) -> List[ModelStats]:
    """Cross-validate each model's predictions against observed values.

    Args:
        observations: List of ObservationRow from read_gw_model_csv().
        tolerance_ft: Absolute error threshold for the "percent within
            tolerance" stat.
        qa: QACollector for status messages.

    Returns:
        One ModelStats per model that has at least one prediction, ranked
        1..N by ascending RMSE (rank 1 = best fit).
    """
    if not observations:
        qa.add(SEV_ERROR, "no_observations", "No observation records provided.")
        return []

    model_names: List[str] = []
    for obs in observations:
        for name in obs.predictions:
            if name not in model_names:
                model_names.append(name)

    if not model_names:
        qa.add(SEV_ERROR, "no_model_predictions",
               "No model prediction columns found in the observations.")
        return []

    stats: List[ModelStats] = []
    for model in model_names:
        errors = [obs.predictions[model] - obs.observed_ft
                  for obs in observations if model in obs.predictions]

        if not errors:
            qa.add(SEV_WARNING, "model_has_no_predictions",
                   f"Model {model!r} has no predictions across any well.")
            continue

        n = len(errors)
        rmse = math.sqrt(sum(e ** 2 for e in errors) / n)
        mean_error = sum(errors) / n
        mae = sum(abs(e) for e in errors) / n
        n_within = sum(1 for e in errors if abs(e) <= tolerance_ft)

        stats.append(ModelStats(
            model_name=model, n_points=n, rmse=rmse, mean_error=mean_error,
            mae=mae, pct_within_tolerance=100.0 * n_within / n, rank=0,
        ))

    stats.sort(key=lambda s: s.rmse)
    for i, s in enumerate(stats, start=1):
        s.rank = i

    if stats:
        best = stats[0]
        qa.add(SEV_INFO, "evaluate_gw_models_complete",
               f"{len(stats)} model(s) evaluated — best fit: {best.model_name!r} "
               f"(RMSE={best.rmse:.4f} ft)")
    return stats


def write_model_stats_csv(stats: List[ModelStats], output_path: Path) -> None:
    """Write one row per model, ranked, to CSV."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [f.name for f in dataclasses.fields(ModelStats)]
    with open(output_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for s in stats:
            writer.writerow(dataclasses.asdict(s))
