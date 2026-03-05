#!/usr/bin/env python3
"""
EIL-Calc Executive Ground Truth Validation Harness.

Iterates through tests/ground_truth/safe/ and tests/ground_truth/susceptible/,
runs each GeoJSON blindly through the EIL-Calc pipeline (EILOrchestrator),
measures latency, and produces an executive-ready Confusion Matrix.
"""

import argparse
import json
import time
from pathlib import Path

from orchestrator import EILOrchestrator

# ── Category configuration ─────────────────────────────────────────────────
# We only care about safe and susceptible.
_CATEGORIES = {
    "safe": {"gt_hazard": False},
    "susceptible": {"gt_hazard": True},
}

# ── GeoJSON loading ────────────────────────────────────────────────────────

def _extract_geometry(path: Path) -> dict:
    """Return the GeoJSON geometry dict from a Feature, FeatureCollection, or
    bare geometry file."""
    with open(path) as f:
        gj = json.load(f)
    if gj.get("type") == "Feature":
        return gj["geometry"]
    if gj.get("type") == "FeatureCollection":
         # PHIVOLCS sometimes puts a polyline first. Find the polygon.
         for feature in gj.get("features", []):
             geom = feature.get("geometry", {})
             if geom.get("type") in ("Polygon", "MultiPolygon"):
                 return geom
         return gj["features"][0]["geometry"]
    return gj  # bare geometry

# ── Main validation loop ───────────────────────────────────────────────────

def run_validation(base_dir: Path) -> None:
    orchestrator = EILOrchestrator()

    matrix = {"TP": 0, "FP": 0, "TN": 0, "FN": 0}
    crashes = 0
    total_latency = 0.0
    processed_count = 0

    print("=" * 60)
    print("  EIL-CALC EXECUTIVE GROUND TRUTH VALIDATION")
    print("=" * 60)
    print(f"  Base directory : {base_dir.resolve()}\n")

    for category, cfg in _CATEGORIES.items():
        folder = base_dir / category
        gt_hazard = cfg["gt_hazard"]

        if not folder.exists():
            print(f"  [SKIP] {folder} — directory not found.\n")
            continue

        files = sorted(folder.glob("*.geojson"))
        if not files:
            print(f"  [SKIP] {folder} — no .geojson files.\n")
            continue

        print(f"── {category.upper()} ({len(files)} parcel(s)) ─────────────────────────")

        for path in files:
            parcel_id = path.stem
            try:
                geometry = _extract_geometry(path)
                payload  = {
                    "project_id": parcel_id,
                    "geometry":   geometry,
                    "config":     {"mode": "compliance"},
                }
                
                # Measure latency
                start_time = time.perf_counter()
                result = orchestrator.run_assessment(payload)
                end_time = time.perf_counter()
                
                latency = end_time - start_time
                total_latency += latency
                processed_count += 1

                # Read the final assessment status from the orchestrator payload schema
                status = result.get("phase_1_compliance", {}).get("overall_status", "UNKNOWN")
                
                pred_hazard = status in ("SUSCEPTIBLE", "NOT CERTIFIED", "MANUAL REVIEW REQUIRED")

                if gt_hazard and pred_hazard:
                    q = "TP"
                elif not gt_hazard and pred_hazard:
                    q = "FP"
                elif not gt_hazard and not pred_hazard:
                    q = "TN"
                else:
                    q = "FN"  # hazard missed — dangerous

                matrix[q] += 1
                
                danger = "  *** MISSED HAZARD ***" if q == "FN" else ""
                print(f"  {parcel_id:<20s}  status={status:<26s}  {q}{danger}  ({latency:.3f}s)")

            except Exception as exc:
                print(f"  {parcel_id:<20s}  *** CRASH: {exc} ***")
                crashes += 1

        print()

    # ── Print Executive Summary ──────────────────────────────────────────────
    TP, FP, TN, FN = matrix["TP"], matrix["FP"], matrix["TN"], matrix["FN"]
    total = TP + FP + TN + FN

    accuracy = (TP + TN) / total * 100 if total else 0.0
    avg_latency = total_latency / processed_count if processed_count else 0.0

    print("=" * 60)
    print("  EXECUTIVE CONFUSION MATRIX")
    print("=" * 60)
    print(f"  Total parcels tested : {total + crashes}")
    print(f"  Successful processed : {processed_count}")
    print(f"  Crashes (edge cases) : {crashes}")
    print(f"  Average Compute Latency : {avg_latency:.3f} seconds/parcel")
    print()
    print(f"  Overall Accuracy (%) : {accuracy:.1f}%\n")
    
    print("  Confusion Matrix (Positive Class = Hazardous Parcel):")
    print(f"  {'':15s}  {'Pred HAZARD':>14s}  {'Pred SAFE':>12s}")
    print(f"  {'GT HAZARD':15s}  {'TP = ' + str(TP):>14s}  {'FN = ' + str(FN):>12s}  <- Critical Failures")
    print(f"  {'GT SAFE':15s}  {'FP = ' + str(FP):>14s}  {'TN = ' + str(TN):>12s}  <- Over-conservative")
    print("=" * 60)

# ── CLI ────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="EIL-Calc Executive Ground Truth Validation Harness",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--base-dir", default="tests/ground_truth", metavar="DIR",
        help="Root folder containing safe/ and susceptible/ sub-directories.",
    )
    args = parser.parse_args()
    run_validation(Path(args.base_dir))

if __name__ == "__main__":
    main()
