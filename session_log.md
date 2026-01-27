# Session Log: EIL-Calc Implementation

**Date:** 2026-01-28
**Repository:** `/home/finch/repos/hasadmin/packages/eil-calc/`
**Remote:** `https://github.com/alfieprojectsdev/eil-calc.git`

## Manifest of Created Files

| File | Absolute Path | Description |
| :--- | :--- | :--- |
| `tech-spec_ADR.md` | `/home/finch/repos/hasadmin/packages/eil-calc/tech-spec_ADR.md` | Original Specs and ADRs. |
| `orchestrator.py` | `/home/finch/repos/hasadmin/packages/eil-calc/orchestrator.py` | Main pipeline controller. |
| `slope_stability.py` | `/home/finch/repos/hasadmin/packages/eil-calc/slope_stability.py` | Logic for slope angle checks. |
| `calculate_depositional_safety.py` | `/home/finch/repos/hasadmin/packages/eil-calc/calculate_depositional_safety.py` | Logic for runout distance checks. |
| `smart_fetcher.py` | `/home/finch/repos/hasadmin/packages/eil-calc/smart_fetcher.py` | Data abstraction layer. |
| `hybrid_engine.py` | `/home/finch/repos/hasadmin/packages/eil-calc/hybrid_engine.py` | Structural stub for research mode. |
| `test_orchestrator.py` | `/home/finch/repos/hasadmin/packages/eil-calc/test_orchestrator.py` | Pipeline integration tests. |
| `test_eil_calc.py` | `/home/finch/repos/hasadmin/packages/eil-calc/test_eil_calc.py` | Math/Logic verification tests. |
| `pyproject.toml` | `/home/finch/repos/hasadmin/packages/eil-calc/pyproject.toml` | Project configuration (uv). |
| `README.md` | `/home/finch/repos/hasadmin/packages/eil-calc/README.md` | Project documentation. |

## Key Implementation Snippets

### 1. Orchestrator Pipeline (`orchestrator.py`)
Lines 10-45:
```python
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
        dep_res = calculate_depositional_safety(payload, dem_path)
        results["phase_1_compliance"]["depositional_hazard"] = dep_res
```

### 2. Slope Stability Logic (`slope_stability.py`)
Lines 63-71:
```python
        # Classification
        # Using Max Slope as conservative metric
        if max_slope > 15.0:
            status = "SUSCEPTIBLE"
        elif max_slope > 5.0:
            status = "FLAG FOR REVIEW"
        else:
            status = "SAFE"
```

### 3. Depositional Safety Logic (`calculate_depositional_safety.py`)
Lines 75-82:
```python
        # The Threshold
        required_runout = 3 * delta_e
        
        if h_distance > required_runout:
            status = "SAFE (Beyond Runout)"
            is_safe = True
        else:
            status = "PRONE (Within Runout Zone)"
            is_safe = False
```

### 4. Smart Fetcher Fallback (`smart_fetcher.py`)
Lines 39-40:
```python
        print("Warning: High-res IfSAR not found (Mock). Falling back to global SRTM.")
        return "mock_srtm_30m.tif", "srtm_30m_fallback"
```

## Verification Log

**Tool Used:** `uv`
**Commands:**
- `uv run python -m unittest test_orchestrator.py` -> **PASS**
- `uv run python -m unittest test_eil_calc.py` -> **PASS**

All modules verified with real dependencies (numpy/rasterio/shapely).
