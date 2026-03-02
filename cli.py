#!/usr/bin/env python3
"""EIL-Calc command-line interface."""
import argparse
import json
import sys

from orchestrator import EILOrchestrator


def build_parser():
    parser = argparse.ArgumentParser(
        prog="eil-calc",
        description="Automated Earthquake-Induced Landslide (EIL) hazard assessment for land parcels.",
    )
    parser.add_argument("--geojson", required=True, metavar="PATH",
                        help="Path to GeoJSON file (Feature with Polygon geometry).")
    parser.add_argument("--project-id", required=True, dest="project_id", metavar="ID",
                        help="Project identifier included in the output.")
    parser.add_argument("--mode", choices=["compliance", "research"], default="compliance",
                        help="Assessment mode (default: compliance).")
    parser.add_argument("--output", metavar="PATH",
                        help="Write JSON result to this file (default: stdout).")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    # Load GeoJSON
    try:
        with open(args.geojson) as f:
            geojson = json.load(f)
    except FileNotFoundError:
        print(f"Error: GeoJSON file not found: {args.geojson}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid GeoJSON: {e}", file=sys.stderr)
        sys.exit(2)

    # Extract geometry — accept FeatureCollection, Feature, or bare geometry
    if geojson.get("type") == "FeatureCollection":
        features = geojson.get("features", [])
        if not features:
            print("Error: FeatureCollection contains no features.", file=sys.stderr)
            sys.exit(2)
        geometry = features[0]["geometry"]
    elif geojson.get("type") == "Feature":
        geometry = geojson["geometry"]
    else:
        geometry = geojson  # bare geometry dict

    # Build payload
    payload = {
        "project_id": args.project_id,
        "geometry": geometry,
        "config": {"mode": args.mode},
    }

    # Run assessment
    try:
        orc = EILOrchestrator()
        result = orc.run_assessment(payload)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        import traceback
        print(f"Unexpected error: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(2)

    # Output
    output_str = json.dumps(result, indent=2)
    if args.output:
        with open(args.output, "w") as f:
            f.write(output_str)
            f.write("\n")
    else:
        print(output_str)

    sys.exit(0)


if __name__ == "__main__":
    main()
