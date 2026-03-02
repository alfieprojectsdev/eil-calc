import rasterio.mask
import numpy as np
from shapely.geometry.base import BaseGeometry

from eil_types import DEMContext, SlopeAssessment, SlopeMetrics, SlopeResult


def compute_slope_stability(geometry: BaseGeometry, dataset) -> SlopeResult | dict:
    """Compute slope stability from an open rasterio dataset.

    Args:
        geometry: Parcel polygon already in dataset CRS.
        dataset:  Open rasterio dataset.

    Returns:
        SlopeResult dict or {"error": ...} on failure.
    """
    out_image, _ = rasterio.mask.mask(dataset, [geometry], crop=True)
    elevation_data = out_image[0]

    valid_mask = elevation_data != dataset.nodata
    if valid_mask.sum() == 0:
        return {"error": "No valid data in parcel"}

    px, py = dataset.res
    dz_dy, dz_dx = np.gradient(elevation_data, py, px)
    slope_degrees = np.degrees(np.arctan(np.sqrt(dz_dx**2 + dz_dy**2)))
    site_slopes = slope_degrees[valid_mask]

    if site_slopes.size == 0:
        return {"error": "No valid slope data"}

    max_slope = float(np.max(site_slopes))
    avg_slope = float(np.mean(site_slopes))

    if max_slope > 16.0:
        status = "SUSCEPTIBLE"
    elif max_slope > 14.0:
        status = "FLAG FOR REVIEW"
    else:
        status = "SAFE"

    return SlopeResult(
        metrics=SlopeMetrics(max_slope_degrees=max_slope, avg_slope_degrees=avg_slope),
        assessment=SlopeAssessment(status=status, threshold_used="max_slope"),
    )


def calculate_slope_stability(context: DEMContext) -> SlopeResult | dict:
    """Entry point accepting a DEMContext (geometry already projected)."""
    return compute_slope_stability(context.geometry, context.dataset)
