# EIL-Calc Session Log — 2026-03-02

## Session Overview

Resumed work on the EIL-Calc geoprocessing engine after a gap. Session covered a
project status review, one targeted bug fix, and slope stability unit tests.

---

## 1. Project Status Review

Reviewed all existing files to establish current state:

| File | Status |
|---|---|
| `slope_stability.py` | Complete — zonal gradient analysis, 3-tier threshold |
| `calculate_depositional_safety.py` | Complete — geometric runout check (`H > 3 * ΔE`) |
| `smart_fetcher.py` | Stub — local IfSAR path hardcoded, SRTM URL is placeholder |
| `orchestrator.py` | Complete — pipes all modules, produces `phase_1_compliance` result |
| `hybrid_engine.py` | Stub — Phase 2 not yet implemented, returns mock data |
| `test_eil_calc.py` | Tests depositional safety logic only |
| `test_orchestrator.py` | Tests orchestrator wiring with mocks |

**Identified gaps (not yet addressed):**
- ~~No unit tests for `slope_stability.py`~~ — resolved this session
- `SmartFetcher` real tile-lookup logic not implemented
- Phase 2 (Landlab / XGBoost) is a stub
- No CLI / HTTP API entry point

**DEM data documentation gap:** The README and RFC describe the priority logic
(IfSAR → SRTM) but give no concrete guidance on sourcing either dataset.
`smart_fetcher.py` uses a hardcoded `/data/ifsar/philippines/` path and a
placeholder `example.com` SRTM URL. RFC §3 ("Data Requirements") flags the PEM
GeoTIFF access as an open question pending internal coordination with the
Seismology Division. No further action taken this session — deferred until
data access is resolved.

---

## 2. Fix: CRS Handling Gap

**Commit `a5daff4`**

### Problem

GeoJSON inputs are always WGS84 (RFC 7946 mandate). IfSAR DEMs are in a projected
CRS (typically UTM, e.g. EPSG:32651). Both processing modules were using the raw
input polygon directly against the DEM without reprojection:

- **`calculate_depositional_safety.py`:** `site_polygon.buffer(search_buffer_meters)`
  was buffering in degrees, not metres — `buffer(1000)` in WGS84 would create a
  ~111,000 km radius, pulling in the entire planet as the "vicinity."
- **`slope_stability.py`:** `np.gradient(elevation_data, py, px)` uses `src.res`
  (pixel size in DEM native units). If the polygon masking produced nonsense results
  due to CRS mismatch, the slope values would be meaningless.

### Fix

Added conditional reprojection in both modules using `rasterio.warp.transform_geom`
and `rasterio.crs.CRS`. The polygon is reprojected from WGS84 to the DEM's native
CRS at the start of each function, inside the `rasterio.open` context (where
`src.crs` is available):

```python
wgs84 = CRS.from_epsg(4326)
if not src.crs.equals(wgs84):
    site_polygon = shape(transform_geom(wgs84, src.crs, mapping(site_polygon)))
```

No new dependency — `rasterio.warp` and `rasterio.crs` are already part of
rasterio.

### Tests

All 4 existing tests pass after the fix:
- `test_eil_calc`: 2/2 (safe + unsafe depositional scenarios)
- `test_orchestrator`: 2/2 (workflow safe + unsafe)

---

---

## 3. Slope Stability Unit Tests

**Commit `1a6e4db`**

Added `TestSlopeStability` class and `calculate_slope_logic` helper to
`test_eil_calc.py`, following the same in-memory `MemoryFile` pattern used by the
existing depositional tests.

### Design

Synthetic DEMs use a uniform X-direction gradient: `data[:, x] = x * tan(θ) * res`.
For a linear slope, `np.gradient` returns the exact same value at edges and interior
(forward/backward differences agree with central differences), so `max_slope`
round-trips to exactly the target angle with no floating-point variance.

### Tests added

