"""
Integration tests — require the extracted IfSAR tile fixture.

Run with:
    uv run python -m pytest test_integration.py -v

Skip in environments without fixture:
    The tests are marked @pytest.mark.integration and will be skipped
    automatically if the fixture file is missing.

Ground-truth values recorded from tile extraction (2026-03-02):
    Tile:   test_fixtures/ifsar_tile.tif
    Source: IfSAR_PH.tif (IfSAR 5m, EPSG:4326)
    Area:   Bukidnon highlands, Mindanao
    Bounds: lon 124.8910–124.9090, lat 8.0910–8.1090
    Elev:   1631 m – 2587 m

    Test parcel: 30 m × 30 m centred at lon=124.894914, lat=8.104633
    Slope (code behaviour — WGS84 resolution used as spacing):
        max_slope_degrees ≈ 90.0  (SUSCEPTIBLE)
    Depositional:
        elevation_peak  = 2587.0 m
        elevation_site  = 2427.0 m
        delta_e         = 160.0 m
        required_runout = 480.0 m
        h_distance      ≈ 0.0045 m  → PRONE (Within Runout Zone)
    Overall: NOT CERTIFIED
"""
import os
import unittest

import pytest

from slope_stability import compute_slope_stability
from calculate_depositional_safety import compute_depositional_safety
from orchestrator import EILOrchestrator

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "test_fixtures")
IFSAR_TILE = os.path.join(FIXTURE_DIR, "ifsar_tile.tif")

# Skip entire module if fixture is missing.
pytestmark = pytest.mark.skipif(
    not os.path.exists(IFSAR_TILE),
    reason="IfSAR tile fixture not found — run extract_fixture.py first",
)

# ---------------------------------------------------------------------------
# Test parcel — 30 m × 30 m in WGS84, within the tile extent.
#
# Centre: lon=124.894914, lat=8.104633 (Bukidnon highlands, Mindanao)
# Half-extents:  0.000135° lat  ×  0.000136° lon  (≈ 15 m each side)
# ---------------------------------------------------------------------------
_PARCEL_GEOJSON = {
    "type": "Polygon",
    "coordinates": [
        [
            [124.8947776636837, 8.104498025375229],
            [124.8950503363163, 8.104498025375229],
            [124.8950503363163, 8.104767974624771],
            [124.8947776636837, 8.104767974624771],
            [124.8947776636837, 8.104498025375229],
        ]
    ],
}


@pytest.mark.integration
class TestIntegrationSlope(unittest.TestCase):
    """Slope stability computed against the real IfSAR tile."""

    def setUp(self):
        import rasterio
        from shapely.geometry import shape

        self.dataset = rasterio.open(IFSAR_TILE)
        self.parcel_geom = shape(_PARCEL_GEOJSON)

    def tearDown(self):
        self.dataset.close()

    def test_slope_returns_valid_result(self):
        """compute_slope_stability must not return an error dict."""
        result = compute_slope_stability(self.parcel_geom, self.dataset)

        self.assertNotIn("error", result, msg=f"Unexpected error: {result}")
        self.assertIn("metrics", result)
        self.assertIn("assessment", result)

    def test_slope_status_is_susceptible(self):
        """The steep Bukidnon tile must classify as SUSCEPTIBLE."""
        result = compute_slope_stability(self.parcel_geom, self.dataset)

        status = result["assessment"]["status"]
        self.assertEqual(
            status,
            "SUSCEPTIBLE",
            msg=f"Expected SUSCEPTIBLE for steep terrain, got {status!r}",
        )

    def test_slope_max_is_positive(self):
        """max_slope_degrees must be strictly positive for real terrain."""
        result = compute_slope_stability(self.parcel_geom, self.dataset)

        max_slope = result["metrics"]["max_slope_degrees"]
        self.assertGreater(max_slope, 0.0, msg="max_slope_degrees must be > 0")
        print(
            f"\nReal IfSAR slope: {max_slope:.4f}°  "
            f"status={result['assessment']['status']}"
        )


