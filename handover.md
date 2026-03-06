# EIL-Calc / EIL-Viz — Context Handover

Current as of **2026-03-06**.
Primary map for orienting before any implementation work.

---

## 0. Repository Layout

```
hasadmin/packages/
├── eil-calc/          Python FastAPI physics backend
└── eil-viz/           React/Vite visualization frontend
```

Both run locally; they communicate over `http://127.0.0.1:8000`.

---

## 1. eil-calc (Backend)

### Start-up
```bash
cd packages/eil-calc
uv run uvicorn api:app --host 127.0.0.1 --port 8000 --reload
```
Requires the **Backup Plus** external drive mounted at
`/run/media/finch/Backup Plus/eil-calc/` (IfSAR 14.8 GB + SRTM 11.3 GB).

### File Map

| File | Role |
|---|---|
| `api.py` | FastAPI entrypoint — `POST /api/v1/assess` |
| `orchestrator.py` | Opens DEM once; reprojects WGS84 → DEM CRS; builds `DEMContext`; calls both physics modules |
| `slope_stability.py` | Gaussian-smoothed gradient + watershed Slope Unit delineation |
| `calculate_depositional_safety.py` | Uphill Walker + Downhill Stepper multi-path runout routing |
| `eil_types.py` | All `TypedDict` output schemas + `DEMContext` dataclass |
| `smart_fetcher.py` | IfSAR-first DEM path resolution; raises `FileNotFoundError` if drive absent |
| `cli.py` | Argparse CLI (`eil-calc --geojson … --project-id …`) |
| `hybrid_engine.py` | Stub — Phase 2 placeholder; returns mock data |

### API Contract

**Request** (`POST /api/v1/assess`):
```json
{
  "project_id": "LOT-2024-001",
  "geometry": { "type": "Polygon", "coordinates": [[...]] },
  "config": { "mode": "compliance" }
}
```
`geometry` must be WGS84 (EPSG:4326). The orchestrator handles reprojection internally.

**Response** (abbreviated):
```json
{
  "project_id": "LOT-2024-001",
  "data_source": "ifsar",
  "phase_1_compliance": {
    "slope_stability": {
      "metrics": { "max_slope_degrees": 22.4, "avg_slope_degrees": 14.1 },
      "assessment": { "status": "SUSCEPTIBLE", "threshold_used": "max_slope" },
      "_viz_grid": [[12.1, 18.4, null], ...]
    },
    "depositional_hazard": {
      "metrics": { "elevation_peak": 850.0, "elevation_site": 612.0, "delta_e": 238.0,
                   "horizontal_distance_h": 490.0, "required_runout_3x": 714.0 },
      "assessment": { "status": "PRONE (Within Runout Zone)", "is_compliant": false },
      "_viz_transects": [
        {
          "metrics": { ... },
          "assessment": { "status": "PRONE ...", "is_compliant": false },
          "path": [{ "dist_m": 0, "elev_m": 850.0 }, ...],
          "threat_ratio": 1.46
        }
      ]
    },
    "overall_status": "NOT CERTIFIED"
  },
  "phase_2_scientific": null,
  "final_decision": "PENDING"
}
```

### Physics: `slope_stability.py`

**Buffer → Smooth → Gradient → Slope Unit → Parcel mask**

1. **Catchment buffer** (`_CATCHMENT_BUFFER_METRES = 500.0`): Geometry is buffered 500 m
   before masking so parcel-edge pixels compute gradient against real terrain, not nodata
   sentinels. Geographic CRS conversion: `buffer_dist = 500 / 111320.0`.

2. **Gaussian smoothing** (`scipy.ndimage.gaussian_filter`, σ = 2.0): Applied to the
   buffered elevation block *before* `np.gradient`. Simulates a ~30 m geomorphological
   meso-surface, suppressing 5 m IfSAR radar noise and micro-topographic spikes that
   would otherwise produce artificial 90° slope artefacts.
   NaN-safe: fills NaN with 0, smooths the validity weight map in parallel, then
   divides to reconstruct a NaN-respecting smoothed surface.

3. **Gradient**: `np.gradient(elevation_smoothed, py_m, px_m)` — pixel size in metres
   (geographic CRS: `py_m = py * 111320.0`, `px_m = px * 111320.0 * cos(lat)`).

4. **Slope Unit delineation** (`skimage.segmentation.watershed`):
   - Local minima in the smoothed elevation (`skimage.feature.peak_local_max` on
     `-elevation`, `min_distance=10`) become watershed markers.
   - `watershed(elev_valid, markers, mask=valid_mask)` partitions the buffered terrain
     into natural drainage basins.
   - Only catchments that intersect the original unbuffered parcel are retained
     (`su_mask = np.isin(catchments, overlapping_sus)`).
   - Fallback: if the watershed is flat, `su_mask = parcel_mask`.

