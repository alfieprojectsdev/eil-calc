import unittest
from unittest.mock import MagicMock, patch
# Removed sys.modules hacks for rasterio/numpy
from orchestrator import EILOrchestrator

class TestEILOrchestrator(unittest.TestCase):
    
    @patch('orchestrator.calculate_slope_stability')
    @patch('orchestrator.calculate_depositional_safety')
    @patch('orchestrator.SmartFetcher')
    def test_workflow_safe(self, mock_fetcher_cls, mock_dep, mock_slope):
        # Setup Mocks
        mock_fetcher = mock_fetcher_cls.return_value
        mock_fetcher.fetch_dem_path.return_value = ("dummy.tif", "mock_type")
        
        mock_slope.return_value = {
            "assessment": {"status": "SAFE"}
        }
        mock_dep.return_value = {
            "assessment": {"status": "SAFE (Beyond Runout)"}
        }
        
        # Payload
        payload = {
            "project_id": "test-safe",
            "geometry": {"type": "Polygon", "coordinates": []},
            "config": {"mode": "compliance"}
        }
        
        # Execute
        orc = EILOrchestrator()
        result = orc.run_assessment(payload)
        
        # Verify
        self.assertEqual(result['phase_1_compliance']['overall_status'], "CERTIFIED SAFE")
        self.assertEqual(result['data_source'], "mock_type")

    @patch('orchestrator.calculate_slope_stability')
    @patch('orchestrator.calculate_depositional_safety')
    @patch('orchestrator.SmartFetcher')
    def test_workflow_unsafe(self, mock_fetcher_cls, mock_dep, mock_slope):
        # Setup Mocks
        mock_fetcher = mock_fetcher_cls.return_value
        mock_fetcher.fetch_dem_path.return_value = ("dummy.tif", "mock_type")
        
        mock_slope.return_value = {
            "assessment": {"status": "SUSCEPTIBLE"}
        }
        mock_dep.return_value = {
            "assessment": {"status": "SAFE"}
        }
        
        # Payload
        payload = {
            "project_id": "test-unsafe",
            "geometry": {},
            "config": {"mode": "compliance"}
        }
        
        orc = EILOrchestrator()
        result = orc.run_assessment(payload)
        
        self.assertEqual(result['phase_1_compliance']['overall_status'], "NOT CERTIFIED")

if __name__ == '__main__':
    unittest.main()
