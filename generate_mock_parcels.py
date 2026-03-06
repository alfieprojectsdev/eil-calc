#!/usr/bin/env python3
"""
EIL-Calc Ground Truth Parcel Factory.

Generates RFC 7946 GeoJSON test parcels from live PHIVOLCS ArcGIS REST
endpoints.  Two modes:

  slope        — dart-throw random coordinates against the Layer 0 raster
                 (EIL Susceptibility) using the /identify endpoint, then
                 save 20×20 m squares to tests/ground_truth/susceptible/ or
                 tests/ground_truth/safe/ based on the pixel value.

  depositional — query Layer 1 (Depositional Zone polygons), pick random
                 points inside them, and save squares to
                 tests/ground_truth/prone/.

Usage:
  python generate_mock_parcels.py --type slope --count 20
  python generate_mock_parcels.py --type depositional --count 10

  # After a first run logs pixel values you can refine the thresholds:
  python generate_mock_parcels.py --type slope --high-pixels "3,High" \\
                                               --low-pixels  "1,Low"
"""

import argparse
import getpass
import json
import random
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from shapely.geometry import Point, box, mapping

# ── Constants ──────────────────────────────────────────────────────────────
BASE_URL = (
    "https://gisweb.phivolcs.dost.gov.ph"
    "/arcgis/rest/services/PHIVOLCS/EIL_CAR/MapServer"
)

# Portal-federated endpoint — the standalone /arcgis/tokens/generateToken
# is rejected when the server is federated with an ArcGIS Portal.
TOKEN_URL = "https://gisweb.phivolcs.dost.gov.ph/portal/sharing/rest/generateToken"
# Bounding box for the CAR region (Cordillera Administrative Region).
# Covers Abra, Apayao, Benguet, Ifugao, Kalinga, Mountain Province.
SLOPE_BBOX = (120.39, 15.82, 121.69, 18.59)  # (minx, miny, maxx, maxy)

LOT_SIZE_M = 20.0          # square lot side length in metres
OUT_BASE   = Path("tests/ground_truth")


# ── ArcGIS token authentication ───────────────────────────────────────────

def _load_password_from_env() -> str | None:
    """
    Try to read PHIVOLCS_PASSWORD from a .env file in the current directory.

    Uses python-dotenv if available; otherwise falls back to a minimal
    line-by-line parser so the script works without the package installed.
    """
    env_file = Path(".env")
    if not env_file.exists():
        return None

    # Prefer python-dotenv when available.
    try:
        from dotenv import dotenv_values
        return dotenv_values(env_file).get("PHIVOLCS_PASSWORD")
    except ImportError:
        pass

    # Minimal fallback — handles KEY=value, KEY="value", KEY='value', # comments.
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        if key.strip() == "PHIVOLCS_PASSWORD":
            return val.strip().strip('"').strip("'")
    return None


