# EIL-Calc: Earthquake-Induced Landslide Calculator

EIL-Calc is a headless Python geoprocessing engine that automates Earthquake-Induced Landslide (EIL) hazard certification for land parcels. It accepts a GeoJSON polygon, resolves the best available DEM (IfSAR 5m or SRTM 30m), and runs two Phase 1 topography-aware compliance algorithms — geomorphological slope stability and steepest-descent depositional runout — producing a structured JSON verdict.

## Installation

Requires Python 3.11+. Uses `uv` for dependency management.

```bash
uv sync
```

The `eil-calc` console script is registered automatically after `uv sync`.

> **Drive dependency:** Live runs require the `Backup Plus` external drive. Unit tests and integration tests using the bundled fixture do not.

## Data requirements

The `SmartFetcher` resolves DEMs in priority order:

| Priority | Source | Subpath on drive |
|---|---|---|
| 1 | IfSAR 5m (preferred) | `eil-calc/IfSAR/IfSAR_PH.tif` |
| 2 | SRTM 30m (fallback) | `eil-calc/SRTM/SRTM30m.tif` |

Both are single nationwide GeoTIFFs covering the Philippines. Mount point is detected automatically:

- **Linux:** scans `/run/media/<user>/Backup Plus/` and `/media/Backup Plus/`. Mount roots that are not readable (e.g. another user's root-owned `/run/media/root`) are skipped rather than aborting the scan.
- **Windows:** scans all drive letters (A–Z) for the `eil-calc/` subpath

Override paths via environment variables if the drive is mounted elsewhere:

```bash
export IFSAR_PATH=/mnt/data/IfSAR_PH.tif
export SRTM_PATH=/mnt/data/SRTM30m.tif
```

If neither file is accessible, the engine raises `FileNotFoundError` with the expected paths.

## Running the API server

**Linux / macOS:**
```bash
uv run uvicorn api:app --host 127.0.0.1 --port 8000 --reload
```

**Windows:**
```bat
start.bat
```
`start.bat` sets up the environment and launches uvicorn. Edit it to add `IFSAR_PATH`/`SRTM_PATH` overrides if the drive is on a non-standard letter.

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
      "metrics": {
        "max_slope_degrees": 12.4,
        "avg_slope_degrees": 8.1,
        "pct_susceptible": 0.008,
        "pct_flag": 0.031
      },
      "assessment": { "status": "SAFE", "threshold_used": "coverage_fraction" },
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
      "_viz_transects": [
        {
          "metrics": { "threat_ratio": 0.82 },
          "assessment": "SAFE (Beyond Runout)",
          "path": [
            {"dist_m": 0.0, "elev_m": 480.0},
            {"dist_m": 620.0, "elev_m": 310.0}
          ]
        }
      ]
    },
    "overall_status": "CERTIFIED SAFE"
  },
  "phase_2_scientific": null,
  "final_decision": "PENDING"
}
```

`overall_status` is one of `CERTIFIED SAFE`, `MANUAL REVIEW REQUIRED`, or `NOT CERTIFIED`.

### Slope stability thresholds

The decision uses **coverage fraction** over the parcel's watershed slope units, not a single max-slope threshold:

| Condition | Status |
|---|---|
| `pct_susceptible > 1.5%` | SUSCEPTIBLE |
| `pct_flag > 10%` (and not susceptible) | FLAG FOR REVIEW |
| Otherwise | SAFE |

where pixels are classified as susceptible (> 16°) or flag (14–16°) before computing the fraction. The degree thresholds and status enum are centralised in `eil_status.py` (`SLOPE_THRESHOLD_FLAG = 14.0`, `SLOPE_THRESHOLD_SUSCEPTIBLE = 16.0`).

### Depositional check

A parcel is `PRONE (Within Runout Zone)` if the steepest-descent horizontal distance `H < 3 × ΔE` (elevation drop from peak to site). Paths shorter than 30 m are discarded as sub-pixel noise. The top-3 highest-threat paths are returned in `_viz_transects`; `overall_status` reflects the worst-case path.

## How the logic works (plain-language guide for reviewers)

This section is for hazard assessors reviewing the *reasoning*, not the code. Each plain-language step is mapped to the exact source file and function so a developer can confirm the implementation matches the intent. Line numbers are approximate and may drift as the code evolves — the function names are the stable reference.

The engine answers **two independent questions** about a parcel, then combines them:

### Question 1 — "Is the ground inside the lot too steep?" (slope stability)

| # | What it does, in plain terms | Where in code |
|---|---|---|
| 1 | Take the lot outline and a 500 m collar around it, and cut that patch out of the elevation map (DEM). The collar exists so slope near the lot's edge is measured against real neighbouring ground, not the empty map border. | `slope_stability.py` → `compute_slope_stability()`, buffer + crop |
| 2 | Smooth the elevation map slightly to remove data spikes/noise, so a single bad pixel can't fake a cliff. | Gaussian smoothing block (`sigma = 2.0`, ≈ 30 m smoothing on 5 m IfSAR) |
| 3 | Compute the slope angle (in degrees) at every pixel. | `np.gradient` → `slope_degrees` |
| 4 | Divide the surrounding terrain into natural drainage basins (the way ridgelines separate one hillside catchment from the next) and keep only the basins the lot actually sits in. This stops a far-off mountain from being blamed for the lot. | "Dynamic Slope Unit" / watershed block |
| 5 | Inside those relevant basins **and** inside the lot boundary, measure what fraction of the ground is steep: `> 16°` = *susceptible*, `14–16°` = *flag for review*. | coverage-fraction calculation (`pct_susceptible`, `pct_flag`) |
| 6 | Decide: more than **1.5%** of the lot susceptible → **SUSCEPTIBLE**; else more than **10%** in the flag band → **FLAG FOR REVIEW**; otherwise **SAFE**. | final `if`/`elif`/`else` block; thresholds in `eil_status.py` |

*Why fractions instead of the single steepest point:* one isolated steep pixel (often a data artefact at 5 m resolution) should not condemn an otherwise flat lot. Using coverage mirrors PHIVOLCS' own "Largely / Partly" qualifier language.

### Question 2 — "Could a landslide from higher ground reach the lot?" (depositional runout)

| # | What it does, in plain terms | Where in code |
|---|---|---|
| 1 | Find the **lowest point inside the lot** — treat it as where debris would arrive. | `calculate_depositional_safety.py` → `compute_depositional_safety()`, STEP A |
| 2 | Look up to ~1 km around the lot and find the **highest peak** that could be a landslide source. | STEP B (vicinity buffer + peak search) |
| 3 | Walk downhill from that peak, always following the steepest descent, until the path reaches the lot. Measure the **drop in height (ΔE)** and the **horizontal travel distance (H)** along that path. | uphill-walker / downhill-stepper routine |
| 4 | Apply the runout rule: landslide debris is assumed able to travel up to **3× its fall height**. If the lot is *farther* than that (`H > 3 × ΔE`) it is **SAFE (Beyond Runout)**; if *closer* (`H < 3 × ΔE`) it is **PRONE (Within Runout Zone)**. | `required_runout = 3.0 * delta_e`; `is_compliant = h_distance > required_runout` |
| 5 | Ignore any path shorter than **30 m** (too short to be a real slide at this map resolution), keep the **3 most threatening** source paths, and let the **worst one** decide the parcel's status. | `_MIN_RUNOUT_METRES`; top-3 sort; worst-case aggregation |

*The "3× fall height" rule* is a standard landslide reach approximation (a travel/reach angle of roughly 18°): the steeper and higher the source, the farther debris can run out.

### Putting it together

The orchestrator (`orchestrator.py`) runs both questions on the same parcel and the status enums in `eil_status.py` combine them into the single `overall_status` shown in the output: **CERTIFIED SAFE**, **MANUAL REVIEW REQUIRED**, or **NOT CERTIFIED**. A reviewer disagreeing with any single step above can point to its row and the named function — that is the line that would change.

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

**Ground truth harness** (requires drive + ArcGIS Portal credentials):

```bash
uv run python test_ground_truth.py
```

Accuracy on the current ground truth set: ~90% (24 TP, 21 TN, 3 FP, 2 FN out of 50 parcels).

## Project structure

```
eil-calc/
├── api.py                          # FastAPI POST /api/v1/assess
├── cli.py                          # Argparse entry point (eil-calc script)
├── orchestrator.py                 # Pipeline coordinator (EILOrchestrator)
├── eil_types.py                    # TypedDicts + DEMContext dataclass
├── eil_status.py                   # Slope/depositional status enums + degree thresholds
├── smart_fetcher.py                # DEM resolution: IfSAR → SRTM (cross-platform)
├── slope_stability.py              # Gradient analysis + Dynamic Slope Units (SUs)
├── calculate_depositional_safety.py # Topographic runout check (Steepest-descent H > 3 × ΔE)
├── hybrid_engine.py                # Phase 2 stub (not implemented)
├── test_eil_calc.py                # Unit tests: depositional + slope logic
├── test_orchestrator.py            # Unit tests: orchestrator wiring (mocked)
├── test_integration.py             # Integration tests: real IfSAR tile
├── test_ground_truth.py            # Ground truth accuracy harness
├── generate_mock_parcels.py        # ArcGIS parcel factory for ground truth set
├── test_fixtures/
│   └── ifsar_tile.tif             # Extracted IfSAR tile (Bukidnon, Mindanao)
├── start.bat                       # Windows startup script
├── pyproject.toml
└── RFC_001-EIL-CALC.md            # Technical spec and ADRs
```

## Architecture notes

EIL-Calc follows a **Pipe-and-Filter** architecture. The `EILOrchestrator` coordinates the pipeline: fetch DEM → reproject geometry → build `DEMContext` → run Phase 1 modules → aggregate verdict. CRS reprojection is centralised in the orchestrator; downstream modules receive a `DEMContext` with a geometry already in the DEM's native CRS.

**Phase 1** uses physical "zeroth-order" algorithms built natively on topological math: Scipy/skimage Gaussian smoothing and watershed segmentation for slope unit delineation, and steepest-descent path routing for depositional runout metrics.

**Phase 2** (Landlab physically-based modelling + XGBoost hybrid engine) is planned but deferred. `hybrid_engine.py` is a non-functional stub.

## Known limitations

- **`final_decision` always `"PENDING"`** — `hybrid_engine.py` is a stub. Phase 1 `overall_status` is the operative result.
- **3 FP / 2 FN in ground truth** — Remaining errors require regional geologic data beyond the DEM (debris-flow channels, engineered fill, volcanic lahars). The 30 m minimum-runout filter and 1.5% coverage threshold were tuned on the current 50-parcel set and may need adjustment as the ground truth set grows.
- **Ground truth harness is observation-only** — `test_ground_truth.py` prints a confusion matrix but has no per-parcel `assert` statements. Regressions won't fail CI automatically.
- **`SmartFetcher` has no unit tests** — The fallback chain (config → env var → drive scan) and `validate_resolution()` are untested.
- **API error responses are untyped** — The `POST /api/v1/assess` error path returns `Dict[str, Any]`; there is no Pydantic response model for 4xx/5xx.
- **`test_orchestrator.py` patch path** — The test patches `calculate_slope_stability` but the module's internal function is `compute_slope_stability`; the patch may silently no-op.
- **Geographic buffer asymmetry** — Slope engine uses a latitude-only buffer (`500/111320` deg); depositional engine applies the correct `cos(lat)` correction. ~5% east-west error at 18°N.

## License

Proprietary / Internal Use Only.
