import math

import scipy.ndimage as ndimage
import rasterio.features
import rasterio.mask
import numpy as np
from shapely.geometry.base import BaseGeometry

from skimage import feature, segmentation
from eil_types import DEMContext, SlopeAssessment, SlopeMetrics, SlopeResult

_CATCHMENT_BUFFER_METRES = 500.0


def compute_slope_stability(geometry: BaseGeometry, dataset) -> SlopeResult | dict:
    """Compute slope stability from an open rasterio dataset.

    Args:
        geometry: Parcel polygon already in dataset CRS.
        dataset:  Open rasterio dataset.

    Returns:
        SlopeResult dict or {"error": ...} on failure.
    """
    px, py = dataset.res
    if dataset.crs and dataset.crs.is_geographic:
        lat_rad = math.radians(geometry.centroid.y)
        py_m_deg = py * 111320.0
        px_m_deg = px * 111320.0 * math.cos(lat_rad)
        buffer_dist = _CATCHMENT_BUFFER_METRES / 111320.0
    else:
        py_m_deg, px_m_deg = py, px
        buffer_dist = _CATCHMENT_BUFFER_METRES

    # Buffer the parcel so edge pixels have real neighbours during gradient
    # computation, preventing nodata sentinels from producing false 90° slopes.
    buffered_geom = geometry.buffer(buffer_dist)

    out_image, out_transform = rasterio.mask.mask(dataset, [buffered_geom], crop=True)
    elevation_data = out_image[0].astype(float)

    # NaN-out nodata pixels before gradient so arithmetic against sentinel values
    # (e.g. IfSAR INT32_MAX=2147483648, SRTM 0.0) does not corrupt slope angles.
    # Note: SRTM nodata=0.0 means valid sea-level pixels in the buffer zone are
    # also NaN'd, but they lie outside the actual parcel so this is acceptable.
    if dataset.nodata is not None:
        elevation_data[elevation_data == dataset.nodata] = np.nan

    # --- Feature 3.1: DEM Noise Mitigation (Spatial Smoothing) ---
    # Apply a Gaussian low-pass filter to remove micro-topographic artifacts 
    # before evaluating the slope threshold. A sigma of 2.0 on 5m pixels 
    # mimics a ~30m mesoscale resolution.
    valid_mask = ~np.isnan(elevation_data)
    elev_filled = np.nan_to_num(elevation_data, nan=0.0)
    
    # Smooth the filled elevation and the validity mask to prevent NaN propagation
    smoothed_elev = ndimage.gaussian_filter(elev_filled * valid_mask, sigma=2.0)
    weight_map = ndimage.gaussian_filter(valid_mask.astype(float), sigma=2.0)
    
    elevation_smoothed = np.full_like(elevation_data, np.nan)
    valid_weights = weight_map > 1e-6
    elevation_smoothed[valid_weights] = smoothed_elev[valid_weights] / weight_map[valid_weights]
    
    # Re-apply the strict nodata mask to keep bounds sharp
    elevation_smoothed[~valid_mask] = np.nan

    dz_dy, dz_dx = np.gradient(elevation_smoothed, py_m_deg, px_m_deg)
    slope_degrees = np.degrees(np.arctan(np.sqrt(dz_dx**2 + dz_dy**2)))

    # Restrict the metric to pixels inside the original (unbuffered) parcel.
    parcel_mask = rasterio.features.geometry_mask(
        [geometry],
        out_shape=elevation_data.shape,
        transform=out_transform,
        invert=True,  # True → pixels inside geometry are True
    )

    # --- Feature 3.2: Dynamic Slope Unit (SU) Delineation ---
    # Partition the terrain into natural drainage basins (bounded by ridges).
    # 1. Identify local minima to serve as pour points mapping to the watershed.
    elev_valid = np.nan_to_num(elevation_smoothed, nan=np.nanmax(elevation_smoothed))
    
    # Find natural local minima in the smoothed elevation (valleys/sinks)
    minima_coords = feature.peak_local_max(-elev_valid, min_distance=10, exclude_border=False)
    
    markers = np.zeros_like(elevation_smoothed, dtype=int)
    for i, (r, c) in enumerate(minima_coords, start=1):
        markers[r, c] = i
        
    # Segment terrain using standard watershed
    catchments = segmentation.watershed(elev_valid, markers, mask=valid_mask)
    
    # Identify which natural drainage basins (SUs) intersect the original parcel footprint
    overlapping_sus = np.unique(catchments[parcel_mask])
    overlapping_sus = overlapping_sus[overlapping_sus > 0]
    
    if len(overlapping_sus) > 0:
        su_mask = np.isin(catchments, overlapping_sus)
    else:
        su_mask = parcel_mask  # Fallback if the watershed is totally flat
        
    # Evaluate slope constraints strictly within the natural slope unit
    site_slopes = slope_degrees[su_mask & valid_mask]
    site_slopes = site_slopes[~np.isnan(site_slopes)]

    if site_slopes.size == 0:
        return {"error": "No valid slope data"}

    max_slope = float(np.nanmax(site_slopes))
    avg_slope = float(np.nanmean(site_slopes))

    # Mask the 2D gradient array to NaN where the pixel isn't inside the parcel bounds
    # (for the heatmap output).
    viz_grid = slope_degrees.copy()
    viz_grid[~parcel_mask] = np.nan
    viz_grid_list = np.where(np.isnan(viz_grid), None, viz_grid).tolist()

    if max_slope > 16.0:
        status = "SUSCEPTIBLE"
    elif max_slope > 14.0:
        status = "FLAG FOR REVIEW"
    else:
        status = "SAFE"

    return SlopeResult(
        metrics=SlopeMetrics(max_slope_degrees=max_slope, avg_slope_degrees=avg_slope),
        assessment=SlopeAssessment(status=status, threshold_used="max_slope"),
        _viz_grid=viz_grid_list,
    )


def calculate_slope_stability(context: DEMContext) -> SlopeResult | dict:
    """Entry point accepting a DEMContext (geometry already projected)."""
    return compute_slope_stability(context.geometry, context.dataset)
