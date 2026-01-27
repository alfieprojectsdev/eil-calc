import rasterio
import rasterio.mask
import numpy as np
from shapely.geometry import shape, Point, mapping
from shapely.ops import transform
import json

def calculate_depositional_safety(parcel_geojson, dem_path, search_buffer_meters=1000):
    """
    Calculates EIL Depositional Zone safety based on geometric reach.

    Args:
        parcel_geojson (dict): The GeoJSON dictionary of the site.
        dem_path (str): Path to the DEM (GeoTIFF).
        search_buffer_meters (int): Distance to search upslope for the 'Peak'.

    Returns:
        dict: JSON object with H, Delta_E, and Safety Status.
    """

    # 1. Parse Geometry
    site_polygon = shape(parcel_geojson['geometry'])

    # Open DEM
    with rasterio.open(dem_path) as src:

        # --- STEP A: Analyze the Site (Parcel) ---
        # Mask DEM to exactly the parcel boundaries to find the Site's lowest point
        site_img, site_transform = rasterio.mask.mask(src, [site_polygon], crop=True)
        site_elevations = site_img[0] # Band 1

        # Filter out NoData (usually -9999 or similar)
        site_valid_elevs = site_elevations[site_elevations != src.nodata]

        if len(site_valid_elevs) == 0:
            return {"error": "No valid elevation data found inside parcel geometry"}

        # Define 'Site' elevation as the lowest point in the lot
        elev_site_min = np.min(site_valid_elevs)

        # Find coordinates of the min point (pixel center)
        # Note: robust implementation would vectorize this, simplified here for prototype
        min_idx = np.unravel_index(np.argmin(site_elevations), site_elevations.shape)
        site_min_xy = src.xy(min_idx[0], min_idx[1]) # Returns (x, y)
        site_point = Point(site_min_xy)

        # --- STEP B: Analyze the Vicinity (Find the Peak) ---
        # Create a buffer to look for the hazard source (the mountain peak)
        # Note: This assumes projected CRS (meters). If Lat/Lon, this buffer needs reprojection.
        vicinity_polygon = site_polygon.buffer(search_buffer_meters)

        vicinity_img, vic_transform = rasterio.mask.mask(src, [vicinity_polygon], crop=True)
        vic_elevations = vicinity_img[0]
        vic_valid_elevs = vic_elevations[vic_elevations != src.nodata]

        # Define 'Peak' as the highest point in the search buffer
        elev_peak_max = np.max(vic_valid_elevs)

        # Find coordinates of the Peak
        max_idx = np.unravel_index(np.argmax(vic_elevations), vic_elevations.shape)
        # We need to transform relative pixel coords back to world coords
        # Using the transform of the cropped vicinity image
        xs, ys = rasterio.transform.xy(vic_transform, max_idx[0], max_idx[1])
        peak_point = Point(xs, ys)

        # --- STEP C: The Physics Logic (H > 3 * Delta_E) ---

        # Calculate Delta E (Elevation Difference)
        delta_e = elev_peak_max - elev_site_min

        # Calculate H (Horizontal Euclidean Distance)
        h_distance = site_point.distance(peak_point)

        # The Threshold
        required_runout = 3 * delta_e

        if h_distance > required_runout:
            status = "SAFE (Beyond Runout)"
            is_safe = True
        else:
            status = "PRONE (Within Runout Zone)"
            is_safe = False

        return {
            "metrics": {
                "elevation_peak": float(elev_peak_max),
                "elevation_site": float(elev_site_min),
                "delta_e": float(delta_e),
                "horizontal_distance_h": float(h_distance),
                "required_runout_3x": float(required_runout)
            },
            "assessment": {
                "status": status,
                "is_compliant": is_safe
            }
        }

# Example Usage Mockup
if __name__ == "__main__":
    # Mock GeoJSON for testing
    mock_geojson = {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[121.0, 14.5], [121.01, 14.5], [121.01, 14.51], [121.0, 14.51], [121.0, 14.5]]]
        }
    }

    # print(calculate_depositional_safety(mock_geojson, "path/to/local_dem.tif"))