5. **Parcel mask** (`rasterio.features.geometry_mask`, original unbuffered geometry,
   `out_transform` from the 500 m buffered extraction).

6. **Metrics**: `np.nanmax` / `np.nanmean` over `slope_degrees[su_mask & valid_mask]`.

7. **`_viz_grid`**: Full slope array from the buffered extraction, with all pixels
   outside the original parcel set to `None`. Row-major 2D list for JSON serialisation.

**Thresholds**: ≤ 14° SAFE / 14–16° FLAG FOR REVIEW / > 16° SUSCEPTIBLE.

### Physics: `calculate_depositional_safety.py`

**Uphill Walker → Downhill Stepper → Top-3 Transects → Worst-Case Status**

**Step A — Site** (`rasterio.mask.mask` on parcel geometry):
Site elevation = minimum valid elevation inside the parcel.
Site point = pixel coordinates of that minimum, converted via `rasterio.transform.xy`.

**Step B — Vicinity** (1 000 m search buffer):
Full 1 km² area extracted; geographic CRS buffer:
`search_buffer = search_buffer_meters / (111320 * cos(lat_rad))`.
Parcel boolean mask (`parcel_mask_vic`) projected into the vicinity grid.

**Step C.1 — Uphill Walker** (reverse gradient ascent from each parcel boundary pixel):
- 8-directional greedy ascent.
- **Outward-only constraint**: `if parcel_mask_vic[nr, nc]: continue` — prevents the
  walker from re-entering the parcel.
- **Topographic momentum** (5 × 5 look-ahead): if all 8 neighbours are lower, scans a
  ±2-pixel window; if a higher cell exists, jumps to it to escape micro-dips.
- Terminates when truly trapped on a ridge.
- **Regional filter**: peaks within 50 m horizontal distance of the site are discarded
  (retaining walls, grade changes).
- De-duplication by `(row, col)` coordinate.
- Geodetic distance: `pyproj.Geod.inv()` for geographic CRS; Euclidean otherwise.

**Step C.2 — Downhill Stepper** (per unique peak):
- Greedy descent: at each step takes the steepest downhill unvisited 8-neighbour.
- Accumulates `h_distance` step-by-step using `Geod.inv()` (geographic) or `hypot`
  (projected).
- **Trapped-sink closure**: if the stepper halts outside the parcel, straight-line
  geodetic distance from the trap point to `site_point` is appended (conservative).
- `transect` list: `[{"dist_m": …, "elev_m": …}, …]` for Recharts.
- `ΔE = elevation_peak − elevation_site`.
- `required_runout = 3 × ΔE`.
- `threat_ratio = required_runout / h_distance` (> 1 means PRONE).

**Step C.3 — Ranking & Master Status**:
- All transects sorted by `threat_ratio` descending.
- Top 3 returned in `_viz_transects`.
- **Master status** (worst-case): PRONE if *any* of the top-3 paths is non-compliant.
- Top-level `metrics` and `assessment` keys reflect the worst (index 0) path.
- **Flat-land fallback**: if no threatening peaks found, returns SAFE with dummy
  zero-distance path.

### Data Schemas (`eil_types.py`)

```python
class SlopeResult(TypedDict):
    metrics: SlopeMetrics          # max_slope_degrees, avg_slope_degrees
    assessment: SlopeAssessment    # status, threshold_used
    _viz_grid: list[list[float]]   # row-major 2D, None for out-of-parcel pixels

class DepositionalResult(TypedDict):
    metrics: DepositionalMetrics         # worst-case path
    assessment: DepositionalAssessment   # worst-case status, is_compliant
    _viz_transects: list[dict]           # [{metrics, assessment, path, threat_ratio}, ...]
```

`DEMContext` dataclass: `dataset` (open `rasterio.DatasetReader`), `geometry`
(already in DEM CRS), `source_type`, `landlab_grid` (Phase 2 placeholder).

### Tests

| Suite | What it tests |
|---|---|
| `test_eil_calc.py` | Unit — conical-gradient synthetic DEMs via `rasterio.MemoryFile`; 4 slope tests + 2 depositional |
| `test_orchestrator.py` | Orchestrator wiring with `SmartFetcher` patched |
| `test_integration.py` | 9 tests against real IfSAR fixture (`test_fixtures/ifsar_tile.tif`, Bukidnon highlands) |
| `test_ground_truth.py` | Executive harness — iterates `tests/ground_truth/{safe,susceptible}/`, measures latency, prints confusion matrix |

Run all: `uv run python -m pytest test_eil_calc.py test_orchestrator.py test_integration.py -v`

### Ground Truth Pipeline

