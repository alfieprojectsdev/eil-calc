import json

import rasterio
from rasterio.crs import CRS
from rasterio.warp import transform_geom
from shapely.geometry import mapping, shape

from calculate_depositional_safety import calculate_depositional_safety
from eil_types import DEMContext
from hybrid_engine import run_hybrid_model
from slope_stability import calculate_slope_stability
from smart_fetcher import SmartFetcher


class EILOrchestrator:
    def __init__(self):
        self.fetcher = SmartFetcher()

    def run_assessment(self, payload):
        """Main pipeline entry point."""
        results = {
            "project_id": payload.get("project_id"),
            "phase_1_compliance": {},
            "phase_2_scientific": None,
            "final_decision": "PENDING",
        }

        # 1. Fetch DEM path
        dem_path, dem_type = self.fetcher.fetch_dem_path(payload.get("geometry"))
        results["data_source"] = dem_type

        with rasterio.open(dem_path) as dataset:
            # 2. Reproject geometry once — all modules receive projected geometry.
            wgs84 = CRS.from_epsg(4326)
            geometry = shape(payload["geometry"])
            if dataset.crs != wgs84:
                geometry = shape(
                    transform_geom(wgs84, dataset.crs, mapping(geometry))
                )

            # 3. Build shared context
            context = DEMContext(
                dataset=dataset,
                geometry=geometry,
                source_type=dem_type,
            )

            # 4. Phase 1: Compliance
            slope_res = calculate_slope_stability(context)
            dep_res = calculate_depositional_safety(context)

        results["phase_1_compliance"]["slope_stability"] = slope_res
        results["phase_1_compliance"]["depositional_hazard"] = dep_res

        # 5. Overall Phase 1 status
        # .get() chaining is intentional: error dicts {"error": "..."} lack an
        # "assessment" key and should fall through to "UNKNOWN".
        s_status = slope_res.get("assessment", {}).get("status", "UNKNOWN")
        d_status = dep_res.get("assessment", {}).get("status", "UNKNOWN")

        if "SUSCEPTIBLE" in s_status or "PRONE" in d_status:
            p1_status = "NOT CERTIFIED"
        elif "REVIEW" in s_status:
            p1_status = "MANUAL REVIEW REQUIRED"
        else:
            p1_status = "CERTIFIED SAFE"

        results["phase_1_compliance"]["overall_status"] = p1_status

        # 6. Phase 2: Scientific (optional)
        if payload.get("config", {}).get("mode") == "research":
            results["phase_2_scientific"] = run_hybrid_model(payload, dem_path)

        return results


if __name__ == "__main__":
    mock_payload = {
        "project_id": "test-001",
        "geometry": {
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
        },
        "config": {"mode": "compliance"},
    }
    orc = EILOrchestrator()
    print(json.dumps(orc.run_assessment(mock_payload), indent=2))
