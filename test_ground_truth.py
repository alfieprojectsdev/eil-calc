#!/usr/bin/env python3
"""
EIL-Calc Ground Truth Validation Harness.

Iterates through tests/ground_truth/{safe,susceptible,prone}/, runs each
GeoJSON blindly through the EIL-Calc pipeline, and produces a confusion
matrix and detailed CSV report.

Folder → Ground Truth mapping:
  safe/         Slope SAFE expected      (negative class — not a hazard)
  susceptible/  Slope SUSCEPTIBLE/REVIEW expected  (positive class — slope hazard)
  prone/        Depositional PRONE expected         (positive class — depositional hazard)

Positive class = ANY hazard (slope OR depositional).

Usage:
  python test_ground_truth.py
  python test_ground_truth.py --base-dir tests/ground_truth --output report.csv
"""

import argparse
import csv
import json
import sys
from pathlib import Path

from orchestrator import EILOrchestrator

# ── Category configuration ─────────────────────────────────────────────────
# "check" controls which axis is tested against the ground truth label.
#   "slope"        — check slope_stability status only
#   "depositional" — check depositional_hazard status only
#   "both"         — flag as hazard if EITHER axis is hazardous
_CATEGORIES: dict[str, dict] = {
    "safe":        {"gt_hazard": False, "check": "both"},
    "susceptible": {"gt_hazard": True,  "check": "slope"},
    "prone":       {"gt_hazard": True,  "check": "depositional"},
}


# ── Hazard predicates ──────────────────────────────────────────────────────

def _slope_is_hazard(slope_res: dict) -> bool:
    status = slope_res.get("assessment", {}).get("status", "")
    return status in ("SUSCEPTIBLE", "FLAG FOR REVIEW")


def _depo_is_hazard(dep_res: dict) -> bool:
    status = dep_res.get("assessment", {}).get("status", "")
    return "PRONE" in status


def _engine_is_hazard(result: dict, check: str) -> bool:
    slope_res = result["phase_1_compliance"]["slope_stability"]
    dep_res   = result["phase_1_compliance"]["depositional_hazard"]
    if check == "slope":
        return _slope_is_hazard(slope_res)
    if check == "depositional":
        return _depo_is_hazard(dep_res)
    # "both": a safe parcel is a false positive if EITHER axis fires.
    return _slope_is_hazard(slope_res) or _depo_is_hazard(dep_res)


# ── GeoJSON loading ────────────────────────────────────────────────────────

def _extract_geometry(path: Path) -> dict:
    """Return the GeoJSON geometry dict from a Feature, FeatureCollection, or
    bare geometry file."""
    with open(path) as f:
        gj = json.load(f)
    if gj.get("type") == "Feature":
        return gj["geometry"]
    if gj.get("type") == "FeatureCollection":
        return gj["features"][0]["geometry"]
    return gj  # bare geometry


# ── Main validation loop ───────────────────────────────────────────────────

