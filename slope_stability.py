import rasterio
import rasterio.mask
import numpy as np
from shapely.geometry import shape

def calculate_slope_stability(parcel_geojson, dem_path):
    """
    Calculates EIL Slope Stability based on gradient thresholds.
    
    Thresholds:
    - < 5 deg: SAFE
    - 5 - 15 deg: REVIEW (Buffer)
    - > 15 deg: SUSCEPTIBLE
    """
    
    # 1. Parse Geometry
    site_polygon = shape(parcel_geojson['geometry'])
    
    with rasterio.open(dem_path) as src:
        # Mask to Parcel
        out_image, out_transform = rasterio.mask.mask(src, [site_polygon], crop=True)
        elevation_data = out_image[0]
        
        # Filter NoData
        valid_mask = elevation_data != src.nodata
        valid_elevations = elevation_data[valid_mask]
        
        if valid_elevations.size == 0:
             return {"error": "No valid data in parcel"}

        # Calculate Gradient (Simplified approach using numpy gradient)
        # In a real GIS app, we'd use richdem or gdaldem slope
        # Here we approximate: Slope = rise/run. 
        # CAUTION: np.gradient computes differences between neighbors.
        # Need pixel size.
        
        px, py = src.res
        # Gradient dZ/dX and dZ/dY
        
        # We need the full 2D array for gradient, but masked 'out_image' has 0s or nodata outside
        # Let's compute gradient on the cropped array, then mask again.
        
        # Handle nodata for gradient calculation (fill with mean or something to avoid edge artifacts? 
        # Or just ignore edges).
        # For prototype: simple approx.
        
        dz_dy, dz_dx = np.gradient(elevation_data, py, px)
        slope_radians = np.arctan(np.sqrt(dz_dx**2 + dz_dy**2))
        slope_degrees = np.degrees(slope_radians)
        
        # Apply mask again to only consider pixels INSIDE the polygon
        # (rasterio mask sets outside to nodata, usually)
        # We rely on valid_mask
        
        site_slopes = slope_degrees[valid_mask]
        
        if site_slopes.size == 0:
             return {"error": "No valid slope data"}
        
        max_slope = np.max(site_slopes)
        avg_slope = np.mean(site_slopes)
        
        # Classification
        # Using Max Slope as conservative metric
        if max_slope > 15.0:
            status = "SUSCEPTIBLE"
        elif max_slope > 5.0:
            status = "FLAG FOR REVIEW"
        else:
            status = "SAFE"
            
        return {
            "metrics": {
                "max_slope_degrees": float(max_slope),
                "avg_slope_degrees": float(avg_slope)
            },
            "assessment": {
                "status": status,
                "threshold_used": "max_slope"
            }
        }
