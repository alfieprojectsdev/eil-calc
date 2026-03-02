import json
import unittest
from unittest.mock import MagicMock, patch

from orchestrator import EILOrchestrator


# A minimal valid GeoJSON Polygon geometry used across tests.
_GEOMETRY = {
    "type": "Polygon",
    "coordinates": [
        [
            [121.0, 14.5],
            [121.01, 14.5],
            [121.01, 14.51],
            [121.0, 14.51],
            [121.0, 14.5],
        ]
    ],
}


def _make_mock_dataset():
    """Return a mock rasterio dataset whose CRS equals WGS84.

    Setting crs.equals to return True means the reprojection branch in the
    orchestrator is skipped, keeping the mock simple.
    """
    from rasterio.crs import CRS

    mock_ds = MagicMock()
    mock_ds.crs = CRS.from_epsg(4326)
    return mock_ds


class TestEILOrchestrator(unittest.TestCase):

    @patch("orchestrator.rasterio.open")
    @patch("orchestrator.calculate_slope_stability")
    @patch("orchestrator.calculate_depositional_safety")
    @patch("orchestrator.SmartFetcher")
    def test_workflow_safe(self, mock_fetcher_cls, mock_dep, mock_slope, mock_rasterio_open):
        # SmartFetcher mock
        mock_fetcher = mock_fetcher_cls.return_value
        mock_fetcher.fetch_dem_path.return_value = ("dummy.tif", "mock_type")

        # rasterio.open context-manager mock
        mock_ds = _make_mock_dataset()
        mock_rasterio_open.return_value.__enter__ = MagicMock(return_value=mock_ds)
        mock_rasterio_open.return_value.__exit__ = MagicMock(return_value=False)

        # Module mocks
        mock_slope.return_value = {"assessment": {"status": "SAFE"}}
        mock_dep.return_value = {"assessment": {"status": "SAFE (Beyond Runout)"}}

        payload = {
            "project_id": "test-safe",
            "geometry": _GEOMETRY,
            "config": {"mode": "compliance"},
        }

        orc = EILOrchestrator()
        result = orc.run_assessment(payload)

        self.assertEqual(result["phase_1_compliance"]["overall_status"], "CERTIFIED SAFE")
        self.assertEqual(result["data_source"], "mock_type")

    @patch("orchestrator.rasterio.open")
    @patch("orchestrator.calculate_slope_stability")
    @patch("orchestrator.calculate_depositional_safety")
    @patch("orchestrator.SmartFetcher")
    def test_workflow_unsafe(self, mock_fetcher_cls, mock_dep, mock_slope, mock_rasterio_open):
        # SmartFetcher mock
        mock_fetcher = mock_fetcher_cls.return_value
        mock_fetcher.fetch_dem_path.return_value = ("dummy.tif", "mock_type")

        # rasterio.open context-manager mock
        mock_ds = _make_mock_dataset()
        mock_rasterio_open.return_value.__enter__ = MagicMock(return_value=mock_ds)
        mock_rasterio_open.return_value.__exit__ = MagicMock(return_value=False)

        # Module mocks
        mock_slope.return_value = {"assessment": {"status": "SUSCEPTIBLE"}}
        mock_dep.return_value = {"assessment": {"status": "SAFE (Beyond Runout)"}}

        payload = {
            "project_id": "test-unsafe",
            "geometry": _GEOMETRY,
            "config": {"mode": "compliance"},
        }

        orc = EILOrchestrator()
        result = orc.run_assessment(payload)

        self.assertEqual(result["phase_1_compliance"]["overall_status"], "NOT CERTIFIED")


class TestCLI(unittest.TestCase):

    @patch('cli.EILOrchestrator')
    def test_cli_stdout(self, mock_orc_cls):
        import tempfile
        import os
        import io
        from contextlib import redirect_stdout

        mock_orc = mock_orc_cls.return_value
        mock_orc.run_assessment.return_value = {"project_id": "test", "result": "ok"}

        # Write a temp GeoJSON file
        geojson = {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [121.0, 14.5],
                        [121.1, 14.5],
                        [121.1, 14.6],
                        [121.0, 14.6],
                        [121.0, 14.5],
                    ]
                ],
            },
        }
        with tempfile.NamedTemporaryFile(mode='w', suffix='.geojson', delete=False) as f:
            json.dump(geojson, f)
            tmp_path = f.name

        try:
            from cli import main
            buf = io.StringIO()
            with redirect_stdout(buf):
                with self.assertRaises(SystemExit) as cm:
                    main(["--geojson", tmp_path, "--project-id", "test"])
            self.assertEqual(cm.exception.code, 0)
            output = json.loads(buf.getvalue())
            self.assertEqual(output["project_id"], "test")
        finally:
            os.unlink(tmp_path)


if __name__ == "__main__":
    unittest.main()