def run_validation(base_dir: Path, output_csv: Path) -> None:
    orchestrator = EILOrchestrator()

    rows: list[dict] = []
    matrix = {"TP": 0, "FP": 0, "TN": 0, "FN": 0}
    per_cat: dict[str, dict[str, int]] = {
        cat: {"TP": 0, "FP": 0, "TN": 0, "FN": 0}
        for cat in _CATEGORIES
    }

    print("EIL-Calc Ground Truth Validation")
    print(f"Base directory : {base_dir.resolve()}")
    print(f"Output CSV     : {output_csv.resolve()}\n")

    for category, cfg in _CATEGORIES.items():
        folder   = base_dir / category
        gt_hazard = cfg["gt_hazard"]
        check     = cfg["check"]

        if not folder.exists():
            print(f"[skip] {folder} — directory not found.\n")
            continue

        files = sorted(folder.glob("*.geojson"))
        if not files:
            print(f"[skip] {folder} — no .geojson files.\n")
            continue

        print(f"── {category.upper()} ({len(files)} parcel(s)) ──────────────────────────")

        for path in files:
            parcel_id = path.stem
            try:
                geometry = _extract_geometry(path)
                payload  = {
                    "project_id": parcel_id,
                    "geometry":   geometry,
                    "config":     {"mode": "compliance"},
                }
                result    = orchestrator.run_assessment(payload)
                slope_res = result["phase_1_compliance"]["slope_stability"]
                dep_res   = result["phase_1_compliance"]["depositional_hazard"]
                overall   = result["phase_1_compliance"]["overall_status"]

                slope_status = (
                    slope_res.get("assessment", {}).get("status")
                    or slope_res.get("error", "ERROR")
                )
                dep_status = (
                    dep_res.get("assessment", {}).get("status")
                    or dep_res.get("error", "ERROR")
                )
                max_slope = slope_res.get("metrics", {}).get("max_slope_degrees", float("nan"))
                avg_slope = slope_res.get("metrics", {}).get("avg_slope_degrees", float("nan"))

                pred_hazard = _engine_is_hazard(result, check)

                if gt_hazard and pred_hazard:
                    q = "TP"
                elif not gt_hazard and pred_hazard:
                    q = "FP"
                elif not gt_hazard and not pred_hazard:
                    q = "TN"
                else:
                    q = "FN"  # hazard missed — dangerous

                matrix[q] += 1
                per_cat[category][q] += 1

                danger = "  *** MISSED HAZARD ***" if q == "FN" else ""
                print(
                    f"  {parcel_id:<30s}"
                    f"  slope={slope_status:<22s}"
                    f"  depo={dep_status:<28s}"
                    f"  {q}{danger}"
                )

                rows.append({
                    "parcel_id":     parcel_id,
                    "category":      category,
                    "ground_truth":  "HAZARD" if gt_hazard else "SAFE",
                    "slope_status":  slope_status,
                    "depo_status":   dep_status,
                    "overall_status": overall,
                    "engine_hazard": "YES" if pred_hazard else "NO",
                    "matrix_quad":   q,
                    "max_slope_deg": f"{max_slope:.4f}" if max_slope == max_slope else "nan",
                    "avg_slope_deg": f"{avg_slope:.4f}" if avg_slope == avg_slope else "nan",
                    "error":         "",
                })

            except Exception as exc:
                print(f"  {parcel_id:<30s}  ERROR: {exc}")
                rows.append({
                    "parcel_id":     parcel_id,
                    "category":      category,
                    "ground_truth":  "HAZARD" if gt_hazard else "SAFE",
                    "slope_status":  "ERROR",
                    "depo_status":   "ERROR",
                    "overall_status": "ERROR",
                    "engine_hazard": "ERROR",
                    "matrix_quad":   "ERROR",
                    "max_slope_deg": "nan",
                    "avg_slope_deg": "nan",
                    "error":         str(exc),
                })

        print()

    # ── Write CSV ─────────────────────────────────────────────────────────
    fieldnames = [
        "parcel_id", "category", "ground_truth",
        "slope_status", "depo_status", "overall_status",
        "engine_hazard", "matrix_quad",
        "max_slope_deg", "avg_slope_deg", "error",
    ]
    with open(output_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # ── Print results ─────────────────────────────────────────────────────
    TP, FP, TN, FN = matrix["TP"], matrix["FP"], matrix["TN"], matrix["FN"]
    total = TP + FP + TN + FN

    accuracy  = (TP + TN) / total * 100 if total else 0.0
    precision = TP / (TP + FP)          * 100 if (TP + FP) else 0.0
    recall    = TP / (TP + FN)          * 100 if (TP + FN) else 0.0
    f1        = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) else 0.0
    )

    W = 60
    print("=" * W)
    print("  EIL-CALC GROUND TRUTH VALIDATION RESULTS")
    print("=" * W)
    print(f"  Total parcels tested : {total}")
    print()
    print(f"  Accuracy   : {accuracy:.1f}%")
    print(f"  Precision  : {precision:.1f}%   (when flagged, was it correct?)")
    print(f"  Recall     : {recall:.1f}%   (of actual hazards, how many caught?)")
    print(f"  F1 Score   : {f1:.1f}%")
    print()
    print("  Confusion Matrix  (positive class = HAZARDOUS)")
    print(f"  {'':12s}  {'Pred HAZARD':>14s}  {'Pred SAFE':>12s}")
    print(
        f"  {'GT HAZARD':12s}  "
        f"{'TP = ' + str(TP):>14s}  "
        f"{'FN = ' + str(FN):>12s}"
        f"   <- FN = MISSED HAZARD"
    )
    print(
        f"  {'GT SAFE':12s}  "
        f"{'FP = ' + str(FP):>14s}  "
        f"{'TN = ' + str(TN):>12s}"
    )
    print()
    print("  Per-category breakdown:")
    for cat, m in per_cat.items():
        n = sum(m.values())
        if n == 0:
            continue
        print(
            f"  {cat:<14s}  "
            f"TP={m['TP']}  FP={m['FP']}  TN={m['TN']}  FN={m['FN']}"
        )
    print()
    print(f"  Detailed report saved to: {output_csv.resolve()}")
    print("=" * W)

    if FN > 0:
        print(
            f"\n  *** WARNING: {FN} missed hazard(s) (FN > 0). "
            "Review FN rows in the CSV. ***\n"
        )
        sys.exit(1)


# ── CLI ────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="EIL-Calc Ground Truth Validation Harness",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--base-dir", default="tests/ground_truth", metavar="DIR",
        help=(
            "Root folder containing safe/, susceptible/, prone/ "
            "sub-directories (default: tests/ground_truth)"
        ),
    )
    parser.add_argument(
        "--output", default="validation_report.csv", metavar="FILE",
        help="Path for the CSV report (default: validation_report.csv)",
    )
    args = parser.parse_args()
    run_validation(Path(args.base_dir), Path(args.output))


if __name__ == "__main__":
    main()
