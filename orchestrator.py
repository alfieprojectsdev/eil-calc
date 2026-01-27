from smart_fetcher import SmartFetcher
from slope_stability import calculate_slope_stability
from calculate_depositional_safety import calculate_depositional_safety
from hybrid_engine import run_hybrid_model
import json

class EILOrchestrator:
    def __init__(self):
        self.fetcher = SmartFetcher()

    def run_assessment(self, payload):
        """
        Main pipeline entry point.
        """
        results = {
            "project_id": payload.get("project_id"),
            "phase_1_compliance": {},
            "phase_2_scientific": None,
            "final_decision": "PENDING"
        }
        
        # 1. Fetch Data
        dem_path, dem_type = self.fetcher.fetch_dem_path(payload.get('geometry'))
        results["data_source"] = dem_type
        
        # 2. Phase 1: Compliance
        # Module A: Slope
        slope_res = calculate_slope_stability(payload, dem_path)
        results["phase_1_compliance"]["slope_stability"] = slope_res
        
        # Module B: Depositional
        # Note: calculate_depositional_safety expects different arg order or dict?
        # Let's check signature: calculate_depositional_safety(parcel_geojson, dem_path, search_buffer_meters)
        dep_res = calculate_depositional_safety(payload, dem_path)
        results["phase_1_compliance"]["depositional_hazard"] = dep_res
        
        # Logic for Overall Phase 1 Status
        # If ANY is SUSCEPTIBLE/PRONE -> FAIL
        # If ANY is REVIEW -> REVIEW
        # Else SAFE
        
        s_status = slope_res.get("assessment", {}).get("status", "UNKNOWN")
        d_status = dep_res.get("assessment", {}).get("status", "UNKNOWN")
        
        if "SUSCEPTIBLE" in s_status or "PRONE" in d_status:
            p1_status = "NOT CERTIFIED"
        elif "REVIEW" in s_status:
            p1_status = "MANUAL REVIEW REQUIRED"
        else:
            p1_status = "CERTIFIED SAFE"
            
        results["phase_1_compliance"]["overall_status"] = p1_status
        
        # 3. Phase 2: Scientific (Optional)
        if payload.get("config", {}).get("mode") == "research":
            results["phase_2_scientific"] = run_hybrid_model(payload, dem_path)
            
        return results

if __name__ == "__main__":
    # Test Run
    mock_payload = {
        "project_id": "test-001",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[121.0, 14.5], [121.01, 14.5], [121.01, 14.51], [121.0, 14.51], [121.0, 14.5]]]
        },
        "config": {
            "mode": "compliance"
        }
    }
    orc = EILOrchestrator()
    print(json.dumps(orc.run_assessment(mock_payload), indent=2))
