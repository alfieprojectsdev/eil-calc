import math

import rasterio
import rasterio.features
import rasterio.mask
import numpy as np
from pyproj import Geod
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
    # Buffer must be in the dataset's native CRS units.
    # For geographic CRS (degrees), convert metres to degrees at the parcel's latitude.
    if dataset.crs and dataset.crs.is_geographic:
        lat_rad = math.radians(geometry.centroid.y)
        search_buffer = search_buffer_meters / (111320.0 * math.cos(lat_rad))
    else:
        search_buffer = float(search_buffer_meters)
    vicinity_polygon = geometry.buffer(search_buffer)

    vicinity_img, vic_transform = rasterio.mask.mask(
        dataset, [vicinity_polygon], crop=True
    )
    vic_elevations = vicinity_img[0]
    vic_valid_elevs = vic_elevations[vic_elevations != dataset.nodata]

    elev_peak_max = float(np.max(vic_valid_elevs))

    max_idx = np.unravel_index(np.argmax(vic_elevations), vic_elevations.shape)
    xs, ys = rasterio.transform.xy(vic_transform, max_idx[0], max_idx[1])
    peak_point = Point(xs, ys)

    # --- STEP C: Physics logic (H > 3 × Delta_E) via Topographic Runout Routing ---
    delta_e = elev_peak_max - float(elev_site_min)
    
    # We need a boolean mask of the parcel inside the vicinity grid
    parcel_mask_vic = rasterio.features.geometry_mask(
        [geometry],
        out_shape=vic_elevations.shape,
        transform=vic_transform,
        invert=True
    )
    
    geod = Geod(ellps="WGS84") if (dataset.crs and dataset.crs.is_geographic) else None

    # Path routing (Steepest Descent)
    curr_r, curr_c = max_idx
    h_distance = 0.0
    visited = set()
    transect = []

    while not parcel_mask_vic[curr_r, curr_c]:
        visited.add((curr_r, curr_c))
        
        # save transect point
        curr_x, curr_y = rasterio.transform.xy(vic_transform, curr_r, curr_c)
        transect.append({"dist_m": round(h_distance, 1), "elev_m": round(float(vic_elevations[curr_r, curr_c]), 1)})
        
        min_elev = vic_elevations[curr_r, curr_c]
        next_r, next_c = curr_r, curr_c
        
        for dr in [-1, 0, 1]:
            for dc in [-1, 0, 1]:
                if dr == 0 and dc == 0:
                    continue
                nr, nc = len(vic_elevations) and curr_r + dr, curr_c + dc
                if 0 <= nr < vic_elevations.shape[0] and 0 <= nc < vic_elevations.shape[1]:
                    if (nr, nc) in visited:
                        continue
                        
                    elev = vic_elevations[nr, nc]
                    if elev != dataset.nodata and elev < min_elev:
                        min_elev = elev
                        next_r, next_c = nr, nc
                        
        if next_r == curr_r and next_c == curr_c:
            # Trapped in a local bowl or flat area before reaching the parcel.
            break

        next_x, next_y = rasterio.transform.xy(vic_transform, next_r, next_c)
        if geod:
            _, _, step_dist = geod.inv(curr_x, curr_y, next_x, next_y)
        else:
            step_dist = math.hypot(next_x - curr_x, next_y - curr_y)
            
        h_distance += float(step_dist)
        curr_r, curr_c = next_r, next_c

    # If trapped, we compute the remaining distance from trap to site_point
    if not parcel_mask_vic[curr_r, curr_c]:
        trap_x, trap_y = rasterio.transform.xy(vic_transform, curr_r, curr_c)
        if geod:
            _, _, trap_dist = geod.inv(trap_x, trap_y, site_point.x, site_point.y)
        else:
            trap_dist = math.hypot(site_point.x - trap_x, site_point.y - trap_y)
            
        h_distance += float(trap_dist)
        transect.append({"dist_m": round(h_distance, 1), "elev_m": round(float(elev_site_min), 1)})
    else:
        # Reached the parcel gracefully
        transect.append({"dist_m": round(h_distance, 1), "elev_m": round(float(vic_elevations[curr_r, curr_c]), 1)})

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
        _viz_transect=transect,
    )


def calculate_depositional_safety(
    context: DEMContext,
    search_buffer_meters: int = 1000,
) -> DepositionalResult | dict:
    """Entry point accepting a DEMContext (geometry already projected)."""
    return compute_depositional_safety(
        context.geometry, context.dataset, search_buffer_meters
    )
