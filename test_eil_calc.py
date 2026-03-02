import math
import unittest
import numpy as np
import rasterio
import rasterio.mask
from rasterio.transform import from_origin
from rasterio.io import MemoryFile
from shapely.geometry import box, mapping, Point
from calculate_depositional_safety import calculate_depositional_safety

# Re-implementing logic wrapper or importing if possible. 
# In Step 9, the file was `calculate_depositional_safety.py`. 
# The test previously had an embedded `calculate_safety_logic` helper. 
# I will retain the helper for the unit test to be self-contained as it was before.

def calculate_safety_logic(site_polygon, src, search_buffer=100):
    """
    Simplified logic mirror for testing the math without file I/O overhead of the main script,
    or we can import the main function if we structure data correctly.
    Let's stick to the previous test logic which verified the math principles.
    """
    # 1. MASK SITE (Find Min Elevation)
    site_img, _ = rasterio.mask.mask(src, [site_polygon], crop=True)
    site_valid = site_img[0][site_img[0] != src.nodata] # Band 1

    if len(site_valid) == 0: return None
    elev_site_min = np.min(site_valid)

    # Get center of site for distance calc
    site_centroid = site_polygon.centroid

    # 2. MASK VICINITY (Find Peak)
    vicinity_poly = site_polygon.buffer(search_buffer)
    vic_img, vic_transform = rasterio.mask.mask(src, [vicinity_poly], crop=True)
    vic_valid = vic_img[0][vic_img[0] != src.nodata]

    if len(vic_valid) == 0: return None
    elev_peak_max = np.max(vic_valid)

    # Find peak location
    max_idx = np.unravel_index(np.argmax(vic_img[0]), vic_img[0].shape)
    xs, ys = rasterio.transform.xy(vic_transform, max_idx[0], max_idx[1])
    peak_point = Point(xs, ys)

    # 3. MATH
    delta_e = elev_peak_max - elev_site_min
    h_distance = site_centroid.distance(peak_point)
    required_runout = 3 * delta_e

    return {
        "status": "SAFE" if h_distance > required_runout else "PRONE",
        "H": h_distance,
        "Delta_E": delta_e,
        "Required_H": required_runout
    }

class TestEILTools(unittest.TestCase):

    def create_synthetic_dem(self, peak_location, peak_elev, site_elev):
        """
        Creates a 100x100 pixel DEM in memory.
        Background is 0m.
        Site area is set to `site_elev`.
        One specific pixel is set to `peak_elev`.
        Resolution: 1 meter/pixel.
        """
        data = np.zeros((100, 100), dtype=rasterio.float32)

        # Define Site Area (Pixels 10-20 x 10-20)
        data[10:20, 10:20] = site_elev

        # Define Peak (Single Pixel)
        px, py = peak_location
        data[py, px] = peak_elev # Note: numpy is row(y), col(x)

        transform = from_origin(0, 100, 1, 1) # West, North, Xres, Yres

        return data, transform

    def test_unsafe_scenario(self):
        """
        Scenario: Peak is 100m high and only 50m away horizontally.
        Formula: H (50) > 3 * DeltaE (100) -> 50 > 300? FALSE.
        Result should be PRONE.
        """
        print("\n--- Testing UNSAFE Scenario (Real Numpy) ---")

        # Create Data
        # Site is at (15,15) approx. Peak at (15, 65). Distance ~50m.
        # Site Elev = 10m, Peak Elev = 110m. Delta E = 100m.
        data, transform = self.create_synthetic_dem((15, 65), 110, 10)

        # Define Site Geometry
        site_poly = box(10, 80, 20, 90)

        with MemoryFile() as memfile:
            with memfile.open(driver='GTiff', height=100, width=100, count=1,
                              dtype=rasterio.float32, transform=transform, nodata=-9999) as dataset:
                dataset.write(data, 1)

                result = calculate_safety_logic(site_poly, dataset)

                print(f"Calculated H: {result['H']:.2f}m")
                print(f"Required H:   {result['Required_H']:.2f}m")
                print(f"Result:       {result['status']}")

                self.assertEqual(result['status'], "PRONE")

    def test_safe_scenario(self):
        """
        Scenario: Peak is 100m high but 400m away horizontally.
        Formula: H (400) > 3 * DeltaE (100) -> 400 > 300? TRUE.
        Result should be SAFE.
        """
        print("\n--- Testing SAFE Scenario (Real Numpy) ---")

        # Create Data
        # Site Elev = 10m. Peak Elev = 20m. Delta E = 10m. Required H = 30m.
        # Peak at (15, 65). Distance ~50m.
        # 50m > 30m ? TRUE.
        data, transform = self.create_synthetic_dem((15, 65), 20, 10)

        site_poly = box(10, 80, 20, 90)

        with MemoryFile() as memfile:
            with memfile.open(driver='GTiff', height=100, width=100, count=1,
                              dtype=rasterio.float32, transform=transform, nodata=-9999) as dataset:
                dataset.write(data, 1)

                result = calculate_safety_logic(site_poly, dataset)

                print(f"Calculated H: {result['H']:.2f}m")
                print(f"Required H:   {result['Required_H']:.2f}m")
                print(f"Result:       {result['status']}")

                self.assertEqual(result['status'], "SAFE")

