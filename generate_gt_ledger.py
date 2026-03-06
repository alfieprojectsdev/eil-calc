#!/usr/bin/env python3
"""
EIL-Calc Ground Truth Ledger Generator.
Scans the local tests/ground_truth/ directories and builds a CSV ledger
of all manually exported hasadmin parcels to prevent duplicate work.
"""

import csv
from pathlib import Path

def generate_ledger():
    # Adjust this path if you place the script outside the eil-calc root
    base_dir = Path("tests/ground_truth")
    output_file = Path("gt_parcel_ledger.csv")
    
    if not base_dir.exists():
        print(f"[error] Directory {base_dir.absolute()} does not exist.")
        return

    ledger_data = []
    # Tracking your progress towards the Tier 1 goals
    counts = {"safe": 0, "susceptible": 0, "prone": 0}

    # rglog finds both .json and .geojson files recursively
    for geojson_file in base_dir.rglob("*.*json"):
        parcel_id = geojson_file.stem
        category = geojson_file.parent.name
        
        if category in counts:
            counts[category] += 1
        else:
            counts[category] = 1

        ledger_data.append({
            "Parcel_ID": parcel_id,
            "Ground_Truth": category.upper(),
            "File_Path": str(geojson_file)
        })

    # Sort alphabetically/numerically by Parcel ID so it matches the hasadmin list
    ledger_data.sort(key=lambda x: x["Parcel_ID"])

    # Write the CSV
    with open(output_file, mode="w", newline="") as csvfile:
        fieldnames = ["Parcel_ID", "Ground_Truth", "File_Path"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        
        writer.writeheader()
        writer.writerows(ledger_data)

    # Print the Executive Summary to the terminal
    print(f"\n✅ Ledger successfully generated at: {output_file.name}")
    print("=" * 40)
    print("  CURRENT TIER 1 GRIND PROGRESS")
    print("=" * 40)
    for cat, count in counts.items():
        if count > 0 or cat in ["safe", "susceptible"]:
            target = 50 if cat in ["safe", "susceptible"] else 0
            progress = (count / target * 100) if target > 0 else 0
            print(f"  {cat.upper():<12} : {count:>3} / {target}  ({progress:.1f}%)")
    print("=" * 40)
    print(f"  Total Parcels Exported: {len(ledger_data)}\n")

if __name__ == "__main__":
    generate_ledger()