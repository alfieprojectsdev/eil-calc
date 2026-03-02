import rasterio
import rasterio.mask
import numpy as np
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

from eil_types import (
    DEMContext,
    DepositionalAssessment,
    DepositionalMetrics,
    DepositionalResult,
)


def compute_depositional_safety(
    geometry: BaseGeometry,
    dataset,
    search_buffer_meters: int = 1000,
) -> DepositionalResult | dict:
    """Compute depositional zone safety from an open rasterio dataset.

    Pure computation — geometry must already be in the dataset CRS.
    No CRS reprojection is performed here; that responsibility belongs
    to the orchestrator.

    Args:
        geometry:              Parcel polygon already in dataset CRS.
        dataset:               Open rasterio dataset.
        search_buffer_meters:  Radius (metres) to search upslope for the peak.

    Returns:
        DepositionalResult dict or {"error": ...} on failure.
    """
    # --- STEP A: Analyse the site (parcel) ---
    site_img, site_transform = rasterio.mask.mask(dataset, [geometry], crop=True)
    site_elevations = site_img[0]  # Band 1

    site_valid_elevs = site_elevations[site_elevations != dataset.nodata]
    if len(site_valid_elevs) == 0:
        return {"error": "No valid elevation data found inside parcel geometry"}

    # Site elevation = lowest point in the lot.
    elev_site_min = np.min(site_valid_elevs)

    # Coordinates of the minimum-elevation pixel.
    min_idx = np.unravel_index(np.argmin(site_elevations), site_elevations.shape)
    site_min_xy = rasterio.transform.xy(site_transform, min_idx[0], min_idx[1])
    site_point = Point(site_min_xy)

    # --- STEP B: Analyse the vicinity (find the peak) ---
    vicinity_polygon = geometry.buffer(search_buffer_meters)

    vicinity_img, vic_transform = rasterio.mask.mask(
        dataset, [vicinity_polygon], crop=True
    )
    vic_elevations = vicinity_img[0]
    vic_valid_elevs = vic_elevations[vic_elevations != dataset.nodata]

    elev_peak_max = float(np.max(vic_valid_elevs))

    max_idx = np.unravel_index(np.argmax(vic_elevations), vic_elevations.shape)
    xs, ys = rasterio.transform.xy(vic_transform, max_idx[0], max_idx[1])
    peak_point = Point(xs, ys)

    # --- STEP C: Physics logic (H > 3 × Delta_E) ---
    delta_e = elev_peak_max - float(elev_site_min)
    h_distance = float(site_point.distance(peak_point))
    required_runout = 3.0 * delta_e

    if h_distance > required_runout:
        status = "SAFE (Beyond Runout)"
        is_compliant = True
    else:
        status = "PRONE (Within Runout Zone)"
        is_compliant = False

    return DepositionalResult(
        metrics=DepositionalMetrics(
            elevation_peak=elev_peak_max,
            elevation_site=float(elev_site_min),
            delta_e=delta_e,
            horizontal_distance_h=h_distance,
            required_runout_3x=required_runout,
        ),
        assessment=DepositionalAssessment(
            status=status,
            is_compliant=is_compliant,
        ),
    )


def calculate_depositional_safety(
    context: DEMContext,
    search_buffer_meters: int = 1000,
) -> DepositionalResult | dict:
    """Entry point accepting a DEMContext (geometry already projected)."""
    return compute_depositional_safety(
        context.geometry, context.dataset, search_buffer_meters
    )