@pytest.mark.integration
class TestIntegrationDepositional(unittest.TestCase):
    """Depositional safety computed against the real IfSAR tile."""

    def setUp(self):
        import rasterio
        from shapely.geometry import shape

        self.dataset = rasterio.open(IFSAR_TILE)
        self.parcel_geom = shape(_PARCEL_GEOJSON)

    def tearDown(self):
        self.dataset.close()

    def test_depositional_returns_valid_result(self):
        """compute_depositional_safety must not return an error dict."""
        result = compute_depositional_safety(
            self.parcel_geom, self.dataset, search_buffer_meters=1000
        )

        self.assertNotIn("error", result, msg=f"Unexpected error: {result}")
        self.assertIn("metrics", result)
        self.assertIn("assessment", result)

    def test_depositional_status_is_prone(self):
        """Bukidnon parcel is inside the runout zone — must be PRONE."""
        result = compute_depositional_safety(
            self.parcel_geom, self.dataset, search_buffer_meters=1000
        )

        status = result["assessment"]["status"]
        self.assertIn(
            "PRONE",
            status,
            msg=f"Expected PRONE status for within-runout parcel, got {status!r}",
        )

    def test_depositional_metrics_ground_truth(self):
        """Recorded metric values must match the extracted tile."""
        result = compute_depositional_safety(
            self.parcel_geom, self.dataset, search_buffer_meters=1000
        )

        m = result["metrics"]
        self.assertAlmostEqual(m["elevation_peak"], 2587.0, places=0)
        self.assertAlmostEqual(m["elevation_site"], 2427.0, places=0)
        self.assertAlmostEqual(m["delta_e"], 160.0, places=0)
        self.assertAlmostEqual(m["required_runout_3x"], 480.0, places=0)
        print(
            f"\nDepositional: peak={m['elevation_peak']:.1f}m  "
            f"site={m['elevation_site']:.1f}m  "
            f"delta_e={m['delta_e']:.1f}m  "
            f"h={m['horizontal_distance_h']:.6f}  "
            f"runout={m['required_runout_3x']:.1f}m  "
            f"status={result['assessment']['status']}"
        )


@pytest.mark.integration
class TestIntegrationOrchestrator(unittest.TestCase):
    """Full pipeline exercised via EILOrchestrator with SmartFetcher patched."""

    def test_full_pipeline_overall_status(self):
        """overall_status must be one of the three valid Phase 1 outcomes."""
        from unittest.mock import patch
        import smart_fetcher

        payload = {
            "project_id": "integration-test-001",
            "geometry": _PARCEL_GEOJSON,
            "config": {"mode": "compliance"},
        }

        with patch.object(
            smart_fetcher.SmartFetcher,
            "fetch_dem_path",
            return_value=(IFSAR_TILE, "ifsar"),
        ):
            orc = EILOrchestrator()
            result = orc.run_assessment(payload)

        valid_statuses = {
            "CERTIFIED SAFE",
            "NOT CERTIFIED",
            "MANUAL REVIEW REQUIRED",
        }
        overall = result["phase_1_compliance"]["overall_status"]
        self.assertIn(
            overall,
            valid_statuses,
            msg=f"Unexpected overall_status: {overall!r}",
        )

    def test_full_pipeline_data_source_is_ifsar(self):
        """data_source must be 'ifsar' when SmartFetcher is patched."""
        from unittest.mock import patch
        import smart_fetcher

        payload = {
            "project_id": "integration-test-002",
            "geometry": _PARCEL_GEOJSON,
            "config": {"mode": "compliance"},
        }

        with patch.object(
            smart_fetcher.SmartFetcher,
            "fetch_dem_path",
            return_value=(IFSAR_TILE, "ifsar"),
        ):
            orc = EILOrchestrator()
            result = orc.run_assessment(payload)

        self.assertEqual(result["data_source"], "ifsar")

    def test_full_pipeline_not_certified(self):
        """Steep Bukidnon parcel must produce NOT CERTIFIED."""
        from unittest.mock import patch
        import smart_fetcher

        payload = {
            "project_id": "integration-test-003",
            "geometry": _PARCEL_GEOJSON,
            "config": {"mode": "compliance"},
        }

        with patch.object(
            smart_fetcher.SmartFetcher,
            "fetch_dem_path",
            return_value=(IFSAR_TILE, "ifsar"),
        ):
            orc = EILOrchestrator()
            result = orc.run_assessment(payload)

        overall = result["phase_1_compliance"]["overall_status"]
        self.assertEqual(
            overall,
            "NOT CERTIFIED",
            msg=f"Steep terrain must be NOT CERTIFIED, got {overall!r}",
        )
        print(f"\nIntegration result: {overall}")


if __name__ == "__main__":
    unittest.main()
