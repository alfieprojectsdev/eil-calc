from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, TypedDict

import rasterio
from shapely.geometry.base import BaseGeometry


# ---------------------------------------------------------------------------
# Output contracts
# ---------------------------------------------------------------------------

class SlopeMetrics(TypedDict):
    max_slope_degrees: float
    avg_slope_degrees: float


class SlopeAssessment(TypedDict):
    status: str   # "SAFE" | "FLAG FOR REVIEW" | "SUSCEPTIBLE"
    threshold_used: str


class SlopeResult(TypedDict):
    metrics: SlopeMetrics
    assessment: SlopeAssessment


class DepositionalMetrics(TypedDict):
    elevation_peak: float
    elevation_site: float
    delta_e: float
    horizontal_distance_h: float
    required_runout_3x: float


class DepositionalAssessment(TypedDict):
    status: str   # "SAFE (Beyond Runout)" | "PRONE (Within Runout Zone)"
    is_compliant: bool


class DepositionalResult(TypedDict):
    metrics: DepositionalMetrics
    assessment: DepositionalAssessment


# ---------------------------------------------------------------------------
# DEM context
# ---------------------------------------------------------------------------

@dataclass
class DEMContext:
    """Holds an open DEM dataset and the projected parcel geometry.

    Constructed once by the orchestrator so all modules share the same
    open file handle and pre-reprojected geometry.  The landlab_grid
    field is a placeholder for Phase 2 (Landlab + XGBoost).
    """

    dataset: rasterio.io.DatasetReader
    geometry: BaseGeometry        # already reprojected to dataset.crs
    source_type: str              # 'ifsar' | 'srtm' | 'local_override'
    landlab_grid: Optional[object] = field(default=None)