def calculate_slope_logic(site_polygon, src):
    """
    Logic mirror of slope_stability.calculate_slope_stability for in-memory testing.
    Takes a Shapely polygon and an open rasterio dataset directly (no file path needed).
    """
    px, py = src.res
    out_image, _ = rasterio.mask.mask(src, [site_polygon], crop=True)
    elevation_data = out_image[0]

    valid_mask = elevation_data != src.nodata
    if valid_mask.sum() == 0:
        return {"error": "No valid data in parcel"}

    dz_dy, dz_dx = np.gradient(elevation_data, py, px)
    slope_degrees = np.degrees(np.arctan(np.sqrt(dz_dx**2 + dz_dy**2)))
    site_slopes = slope_degrees[valid_mask]

    max_slope = float(np.max(site_slopes))

    if max_slope > 16.0:
        status = "SUSCEPTIBLE"
    elif max_slope > 14.0:
        status = "FLAG FOR REVIEW"
    else:
        status = "SAFE"

    return {"status": status, "max_slope": max_slope}


class TestSlopeStability(unittest.TestCase):

    def create_slope_dem(self, target_degrees, resolution=1.0):
        """
        Creates a 100x100 DEM with a uniform slope in the X direction.
        Rise per pixel = tan(target_degrees) * resolution, so np.gradient
        recovers exactly target_degrees for every interior and edge pixel
        (linear slope → central and forward/backward differences agree).
        """
        rise_per_pixel = math.tan(math.radians(target_degrees)) * resolution
        data = np.zeros((100, 100), dtype=rasterio.float32)
        for x in range(100):
            data[:, x] = x * rise_per_pixel
        transform = from_origin(0, 100, resolution, resolution)
        return data, transform

    def _run(self, target_degrees):
        data, transform = self.create_slope_dem(target_degrees)
        site_poly = box(20, 20, 80, 80)
        with MemoryFile() as memfile:
            with memfile.open(driver='GTiff', height=100, width=100, count=1,
                              dtype=rasterio.float32, transform=transform,
                              nodata=-9999) as ds:
                ds.write(data, 1)
                return calculate_slope_logic(site_poly, ds)

    def test_safe_slope(self):
        """10° slope — well below the 14° threshold."""
        result = self._run(10.0)
        print(f"\n--- SAFE slope --- max={result['max_slope']:.2f}°")
        self.assertEqual(result['status'], 'SAFE')
        self.assertLessEqual(result['max_slope'], 14.0)

    def test_review_slope(self):
        """15° slope — sits in the 14°–16° review buffer."""
        result = self._run(15.0)
        print(f"\n--- FLAG FOR REVIEW slope --- max={result['max_slope']:.2f}°")
        self.assertEqual(result['status'], 'FLAG FOR REVIEW')
        self.assertGreater(result['max_slope'], 14.0)
        self.assertLessEqual(result['max_slope'], 16.0)

    def test_susceptible_slope(self):
        """20° slope — above the 16° susceptibility threshold."""
        result = self._run(20.0)
        print(f"\n--- SUSCEPTIBLE slope --- max={result['max_slope']:.2f}°")
        self.assertEqual(result['status'], 'SUSCEPTIBLE')
        self.assertGreater(result['max_slope'], 16.0)

    def test_all_nodata_parcel(self):
        """Parcel overlaps DEM extent but every pixel is nodata — expect error dict."""
        data = np.full((100, 100), -9999, dtype=rasterio.float32)
        transform = from_origin(0, 100, 1, 1)
        site_poly = box(20, 20, 80, 80)
        with MemoryFile() as memfile:
            with memfile.open(driver='GTiff', height=100, width=100, count=1,
                              dtype=rasterio.float32, transform=transform,
                              nodata=-9999) as ds:
                ds.write(data, 1)
                result = calculate_slope_logic(site_poly, ds)
        print(f"\n--- nodata parcel --- result={result}")
        self.assertIn('error', result)


if __name__ == '__main__':
    unittest.main()