| Test | Target slope | Expected status |
|---|---|---|
| `test_safe_slope` | 10° | `SAFE` |
| `test_review_slope` | 15° | `FLAG FOR REVIEW` |
| `test_susceptible_slope` | 20° | `SUSCEPTIBLE` |
| `test_all_nodata_parcel` | n/a (all nodata) | `{"error": ...}` |

### Result

All 6 tests pass (4 new + 2 existing depositional):

```
Ran 6 tests in 0.058s  OK
--- SAFE slope ---          max=10.00°
--- FLAG FOR REVIEW slope — max=15.00°
--- SUSCEPTIBLE slope ---   max=20.00°
--- nodata parcel ---       result={'error': 'No valid data in parcel'}
```

---

## Commit History

| Hash | Message |
|---|---|
| `a5daff4` | Fix CRS handling: reproject WGS84 input polygon to DEM CRS before processing |
| `1a6e4db` | Add slope stability unit tests covering all three threshold tiers |

---

## Pending / Next Session

- `SmartFetcher` real tile-lookup logic (depends on IfSAR file naming/structure)
- DEM data sourcing documentation (depends on internal coordination)
- Phase 2 implementation (Landlab + XGBoost) — deferred
- CLI / API entry point — deferred

---

---

# EIL-Calc Session Log — 2026-03-02 (continued)

## Session Overview

Continuation of the 2026-03-02 session. Covered a coordinate index bug fix, a
structural refactor, housekeeping, a new CLI entry point, and an integration
test suite against a real IfSAR tile fixture.

---

## 1. Fix: Coordinate Index Bug

**Commit `f215d0c`**

### Problem

`calculate_depositional_safety.py` was calling `src.xy(row, col)` using the
rasterio `DatasetReader.xy` method to convert pixel indices to spatial
coordinates. Following the I/O separation refactor, `src` was no longer in scope
at the call site — the function received a pre-opened dataset through
`DEMContext`. The code was also passing the wrong argument ordering: rasterio's
`dataset.xy` is an instance method, while the intended call was the module-level
`rasterio.transform.xy(transform, row, col)` which requires the affine transform
as its first argument.

### Fix

Replaced `src.xy(row, col)` with `rasterio.transform.xy(site_transform, row,
col)` where `site_transform` is the affine transform of the masked window. This
aligns with the separated-I/O design: the computation function receives the
transform explicitly rather than accessing it through a dataset handle.

---

## 2. Structural Refactor

**Commit `bfab5a8`**

### Changes

- **`eil_types.py` introduced:** Centralised output contracts as `TypedDict`
  classes (`SlopeResult`, `DepositionalResult`, etc.) and the `DEMContext`
  dataclass. `DEMContext` holds an open `rasterio.DatasetReader`, the
  pre-reprojected `shapely` geometry, and the DEM source type. The
  `landlab_grid` field is a placeholder for Phase 2.

- **I/O separated from computation:** Both `slope_stability.py` and
  `calculate_depositional_safety.py` now expose two function layers:
  - An inner `compute_*` function that accepts a geometry and an open dataset
    (pure computation, no file I/O — testable without a filesystem).
  - An outer `calculate_*` function that accepts a `DEMContext` and delegates
    to the inner function.

- **CRS reprojection centralised in orchestrator:** `orchestrator.py` now
  reprojects the WGS84 input geometry to the DEM's native CRS once, before
  constructing `DEMContext`. Downstream modules receive projected geometry and
  no longer perform any CRS logic themselves.

### Result

All 6 existing unit tests continue to pass after the refactor.

---

## 3. Housekeeping

**Commit `6812cfb`**

- **Removed `pandas`:** It was listed as a dependency but unused across the
  entire codebase. Removed from `pyproject.toml` and `uv.lock`.
- **Fixed `__main__` payload in `orchestrator.py`:** The smoke-test payload at
  the bottom of the file was using stale field names left over from an earlier
  schema iteration. Updated to match the current `run_assessment` contract
  (`project_id`, `geometry`, `config`).

---

## 4. CLI Entry Point

**Commit `11096b9`**

### Changes