def get_token(username: str, password: str) -> str:
    """
    Obtain a short-lived ArcGIS token (60 min) from the PHIVOLCS server.

    Exits with a clear error message if authentication fails so no GIS
    queries are attempted with a bad credential.
    """
    payload = urllib.parse.urlencode({
        "username":   username,
        "password":   password,
        "client":     "requestip",
        "expiration": "60",
        "f":          "json",
    }).encode()

    req = urllib.request.Request(
        TOKEN_URL,
        data=payload,
        headers={"User-Agent": "eil-calc-gt/0.1"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
    except Exception as exc:
        print(f"[error] Token request to {TOKEN_URL} failed: {exc}")
        sys.exit(1)

    if "error" in result:
        msg = result["error"].get("message") or str(result["error"])
        print(f"[error] Authentication failed: {msg}")
        sys.exit(1)

    token = result.get("token")
    if not token:
        print(f"[error] Unexpected token response (no 'token' key): {result}")
        sys.exit(1)

    expires_ms = result.get("expires", 0)
    print(f"[auth] Token acquired for '{username}' — expires in 60 min.")
    return token


# ── Geometry helpers ───────────────────────────────────────────────────────

def _half_deg() -> float:
    """Half of LOT_SIZE_M converted to degrees (N-S direction)."""
    return (LOT_SIZE_M / 2.0) / 111320.0


def _geojson_feature(lon: float, lat: float, props: dict) -> dict:
    """Build a 20×20 m square Feature around (lon, lat)."""
    half = _half_deg()
    lot = box(lon - half, lat - half, lon + half, lat + half)
    return {"type": "Feature", "properties": props, "geometry": mapping(lot)}


def _save_feature(feature: dict, folder: Path, stem: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / f"{stem}.geojson", "w") as f:
        json.dump(feature, f, indent=2)


# ── ArcGIS REST helpers ────────────────────────────────────────────────────

def _identify_pixel(lon: float, lat: float, token: str) -> dict | None:
    """
    Call the MapServer /identify endpoint for a single point against Layer 0.

    Returns the first result dict from the response, or None if the point
    is outside the raster coverage or the request fails.
    """

    # Create a tiny 0.001 degree box around the point
    extent = f"{lon-0.0005},{lat-0.0005},{lon+0.0005},{lat+0.0005}"

    minx, miny, maxx, maxy = SLOPE_BBOX
    params = urllib.parse.urlencode({
        "geometry":      f"{lon},{lat}",
        "geometryType":  "esriGeometryPoint",
        "sr":            "4326",
        "layers":        "show:0",          # Standard layer targeting
        "tolerance":     "3",               # Standard pixel hit radius
        "mapExtent":     f"{minx},{miny},{maxx},{maxy}",
        "imageDisplay":  "800,600,96",      # Sane virtual screen ratio
        "returnGeometry": "false",
        "token":         token,
        "f":             "json",
    })
    url = f"{BASE_URL}/identify?{params}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "eil-calc-gt/0.1"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())

        # THE SMOKING GUN: Trap silent ArcGIS API errors
        if "error" in data:
            print(f"\n  [esri api error] {data['error']}")
            return None
        
        results = data.get("results", [])
        return results[0] if results else None
    
    except Exception as exc:
        print(f"  [warn] identify failed ({lon:.5f}, {lat:.5f}): {exc}")
        return None


# ── Mode 1: slope (raster dart-throwing) ──────────────────────────────────

def mode_slope(
    count: int,
    delay: float,
    high_pixels: set[str],
    low_pixels: set[str],
    token: str,
) -> None:
    """
    Randomly sample the CAR bounding box and ping the /identify endpoint.
    Sort results into tests/ground_truth/susceptible/ or safe/ based on the
    pixel value.  Log every pixel value seen so the user can refine the
    --high-pixels / --low-pixels thresholds if needed.
    """
    minx, miny, maxx, maxy = SLOPE_BBOX
    susceptible_dir = OUT_BASE / "susceptible"
    safe_dir        = OUT_BASE / "safe"

    seen_values: dict[str, int] = {}
    n_susceptible = n_safe = n_skip = 0
    total = 0
    attempts = 0
    max_attempts = count * 100

    # Try querying as a feature layer first (works if it has an attribute table)
    query_url = f"{BASE_URL}/0/query?where=1=1&outFields=*&f=geojson&resultRecordCount={count}"
    if token:
        query_url += f"&token={token}"
    
    try:
        print(f"[slope] Attempting direct vector query of Layer 0...")
        gdf = gpd.read_file(query_url)
        if not gdf.empty:
            print(f"[slope] Success! Found {len(gdf)} raster features via vector query.")
            # ... (Existing logic to pick points inside these polygons)
            return
    except Exception:
        print(f"[slope] Dart-throwing for {count} parcels via {BASE_URL}/identify")
        print(f"[slope] High-susceptibility pixels : {sorted(high_pixels)}")
        print(f"[slope] Low-susceptibility pixels  : {sorted(low_pixels)}")
        print(f"[slope] API delay                  : {delay}s between calls\n")

        while total < count and attempts < max_attempts:
            attempts += 1
            lon = random.uniform(minx, maxx)
            lat = random.uniform(miny, maxy)

            hit = _identify_pixel(lon, lat, token)
            time.sleep(delay)

            if hit is None:
                print(f"  [miss] ({lon:.4f}, {lat:.4f}) -> Outside Map")
                n_skip += 1
                continue

            # ArcGIS returns pixel value in either attributes["Pixel Value"] or
            # the top-level "value" field.  Try both.
            raw = (
                hit.get("attributes", {}).get("Pixel Value")
                or hit.get("value")
                or "NoData"
            )
            sv = str(raw).strip()
            seen_values[sv] = seen_values.get(sv, 0) + 1

            if sv in high_pixels:
                category = "susceptible"
                out_dir   = susceptible_dir
                n_susceptible += 1
            elif sv in low_pixels:
                category = "safe"
                out_dir   = safe_dir
                n_safe += 1
            else:
                print(f"  [skip] ({lon:.4f}, {lat:.4f}) -> Pixel: {sv!r} (Moderate/NoData)")
                n_skip += 1
                continue

            total += 1
            stem = f"GT_SLOPE_{total:04d}"
            feat = _geojson_feature(lon, lat, {
                "id":               stem,
                "source":           "phivolcs_eil_car_layer0",
                "pixel_value_raw":  raw,
                "expected_label":   category,
            })
            _save_feature(feat, out_dir, stem)
            print(
                f"  [{total:>4d}/{count}]  {stem}  "
                f"pixel={sv!r:>12s}  -> {category.upper()}"
            )

        print(
            f"\n[slope] Done — susceptible={n_susceptible}  "
            f"safe={n_safe}  skipped={n_skip}  attempts={attempts}"
        )
        print(
            "[slope] All pixel values observed "
            "(use these to refine --high-pixels / --low-pixels):"
        )
        for val, cnt in sorted(seen_values.items(), key=lambda kv: -kv[1]):
            tag = (
                "HIGH" if val in high_pixels else
                "LOW"  if val in low_pixels  else
                "SKIP"
            )
            print(f"  {tag:<5s}  {val!r:>20s} : {cnt:>5d} hits")


# ── Mode 2: depositional (vector query) ───────────────────────────────────

def mode_depositional(count: int, delay: float, token: str) -> None:
    """
    Download Layer 1 (Depositional Zone polygons) via GeoJSON query, pick
    random points inside them, and save squares to tests/ground_truth/prone/.
    """
    try:
        import geopandas as gpd
    except ImportError:
        print("[error] geopandas is required for depositional mode.")
        print("        Run: uv add --dev geopandas")
        return

    prone_dir = OUT_BASE / "prone"
    prone_dir.mkdir(parents=True, exist_ok=True)

    # resultRecordCount=50 keeps the payload manageable; raise if you need more.
    query_url = (
        f"{BASE_URL}/1/query"
        f"?where=1%3D1&outFields=*&f=geojson&resultRecordCount=50&token={token}"
    )
    print(f"[depositional] Fetching Layer 1 polygons: {query_url}")
    try:
        gdf = gpd.read_file(query_url)
    except Exception as exc:
        print(f"[error] Failed to fetch Layer 1: {exc}")
        return

    if gdf.empty:
        print("[warn] Layer 1 returned no features.")
        return

    print(f"  Loaded {len(gdf)} depositional zone polygon(s).\n")

    # Weight random polygon selection by area so larger zones contribute
    # proportionally more parcels.
    areas   = gdf.geometry.area
    weights = areas / areas.sum()

    generated = 0
    attempts  = 0
    max_attempts = count * 50

    while generated < count and attempts < max_attempts:
        attempts += 1
        row  = gdf.sample(1, weights=weights).iloc[0]
        poly = row.geometry
        minx, miny, maxx, maxy = poly.bounds

        lon = random.uniform(minx, maxx)
        lat = random.uniform(miny, maxy)

        if not poly.contains(Point(lon, lat)):
            continue

        generated += 1
        stem = f"GT_DEPO_{generated:04d}"
        feat = _geojson_feature(lon, lat, {
            "id":             stem,
            "source":         "phivolcs_eil_car_layer1",
            "expected_label": "prone",
        })
        _save_feature(feat, prone_dir, stem)
        print(
            f"  [{generated:>4d}/{count}]  {stem}  "
            f"({lon:.5f}, {lat:.5f})  -> PRONE"
        )
        time.sleep(delay)

    print(f"\n[depositional] Saved {generated} prone parcels to {prone_dir}")


# ── CLI ────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="EIL-Calc Ground Truth Parcel Factory — PHIVOLCS ArcGIS REST",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--type",
        choices=["slope", "depositional"],
        required=True,
        help=(
            "slope       = Layer 0 raster /identify (dart-throwing)\n"
            "depositional = Layer 1 vector query"
        ),
    )
    parser.add_argument(
        "-u", "--username", required=True, metavar="USER",
        help="PHIVOLCS GIS portal username.",
    )
    parser.add_argument(
        "--count", type=int, default=20, metavar="N",
        help="Number of parcels to generate (default: 20)",
    )
    parser.add_argument(
        "--delay", type=float, default=1.0, metavar="SEC",
        help="Seconds to sleep between API calls (default: 1.0)",
    )
    parser.add_argument(
        "--high-pixels", default="3", metavar="VAL[,VAL]",
        help=(
            "Comma-separated pixel values that indicate High Susceptibility "
            "(default: '3').  Run once without this flag to see what values "
            "the server returns, then pass the correct ones."
        ),
    )
    parser.add_argument(
        "--low-pixels", default="1", metavar="VAL[,VAL]",
        help="Comma-separated pixel values for Low Susceptibility (default: '1').",
    )

    args = parser.parse_args()

    # ── Acquire password ──────────────────────────────────────────────────
    # Prefer .env (PHIVOLCS_PASSWORD=...) so CI/automated runs don't need
    # an interactive prompt.  Fall back to getpass for interactive use.
    password = _load_password_from_env()
    if password:
        print(f"[auth] Password loaded from .env for '{args.username}'.")
    else:
        password = getpass.getpass(f"Password for {args.username}: ")

    # ── Authenticate before touching any GIS endpoint ─────────────────────
    token = get_token(args.username, password)

    high = {v.strip() for v in args.high_pixels.split(",")}
    low  = {v.strip() for v in args.low_pixels.split(",")}

    if args.type == "slope":
        mode_slope(args.count, args.delay, high, low, token)
    else:
        mode_depositional(args.count, args.delay, token)


if __name__ == "__main__":
    main()
