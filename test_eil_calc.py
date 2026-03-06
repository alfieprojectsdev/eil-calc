import math
import unittest
import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.io import MemoryFile
from shapely.geometry import box

from slope_stability import compute_slope_stability
from calculate_depositional_safety import compute_depositional_safety


class TestEILTools(unittest.TestCase):

    def create_synthetic_dem(self, peak_location, peak_elev, site_elev):
        """Creates a 100x100 pixel DEM in memory.
        
        Creates a conical gradient radiating downwards from the peak so the 
        uphill-walker can trace the path.
        Resolution: 1 metre/pixel.
        """
        data = np.zeros((100, 100), dtype=rasterio.float32)
        px, py = peak_location
        
        # Calculate roughly what slope is needed to hit site_elev from peak_elev at distance 50m
        # (Assuming the site is around 50m away as in the tests).
        drop_per_m = (peak_elev - site_elev) / 50.0 if peak_elev > site_elev else 0
        
        for y in range(100):
            for x in range(100):
                dist = math.hypot(x - px, y - py)
                data[y, x] = max(0, peak_elev - (dist * drop_per_m))
                
        # Flatten the site area
        data[10:20, 10:20] = site_elev
        transform = from_origin(0, 100, 1, 1)  # West, North, Xres, Yres
        return data, transform

    def test_unsafe_scenario(self):
        """Peak 100 m high and only ~50 m away — should be PRONE."""
        print("\n--- Testing UNSAFE Scenario ---")
        data, transform = self.create_synthetic_dem((15, 65), 110, 10)
        site_poly = box(10, 80, 20, 90)

        with MemoryFile() as memfile:
            with memfile.open(
                driver="GTiff",
                height=100,
                width=100,
                count=1,
                dtype=rasterio.float32,
                transform=transform,
                nodata=-9999,
            ) as dataset:
                dataset.write(data, 1)
                result = compute_depositional_safety(site_poly, dataset, search_buffer_meters=100)

        print(f"H: {result['metrics']['horizontal_distance_h']:.2f} m")
        print(f"Required H: {result['metrics']['required_runout_3x']:.2f} m")
        print(f"Status: {result['assessment']['status']}")
        self.assertIn("PRONE", result["assessment"]["status"])

    def test_safe_scenario(self):
        """Peak only 10 m higher than site and ~50 m away — should be SAFE."""
        print("\n--- Testing SAFE Scenario ---")
        data, transform = self.create_synthetic_dem((15, 65), 20, 10)
        site_poly = box(10, 80, 20, 90)

        with MemoryFile() as memfile:
            with memfile.open(
                driver="GTiff",
                height=100,
                width=100,
                count=1,
                dtype=rasterio.float32,
                transform=transform,
                nodata=-9999,
            ) as dataset:
                dataset.write(data, 1)
                result = compute_depositional_safety(site_poly, dataset, search_buffer_meters=100)

        print(f"H: {result['metrics']['horizontal_distance_h']:.2f} m")
        print(f"Required H: {result['metrics']['required_runout_3x']:.2f} m")
        print(f"Status: {result['assessment']['status']}")
        self.assertIn("SAFE", result["assessment"]["status"])


class TestSlopeStability(unittest.TestCase):

    def create_slope_dem(self, target_degrees, resolution=1.0):
        """Creates a 100x100 DEM with a uniform slope in the X direction.

        Rise per pixel = tan(target_degrees) × resolution, so np.gradient
        recovers exactly ``target_degrees`` for every interior and edge pixel
        (linear slope means central and forward/backward differences agree).
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
            with memfile.open(
                driver="GTiff",
                height=100,
                width=100,
                count=1,
                dtype=rasterio.float32,
                transform=transform,
                nodata=-9999,
            ) as ds:
                ds.write(data, 1)
                return compute_slope_stability(site_poly, ds)

    def test_safe_slope(self):
        """10° slope — well below the 14° threshold."""
        result = self._run(10.0)
        print(f"\n--- SAFE slope --- max={result['metrics']['max_slope_degrees']:.2f}°")
        self.assertEqual(result["assessment"]["status"], "SAFE")
        self.assertLessEqual(result["metrics"]["max_slope_degrees"], 14.0)

    def test_review_slope(self):
        """15° slope — sits in the 14°–16° review buffer."""
        result = self._run(15.0)
        print(f"\n--- FLAG FOR REVIEW slope --- max={result['metrics']['max_slope_degrees']:.2f}°")
        self.assertEqual(result["assessment"]["status"], "FLAG FOR REVIEW")
        self.assertGreater(result["metrics"]["max_slope_degrees"], 14.0)
        self.assertLessEqual(result["metrics"]["max_slope_degrees"], 16.0)

    def test_susceptible_slope(self):
        """20° slope — above the 16° susceptibility threshold."""
        result = self._run(20.0)
        print(f"\n--- SUSCEPTIBLE slope --- max={result['metrics']['max_slope_degrees']:.2f}°")
        self.assertEqual(result["assessment"]["status"], "SUSCEPTIBLE")
        self.assertGreater(result["metrics"]["max_slope_degrees"], 16.0)

    def test_all_nodata_parcel(self):
        """Every pixel is nodata — expect an error dict."""
        data = np.full((100, 100), -9999, dtype=rasterio.float32)
        transform = from_origin(0, 100, 1, 1)
        site_poly = box(20, 20, 80, 80)
        with MemoryFile() as memfile:
            with memfile.open(
                driver="GTiff",
                height=100,
                width=100,
                count=1,
                dtype=rasterio.float32,
                transform=transform,
                nodata=-9999,
            ) as ds:
                ds.write(data, 1)
                result = compute_slope_stability(site_poly, ds)
        print(f"\n--- nodata parcel --- result={result}")
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