- **`cli.py` added:** Argparse-based CLI wiring `EILOrchestrator.run_assessment`
  to the command line. Arguments: `--geojson` (required), `--project-id`
  (required), `--mode` (`compliance` | `research`, default `compliance`),
  `--output` (optional file path; defaults to stdout).
- **`pyproject.toml` updated:** `[project.scripts]` entry `eil-calc = "cli:main"`
  added so `uv sync` installs the console script.
- The CLI accepts both a bare GeoJSON Polygon geometry and a GeoJSON Feature
  object (extracts `.geometry` automatically).

### Usage

```bash
eil-calc --geojson parcel.geojson --project-id LOT-2024-001
```

---

## 5. Integration Tests with Real IfSAR Tile Fixture

**Commit `cb26239`**

### Fixture

Extracted a 30 m × 30 m IfSAR tile from `IfSAR_PH.tif` covering the Bukidnon
highlands, Mindanao (lon 124.891–124.909, lat 8.091–8.109). Saved as
`test_fixtures/ifsar_tile.tif`. Ground-truth values recorded from the
extraction:

| Metric | Value |
|---|---|
| Elevation range | 1631 m – 2587 m |
| Test parcel | 30 m × 30 m, centred lon=124.894914, lat=8.104633 |
| `elevation_peak` | 2587.0 m |
| `elevation_site` | 2427.0 m |
| `delta_e` | 160.0 m |
| `required_runout_3x` | 480.0 m |
| Overall status | NOT CERTIFIED |

### Test classes added (`test_integration.py`)

| Class | Coverage |
|---|---|
| `TestIntegrationSlope` | `compute_slope_stability` against real tile — valid result, SUSCEPTIBLE status, positive max slope |
| `TestIntegrationDepositional` | `compute_depositional_safety` against real tile — valid result, PRONE status, ground-truth metric values |
| `TestIntegrationOrchestrator` | Full pipeline via `EILOrchestrator` with `SmartFetcher.fetch_dem_path` patched to the fixture — valid `overall_status`, correct `data_source`, NOT CERTIFIED outcome |

Tests are marked `@pytest.mark.integration` and skip automatically if the
fixture file is missing (no drive required in CI).

### Pytest marker

Registered `integration` marker in `pyproject.toml` under
`[tool.pytest.ini_options]` to suppress the unknown-marker warning.

---

## Commit History

| Hash | Message |
|---|---|
| `f215d0c` | Fix coordinate index bug (src.xy → rasterio.transform.xy with site_transform) |
| `bfab5a8` | Structural refactor: eil_types.py, DEMContext, separated I/O from computation, centralized CRS |
| `6812cfb` | Housekeeping: remove pandas, fix __main__ payload |
| `11096b9` | Add CLI entry point (cli.py, argparse, eil-calc script) |
| `cb26239` | Add integration tests with real IfSAR tile fixture |

---

## Pending / Next Session

- Phase 2: Landlab + XGBoost hybrid engine — deferred until research phase begins
- HTTP API — deferred until multi-user or web use case arises

---

---

# EIL-Calc Session Log — 2026-03-04

## Session Overview

Two areas of work: (1) fixed the `max_slope_degrees: 90` bug in `slope_stability.py`
using a buffered geometry approach, and (2) built the Ground Truth validation pipeline
— directory structure, parcel factory, and validation harness.

---

## 1. Fix: `max_slope_degrees: 90` (Gradient-Across-Nodata Bug)

### Root Cause

`np.gradient` computes central differences for interior pixels and forward/backward
differences at edge pixels. When `rasterio.mask.mask` crops the DEM to the parcel
bounding box and sets exterior pixels to nodata, every pixel on the boundary of the
valid parcel mask has a nodata sentinel as a neighbour. For IfSAR, `nodata =
2147483648.0` (INT32_MAX stored as float32). A gradient of ~2.1 × 10⁹ m/pixel → 90°
slope at every boundary pixel → `np.max` always returns 90.

### Fix: Buffered Geometry Approach (`slope_stability.py`)