```bash
# Generate slope test parcels from live PHIVOLCS ArcGIS REST
python generate_mock_parcels.py --type slope -u <username> --count 20

# Generate depositional parcels
python generate_mock_parcels.py --type depositional -u <username> --count 10

# Run validation harness
python test_ground_truth.py --base-dir tests/ground_truth
```

Auth: Token from `https://gisweb.phivolcs.dost.gov.ph/portal/sharing/rest/generateToken`
(Portal-federated — standalone `/arcgis/tokens/generateToken` is rejected).
Password from `.env` (`PHIVOLCS_PASSWORD=…`) or `getpass` prompt.

---

## 2. eil-viz (Frontend)

### Start-up
```bash
cd packages/eil-viz
npm run dev   # → http://localhost:5173
```

### File Map

| File | Role |
|---|---|
| `src/App.jsx` | GeoJSON textarea, fetch logic, FeatureCollection Polygon extraction, passes `data` to `EILViz` |
| `src/components/EILViz.jsx` | Two-tab dashboard: slope heatmap + depositional transect |

### `App.jsx` — Input handling

- Accepts bare Geometry, Feature, or FeatureCollection (scans for first Polygon feature).
- `POST http://127.0.0.1:8000/api/v1/assess` with `{ project_id, geometry, config }`.
- Renders `<EILViz data={result} />` on success.

### `EILViz.jsx` — Visualisation

**Slope tab** (`_viz_grid`):
- `SlopeHeatmap`: HTML5 Canvas. Crops to bounding box of non-null pixels ± 1 px.
  Per-pixel colour via `slopeColor(deg)` — blue-green (< 10°) → amber (10–16°) →
  crimson (> 16°). Highlights max-slope pixel with white outline. Mouse tooltip
  shows slope at hovered pixel.
- `SlopeLegend`: gradient bar + tick labels at 0°, 5°, 10°, 16°, 25°.
- Metric cards: max slope, avg slope, threshold range, algorithm label.
- Assessment logic panel (pseudo-code display).

**Depositional tab** (`_viz_transects`):
- `TransectChart`: Recharts `AreaChart`. Data source: `activeTransect.path`.
  X-axis domain: `[0, Math.max(250, maxTransectDist, runoutDist)]` — prevents tiny
  runouts from visually dominating.
  `ReferenceLine` at `required_runout_3x` (red dashed — 3×ΔE limit).
  `ReferenceDot` at peak (red) and site (blue).
  Elevation sanitisation: clamps any value > 5 000 m to the previous valid elevation
  (guards against nodata bleed-through into the transect list).
- Dropdown selector: rendered only when `transects.length > 1`. Maps over
  `_viz_transects`; labels paths as "Critical Path 1 (Highest Threat Severity)", etc.
- `selectedPathIndex` controls `activeTransect`; Master Status in the header is always
  the overall worst-case (not the selected path).
- Runout fact box: shows `H > 3×ΔE` formula and computed values; `.prone` class
  applies red tint when non-compliant.
- Fallback: handles old single-transect `_viz_transect` (singular) key from pre-refactor
  cached API responses.

**Status badge mapping**:
- SAFE / CERTIFIED → green (`badge-safe`)
- REVIEW / FLAG → amber (`badge-review`)
- Everything else → red (`badge-danger`)

---

## 3. Key Invariants

| Rule | Where enforced |
|---|---|
| Input geometry always WGS84 | Orchestrator reprojects once before building `DEMContext`; no module does CRS logic |
| Worst-case master status | `calculate_depositional_safety.py` line 293; UI header ignores `selectedPathIndex` |
| `_viz_grid` null = outside parcel | `slope_stability.py`: `viz_grid[~parcel_mask] = np.nan` then serialised as `None` |
| `_viz_transects` sorted by threat_ratio desc | `calculate_depositional_safety.py` line 265 |
| Drive absent → HTTP 503, not 500 | `api.py` catches `FileNotFoundError` separately |
| Nodata → NaN before gradient | `slope_stability.py` — prevents INT32_MAX sentinel from producing 90° artefacts |

---

## 4. Known Pending Work

| Item | Priority | Notes |
|---|---|---|
| `generate_gt_ledger.py` | Medium | Purpose unclear — not yet reviewed |
| Ground truth data collection | High | Need to run `generate_mock_parcels.py` against live PHIVOLCS endpoint and verify pixel classifications |
| `test_integration.py` ground-truth values | Medium | May need updating after Gaussian smoothing + SU changes altered slope metrics |
| Phase 2: Landlab + XGBoost | Deferred | `hybrid_engine.py` is a stub |
| HTTP API pagination / project-id lookup | Deferred | Currently stateless per-request |
| `SmartFetcher` tile-aware lookup | Deferred | Currently serves entire nationwide GeoTIFF; no tile splitting |
