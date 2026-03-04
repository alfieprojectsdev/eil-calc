# EIL-Calc: Earthquake-Induced Landslide Calculator

EIL-Calc is a headless Python geoprocessing engine that automates Earthquake-Induced Landslide (EIL) hazard certification for land parcels. It accepts a GeoJSON polygon, resolves the best available DEM (IfSAR 5m or SRTM 30m), and runs two Phase 1 topography-aware compliance algorithms — geomorphological slope stability and steepest-descent depositional runout — producing a structured JSON verdict.

## Installation

Requires Python 3.11+. Uses `uv` for dependency management.

```bash
uv sync
```

The `eil-calc` console script is registered automatically after `uv sync`.

> **Drive dependency:** Live runs require the `Backup Plus` external drive mounted at `/run/media/finch/Backup Plus/`. Unit tests and integration tests using the bundled fixture do not.

## Data requirements

The `SmartFetcher` resolves DEMs in priority order:

| Priority | Source | Path on drive |
|---|---|---|
| 1 | IfSAR 5m (preferred) | `Backup Plus/eil-calc/IfSAR/IfSAR_PH.tif` |
| 2 | SRTM 30m (fallback) | `Backup Plus/eil-calc/SRTM/SRTM30m.tif` |

Both are single nationwide GeoTIFFs covering the Philippines. If neither file is accessible, the engine raises `FileNotFoundError` with the expected paths.

## CLI usage

```
eil-calc --geojson <path> --project-id <id> [--mode compliance|research] [--output <path>]
```

The `--geojson` file must be a GeoJSON Feature or bare Polygon geometry in WGS84. `--output` defaults to stdout.

```bash
eil-calc --geojson parcel.geojson --project-id LOT-2024-001 --mode compliance
```

## Output format

```json
{
  "project_id": "LOT-2024-001",
  "data_source": "ifsar",
  "phase_1_compliance": {
    "slope_stability": {
      "metrics": { "max_slope_degrees": 12.4, "avg_slope_degrees": 8.1 },
      "assessment": { "status": "FLAG FOR REVIEW", "threshold_used": "10–15°" },
      "_viz_grid": [
        [null, 6.2, 8.4],
        [null, null, 12.4]
      ]
    },
    "depositional_hazard": {
      "metrics": {
        "elevation_peak": 480.0,
        "elevation_site": 310.0,
        "delta_e": 170.0,
        "horizontal_distance_h": 620.0,
        "required_runout_3x": 510.0
      },
      "assessment": { "status": "SAFE (Beyond Runout)", "is_compliant": true },
      "_viz_transect": [
        {"dist_m": 0.0, "elev_m": 480.0},
        {"dist_m": 620.0, "elev_m": 310.0}
      ]
    },
    "overall_status": "MANUAL REVIEW REQUIRED"
  },
  "phase_2_scientific": null,
  "final_decision": "PENDING"
}
```

`overall_status` is one of `CERTIFIED SAFE`, `MANUAL REVIEW REQUIRED`, or `NOT CERTIFIED`.

Slope status thresholds: `SAFE` (< 10°), `FLAG FOR REVIEW` (10–15°), `SUSCEPTIBLE` (≥ 15°).

Depositional check: the parcel is `PRONE (Within Runout Zone)` if `H < 3 × ΔE`.

## Running tests

**Unit tests** (no drive required):

```bash
uv run python -m unittest test_eil_calc test_orchestrator -v
```

**Integration tests** (require `test_fixtures/ifsar_tile.tif`):

```bash
uv run python -m pytest test_integration.py -v
```

The fixture is a 30 m × 30 m IfSAR tile from the Bukidnon highlands, Mindanao. If it is missing the tests skip automatically.

**Manual smoke test** (requires `Backup Plus` drive):

```bash
uv run python orchestrator.py
```

## Project structure

```
eil-calc/
├── cli.py                          # Argparse entry point (eil-calc script)
├── orchestrator.py                 # Pipeline coordinator (EILOrchestrator)
├── eil_types.py                    # TypedDicts + DEMContext dataclass
├── smart_fetcher.py                # DEM resolution: IfSAR → SRTM
├── slope_stability.py              # Gradient analysis + Dynamic Slope Units (SUs)
├── calculate_depositional_safety.py # Topographic runout check (Steepest-descent H > 3 × ΔE)
├── hybrid_engine.py                # Phase 2 stub (Landlab + XGBoost)
├── test_eil_calc.py                # Unit tests: depositional + slope logic
├── test_orchestrator.py            # Unit tests: orchestrator wiring (mocked)
├── test_integration.py             # Integration tests: real IfSAR tile
├── test_fixtures/
│   └── ifsar_tile.tif             # Extracted IfSAR tile (Bukidnon, Mindanao)
├── pyproject.toml
└── RFC_001-EIL-CALC.md            # Technical spec and ADRs
```

## Architecture notes

EIL-Calc follows a **Pipe-and-Filter** architecture. The `EILOrchestrator` coordinates the pipeline: fetch DEM → reproject geometry → build `DEMContext` → run Phase 1 modules → aggregate verdict. CRS reprojection is centralised in the orchestrator; downstream modules receive a `DEMContext` with a geometry already in the DEM's native CRS.

Currently, **Phase 1** uses physical "zeroth-order" algorithms built natively on topological math (e.g. Scipy spatial smoothing for 5m micro-resolutions, `skimage` watershed segmentations for natural geomorphological Slope Units, and steepest-descent path routing for runout metrics).

**Phase 2** (Landlab physically-based modelling + XGBoost hybrid engine) is planned but deferred. `hybrid_engine.py` is a non-functional stub.

## License

Proprietary / Internal Use Only.
