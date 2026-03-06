# Code Review — EIL-Calc & EIL-Viz
**Date:** 2026-03-06
**Branch reviewed:** `feat/zeroth-order-topology` → `master`
**Reviewer:** Claude (automated audit)
**Outcome:** 3 blocking bugs found, fixed, and merged.

---

## Bugs Fixed

### 1. `slope_stability.py` — SU mask over-reports terrain (FIXED)

**Location:** line 103 (post-fix)
**Symptom:** `max_slope_degrees` and `avg_slope_degrees` reflected terrain up to 500 m outside the parcel, producing false SUSCEPTIBLE verdicts for parcels at the edge of steep drainage basins.
**Root cause:** `site_slopes = slope_degrees[su_mask & valid_mask]` — `su_mask` selects every pixel in the matching drainage basins, not just the parcel footprint.
**Fix:** `slope_degrees[su_mask & parcel_mask & valid_mask]`

---

### 2. `calculate_depositional_safety.py` — Empty transect on parcel-interior peak (FIXED)

**Location:** downhill stepper loop entry
**Symptom:** Peaks that the 5×5 momentum jump placed inside the parcel produced `h_distance=0.0`, `transect=[]`, and `threat_ratio=inf`. Those paths sorted to position 0 ("worst") and propagated an empty `"path": []` to the React frontend — likely a JS crash on `AreaChart`.
**Root cause:** No guard before `while parcel_inv_mask[curr_r, curr_c]`; if the peak pixel is inside the parcel the loop body never executes.
**Fix:** `if not parcel_inv_mask[peak_r, peak_c]: continue` before the stepper.

---

### 3. `calculate_depositional_safety.py` — Unsafe float32 nodata comparison (FIXED)

**Location:** Steps A & B; uphill walker and downhill stepper inner loops
**Symptom:** IfSAR nodata = `2147483648.0` (near INT32_MAX). Exact equality between a `float32` rasterio array and Python `float64` at that magnitude can silently return `False` — nodata pixels treated as extreme-elevation valid terrain by the uphill walker.
**Root cause:** `vic_elevations[r, c] == dataset.nodata` on a raw float32 array.
**Fix:** Cast both elevation arrays to `float64` immediately after extraction and NaN-replace nodata (`arr[arr == dataset.nodata] = np.nan`). All inner-loop guards replaced with `np.isnan()`. Same pattern already used in `slope_stability.py` — now consistent.

---

## Minor Issues (non-blocking, tracked separately)

| File | Issue |
|---|---|
| `generate_mock_parcels.py` | `gpd.read_file()` called in `mode_slope` but `geopandas` only imported in `mode_depositional`. `NameError` swallowed by `except Exception` — vector-query path in `mode_slope` silently never works. |
| `slope_stability.py` | Buffer distance `= 500 / 111320.0` corrects only for latitude scale. E-W distortion ≤ 5% at 18°N; acceptable for now but inconsistent with depositional module which applies `cos(lat)` correction. |

---

## Files That Should Not Be in the Repo

| File | Issue |
|---|---|
| `session_log.md` | Working-notes file; project convention says gitignored. Committed in an earlier commit on this branch. Add to `.gitignore` before next contributor onboards. |
| `gt_parcel_ledger.csv` | Generated artefact with machine-local absolute paths. Should be in `.gitignore`. |

---

## EIL-Viz Changes (same session, pushed to `main`)

All changes were UI-correctness and schema alignment — no bugs introduced.

| Change | File |
|---|---|
| Migrated from `_viz_transect` (singular) to `_viz_transects` array | `EILViz.jsx` |
| Added `selectedPathIndex` state; `activeTransect` drives all metric cards and chart | `EILViz.jsx` |
| Dropdown path selector (renders only when `transects.length > 1`) | `EILViz.jsx` |
| `axisMaxDist = Math.max(250, maxTransectDist, runoutDist)` prevents visual collapse on short runouts | `EILViz.jsx` |
| Backward-compat fallback for old `_viz_transect` singular key | `EILViz.jsx` |
| Sidebar spacing, textarea flex-grow, solid error background | `App.css` |
| Responsive base font via `clamp(14px, 1.5vh, 18px)` | `index.css` |

---

## Test Coverage Notes

- 18/18 tests pass post-fix.
- Integration test ground-truth values updated to match corrected algorithm output (Bukidnon parcel: peak=2471 m, delta_e=44 m, PRONE). Old values (2587 m, SAFE) were recorded against the pre-walker single-`np.argmax` implementation and were stale.
- `test_ground_truth.py` confusion-matrix harness is present but not yet exercised against a representative labelled dataset — the `tests/ground_truth/` fixtures are a small sample only.