1. **Buffer the parcel** before masking: `geometry.buffer(60 / 111320.0)` for
   geographic CRS (`EPSG:4326`), `geometry.buffer(60.0)` for projected CRS. The 60 m
   buffer gives ~12 pixels of real terrain context around the parcel on a 5 m IfSAR.
2. **Extract buffered block** with `rasterio.mask.mask(dataset, [buffered_geom], crop=True)`.
   Parcel-edge pixels now have real terrain neighbours, not nodata sentinels.
3. **NaN-out nodata** on the expanded block before gradient: `elevation_data[elevation_data == dataset.nodata] = np.nan`.
   Arithmetic with NaN propagates NaN rather than producing ~90° artefacts.
4. **Compute gradient** on the full buffered block (`np.gradient`).
5. **Restrict to parcel** using `rasterio.features.geometry_mask` with the original
   unbuffered geometry and `out_transform` from step 2.
6. **Strip NaN** from `site_slopes` before `np.nanmax` / `np.nanmean`.

`calculate_slope_stability` (the `DEMContext` entry point) is unchanged — it simply
delegates to the rewritten `compute_slope_stability`.

### Test Results

All 18 tests pass after the fix (9 unit + 9 integration). Real-parcel results:

| Parcel | Old `max_slope` | New `max_slope` | Status |
|---|---|---|---|
| LOT-13929 | 90.0° (artefact) | 45.3° | SUSCEPTIBLE |
| LOT-14936 | 90.0° (artefact) | 30.2° | SUSCEPTIBLE |

---

## 2. Ground Truth Validation Pipeline

### 2a. Directory Structure

Created `tests/ground_truth/{safe,susceptible,prone}/` with `.gitkeep` sentinels.

### 2b. `geopandas` Dev Dependency

Added via `uv add --dev geopandas` (pulls geopandas 1.1.2, pandas 3.0.1, pyogrio
0.12.1). Used exclusively by `generate_mock_parcels.py` for Layer 1 polygon download;
not required by the production engine.

### 2c. `generate_mock_parcels.py` — Refactored as Dual-Engine Parcel Factory

Replaced the old shapefile-based generator (which required a local `.shp`) with a
live PHIVOLCS ArcGIS REST client. Two modes via `--type {slope,depositional}`:

**Mode: `--type slope`** (Layer 0 raster, dart-throwing)
- Target bbox: CAR region `[120.39, 15.82, 121.69, 18.59]`.
- Pings `/identify` endpoint: `layers=show:0`, `tolerance=3`, `returnGeometry=false`.
- Logs all raw pixel values observed; classifies via `--high-pixels` / `--low-pixels`
  (defaults `3` / `1`). Traps silent ArcGIS API errors (`"error"` key in response).
- Also attempts a direct `Layer0/query` vector call first; falls back to dart-throwing
  if the layer has no queryable attribute table.
- Saves 20 × 20 m GeoJSON squares to `susceptible/` or `safe/`.

**Mode: `--type depositional`** (Layer 1 vector)
- GeoJSON query: `{base_url}/1/query?where=1%3D1&outFields=*&f=geojson&resultRecordCount=50&token={token}`.
- `geopandas.read_file()` download → area-weighted random point sampling inside polygons.
- Saves squares to `prone/`.

**ArcGIS Token Authentication**
- `-u / --username` (required CLI arg).
- Password sourced from `.env` (`PHIVOLCS_PASSWORD=`) if present (uses `python-dotenv`
  when installed; falls back to inline line-by-line `.env` parser). Otherwise prompts
  via `getpass.getpass()` — password never touches argv or shell history.
- `get_token()` POSTs to the Portal endpoint (see §3 below). Exits immediately with a
  clear message if auth fails — no GIS queries attempted with a bad token.
- Token appended to all subsequent `/identify` and `/query` requests.

### 2d. `test_ground_truth.py` — Validation Harness

Iterates `tests/ground_truth/{safe,susceptible,prone}/`, runs each GeoJSON blindly
through `EILOrchestrator.run_assessment()`, and compares to the folder ground truth.

