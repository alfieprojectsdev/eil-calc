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

def get_boundary_pixels(mask_2d):
    """
    Given a 2D boolean mask where True=inside,
    Find coordinates of all 'True' pixels that border a 'False' pixel (or array edge).
    """
    from scipy.ndimage import binary_dilation
    # Dilating the inside by 1 pixel, then XORing with the original gives the outer border.
    # We want the inside border, so we dilate the outside (False) and AND with inside (True).
    outside = ~mask_2d
    dilated_outside = binary_dilation(outside)
    inside_border = dilated_outside & mask_2d
    return np.argwhere(inside_border)


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
    site_elevations = site_img[0].astype(float)  # Band 1
    if dataset.nodata is not None:
        site_elevations[site_elevations == dataset.nodata] = np.nan

    site_valid_elevs = site_elevations[~np.isnan(site_elevations)]
    if len(site_valid_elevs) == 0:
        return {"error": "No valid elevation data found inside parcel geometry"}

    # Site elevation = lowest point in the lot.
    elev_site_min = np.nanmin(site_valid_elevs)

    # Coordinates of the minimum-elevation pixel.
    min_idx = np.unravel_index(np.nanargmin(site_elevations), site_elevations.shape)
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
    vic_elevations = vicinity_img[0].astype(float)
    if dataset.nodata is not None:
        vic_elevations[vic_elevations == dataset.nodata] = np.nan

    vic_valid_elevs = vic_elevations[~np.isnan(vic_elevations)]
    if len(vic_valid_elevs) == 0:
        return {"error": "No valid elevation data found in vicinity"}

    # We need a boolean mask of the parcel inside the vicinity grid
    # (True = inside parcel, False = outside)
    parcel_mask_vic = ~rasterio.features.geometry_mask(
        [geometry],
        out_shape=vic_elevations.shape,
        transform=vic_transform,
        invert=False
    )
    
    geod = Geod(ellps="WGS84") if (dataset.crs and dataset.crs.is_geographic) else None

    # --- STEP C: PHYSICS LOGIC (REVERSE GRADIENT ASCENT) ---
    
    # 1. Trace steepest ascent from parcel boundaries to find threatening local peaks.
    boundary_coords = get_boundary_pixels(parcel_mask_vic)
    
    unique_peaks = set()
    peak_paths = []
    
    directions = [(-1,-1), (-1,0), (-1,1), (0,-1), (0,1), (1,-1), (1,0), (1,1)]
    max_steps = 500
    
    # Uphill Walker
    for start_r, start_c in boundary_coords:
        curr_r, curr_c = start_r, start_c
        
        for _ in range(max_steps):
            max_uphill_diff = 0
            next_step = None
            curr_elev = vic_elevations[curr_r, curr_c]
            
            # Step 1: Check immediate 8 neighbors
            for dr, dc in directions:
                nr, nc = curr_r + dr, curr_c + dc
                if 0 <= nr < vic_elevations.shape[0] and 0 <= nc < vic_elevations.shape[1]:
                    # Outward-Only Constraint: Do not step if the neighbor is inside the parcel
                    if parcel_mask_vic[nr, nc]:
                        continue
                        
                    neighbor_elev = vic_elevations[nr, nc]
                    if np.isnan(neighbor_elev):
                        continue
                    
                    diff = neighbor_elev - curr_elev
                    if diff > max_uphill_diff:
                        max_uphill_diff = diff
                        next_step = (nr, nc)
            
            # Step 2: Topographic Momentum (5x5 look-ahead) if trapped
            if next_step is None:
                max_regional_elev = curr_elev
                window_r, window_c = None, None
                
                # Scan 5x5 window around current pixel (dr/dc from -2 to +2)
                for dr in range(-2, 3):
                    for dc in range(-2, 3):
                        if dr == 0 and dc == 0:
                            continue
                        nr, nc = curr_r + dr, curr_c + dc
                        if 0 <= nr < vic_elevations.shape[0] and 0 <= nc < vic_elevations.shape[1]:
                            if parcel_mask_vic[nr, nc]:
                                continue
                            
                            neighbor_elev = vic_elevations[nr, nc]
                            if not np.isnan(neighbor_elev) and neighbor_elev > max_regional_elev:
                                max_regional_elev = neighbor_elev
                                window_r, window_c = nr, nc
                
                # If we found a higher point nearby, jump to it to preserve momentum
                if window_r is not None and window_c is not None:
                    next_step = (window_r, window_c)
                else:
                    # Truly trapped on a ridge, terminate pathfinding
                    break
                
            curr_r, curr_c = next_step
            
        peak_coord = (curr_r, curr_c)
        if peak_coord not in unique_peaks:
            # Regional Filter: Ensure H > 50m
            peak_x, peak_y = rasterio.transform.xy(vic_transform, peak_coord[0], peak_coord[1])
            if geod:
                _, _, peak_dist = geod.inv(peak_x, peak_y, site_point.x, site_point.y)
            else:
                peak_dist = math.hypot(site_point.x - peak_x, site_point.y - peak_y)
                
            if peak_dist > 50.0:
                unique_peaks.add(peak_coord)
                peak_paths.append(peak_coord)

    # 2. Process downhill runouts from each unique peak
    all_transects = []
    parcel_inv_mask = ~parcel_mask_vic  # True = Outside, False = Inside
    
    for peak_r, peak_c in peak_paths:
        # Skip peaks that landed inside the parcel — the downhill stepper would
        # never enter its loop, producing h_distance=0 and an empty transect list.
        if not parcel_inv_mask[peak_r, peak_c]:
            continue

        curr_r, curr_c = peak_r, peak_c
        elev_peak_max = float(vic_elevations[peak_r, peak_c])
        delta_e = elev_peak_max - float(elev_site_min)
        
        # If the peak is lower than the parcel site, it cannot threaten it
        if delta_e <= 0:
            continue
            
        h_distance = 0.0
        visited = set()
        transect = []
        
        # Downhill Stepper
        while parcel_inv_mask[curr_r, curr_c]:
            visited.add((curr_r, curr_c))
            
            curr_x, curr_y = rasterio.transform.xy(vic_transform, curr_r, curr_c)
            transect.append({"dist_m": round(h_distance, 1), "elev_m": round(float(vic_elevations[curr_r, curr_c]), 1)})
            
            min_elev = vic_elevations[curr_r, curr_c]
            next_r, next_c = curr_r, curr_c
            
            for dr in [-1, 0, 1]:
                for dc in [-1, 0, 1]:
                    if dr == 0 and dc == 0:
                        continue
                    nr, nc = curr_r + dr, curr_c + dc
                    if 0 <= nr < vic_elevations.shape[0] and 0 <= nc < vic_elevations.shape[1]:
                        if (nr, nc) in visited:
                            continue
                            
                        elev = vic_elevations[nr, nc]
                        if not np.isnan(elev) and elev < min_elev:
                            min_elev = elev
                            next_r, next_c = nr, nc
                            
            if next_r == curr_r and next_c == curr_c:
                break
                
            next_x, next_y = rasterio.transform.xy(vic_transform, next_r, next_c)
            if geod:
                _, _, step_dist = geod.inv(curr_x, curr_y, next_x, next_y)
            else:
                step_dist = math.hypot(next_x - curr_x, next_y - curr_y)
                
            h_distance += float(step_dist)
            curr_r, curr_c = next_r, next_c

        # Trapped closure logic
        if parcel_inv_mask[curr_r, curr_c]:
            trap_x, trap_y = rasterio.transform.xy(vic_transform, curr_r, curr_c)
            if geod:
                _, _, trap_dist = geod.inv(trap_x, trap_y, site_point.x, site_point.y)
            else:
                trap_dist = math.hypot(site_point.x - trap_x, site_point.y - trap_y)
            h_distance += float(trap_dist)
            transect.append({"dist_m": round(h_distance, 1), "elev_m": round(float(elev_site_min), 1)})
        else:
            transect.append({"dist_m": round(h_distance, 1), "elev_m": round(float(vic_elevations[curr_r, curr_c]), 1)})

        required_runout = 3.0 * delta_e
        is_compliant = h_distance > required_runout
        status = "SAFE (Beyond Runout)" if is_compliant else "PRONE (Within Runout Zone)"
        
        # Threat ratio: > 1.0 means it impacts the site. Larger = deeper impact.
        threat_ratio = required_runout / h_distance if h_distance > 0 else float('inf')
        
        all_transects.append({
            "metrics": DepositionalMetrics(
                elevation_peak=elev_peak_max,
                elevation_site=float(elev_site_min),
                delta_e=delta_e,
                horizontal_distance_h=h_distance,
                required_runout_3x=required_runout,
            ),
            "assessment": DepositionalAssessment(
                status=status,
                is_compliant=is_compliant,
            ),
            "path": transect,
            "threat_ratio": threat_ratio
        })

    # 3. Sort by severity (highest threat ratio first)
    all_transects.sort(key=lambda t: t["threat_ratio"], reverse=True)
    
    # Take top 3 most critical paths
    top_3_transects = all_transects[:3]
    
    if not top_3_transects:
        # Fallback: No threatening peaks found (e.g. flat land, hilltop parcel)
        dummy_metrics = DepositionalMetrics(
            elevation_peak=float(elev_site_min),
            elevation_site=float(elev_site_min),
            delta_e=0.0,
            horizontal_distance_h=0.0,
            required_runout_3x=0.0,
        )
        dummy_path = [{"dist_m": 0.0, "elev_m": round(float(elev_site_min), 1)}]
        
        return DepositionalResult(
            metrics=dummy_metrics,
            assessment=DepositionalAssessment(status="SAFE (Beyond Runout)", is_compliant=True),
            _viz_transects=[{
                "metrics": dummy_metrics,
                "assessment": DepositionalAssessment(status="SAFE (Beyond Runout)", is_compliant=True),
                "path": dummy_path,
                "threat_ratio": 0.0
            }]
        )
         
    # Determine absolute parcel safety based on worst-case path
    overall_compliant = all(t["assessment"]["is_compliant"] for t in top_3_transects)
    overall_status = "SAFE (Beyond Runout)" if overall_compliant else "PRONE (Within Runout Zone)"

    return DepositionalResult(
        metrics=top_3_transects[0]["metrics"], # Return worst-case as top-level default
        assessment=DepositionalAssessment(
            status=overall_status,
            is_compliant=overall_compliant,
        ),
        _viz_transects=top_3_transects,
    )


def calculate_depositional_safety(
    context: DEMContext,
    search_buffer_meters: int = 1000,
) -> DepositionalResult | dict:
    """Entry point accepting a DEMContext (geometry already projected)."""
    return compute_depositional_safety(
        context.geometry, context.dataset, search_buffer_meters
    )