**Confusion matrix semantics** (positive class = HAZARDOUS):
- `susceptible/` → checks slope axis only (SUSCEPTIBLE or FLAG FOR REVIEW = TP)
- `prone/` → checks depositional axis only (PRONE in status = TP)
- `safe/` → checks both axes; any hazard finding = FP

**Output:**
- Strict confusion matrix (TP, FP, TN, FN) with Accuracy, Precision, Recall, F1.
- Per-category breakdown.
- Detailed CSV: `parcel_id`, `category`, `ground_truth`, `slope_status`, `depo_status`,
  `overall_status`, `engine_hazard`, `matrix_quad`, `max_slope_deg`, `avg_slope_deg`,
  `error`.
- Exits with code 1 if any FN (missed hazard) — CI-gate ready.

---

## 3. ArcGIS Authentication: Federated Portal Fix

Initial `TOKEN_URL` was derived from `BASE_URL`:
```
https://gisweb.phivolcs.dost.gov.ph/arcgis/tokens/generateToken
```
This returned `"You are not authorized to access this information"` — the server is
federated with an ArcGIS Portal, so the standalone Server token endpoint rejects
credentials. Fixed by switching to the Portal endpoint:
```
https://gisweb.phivolcs.dost.gov.ph/portal/sharing/rest/generateToken
```
Payload (`username`, `password`, `client=requestip`, `expiration=60`, `f=json`) is
unchanged — the Portal endpoint uses the same schema.

---

## Pending / Next Session

- Run `generate_mock_parcels.py --type slope` against live PHIVOLCS endpoint to
  collect ground truth parcels; verify pixel value classification.
- Run `test_ground_truth.py` with collected parcels once 'Backup Plus' drive is mounted.
- Phase 2: Landlab + XGBoost hybrid engine — deferred.
- HTTP API — deferred.

---

# EIL-Calc Session Log — 2026-03-04 (ADR-001 Delivery)

## Session Overview

Implemented **ADR-001: Zeroth-Order Topological Upgrades**. Upgraded the Phase 1 geoprocessing engine from static geometric buffers to topography-aware physical algorithms, drastically reducing false-positives caused by micro-terrain noise and arbitrary geometry clipping.

---

## 1. Feature 3.1: DEM Noise Mitigation (Spatial Smoothing)

**Target:** `slope_stability.py`
- Introduced `scipy.ndimage.gaussian_filter` evaluated *after* bounding box masking.
- Applies a `sigma=2.0` buffer over the raw 5m IfSAR grid to simulate a ~30m geomorphological meso-surface.
- This effectively filters out microscopic spikes (boulders, radar noise) before `np.gradient()` is run, preventing artificial 90-degree slope artifacts from being evaluated in the threshold checking.

## 2. Feature 3.2: Dynamic Slope Unit (SU) Delineation

**Target:** `slope_stability.py`
- Removed the strict `_BUFFER_METRES = 60.0` Euclidean circle bounding logic.
- Increased the spatial capture radius to 500m to form a viable topographic context.
- Used `skimage.segmentation.watershed` processing local minima (-elevation) to map the continuous ridge lines defining the hillside sub-basin around the parcel.
- The `su_mask` (Slope Unit mask) now strictly confines `max_slope_degrees` tracking to the natural drainage boundary contiguous with the parcel site, instead of blindly jumping across unrelated ridges/valleys that happen to fall within 60m.

## 3. Feature 3.3: Topographic Runout Routing (Steepest-Descent)

**Target:** `calculate_depositional_safety.py`
- Scrapped the static straight-line `Geod.inv()` formula between `peak_point` and `site_point`.
- Deployed a steepest-descent pathfinding loop. The pointer drops from the highest peak and meanders pixel-by-pixel downhill, accurately tracing the geodetic path a true avalanche or debris flow would take.
- The `h_distance` is now mathematically calculated by summing the hypotenuse vector lengths traversing this terrain-aware curve.
- Outputs the 1-D coordinate matrix directly into `_viz_transect` for the React layer to plot.

---

## Commit History

| Hash | Message |
|---|---|
| `5869bf3` | feat: implement zeroth-order topological improvements |


