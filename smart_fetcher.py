import os
import string
import sys
from pathlib import Path

import rasterio

# ---------------------------------------------------------------------------
# Platform-aware DEM path resolution
#
# On Linux/Mac the 'Backup Plus' drive mounts at:
#   /run/media/<user>/Backup Plus/
# On Windows it appears as a drive letter (E:\, F:\, etc.) — we scan all
# letters for the expected sub-path so the user doesn't have to configure
# anything as long as the drive is plugged in.
#
# Override either path via environment variables:
#   IFSAR_PATH=/path/to/IfSAR_PH.tif
#   SRTM_PATH=/path/to/SRTM30m.tif
# ---------------------------------------------------------------------------

_DEM_SUBPATH_IFSAR = Path("eil-calc") / "IfSAR" / "IfSAR_PH.tif"
_DEM_SUBPATH_SRTM  = Path("eil-calc") / "SRTM"  / "SRTM30m.tif"


def _linux_mount_roots() -> list[Path]:
    """Candidate mount-point roots on Linux (covers multi-user setups)."""
    roots = []
    media = Path("/run/media")
    if media.exists():
        for user_dir in media.iterdir():
            roots.append(user_dir / "Backup Plus")
    roots.append(Path("/media") / "Backup Plus")
    return roots


def _windows_drive_roots() -> list[Path]:
    """All accessible Windows drive-letter roots (A: through Z:)."""
    return [Path(f"{d}:\\") for d in string.ascii_uppercase]


def _find_on_removable(subpath: Path) -> str | None:
    """Scan platform-appropriate roots and return the first match, or None."""
    if sys.platform == "win32":
        roots = _windows_drive_roots()
    else:
        roots = _linux_mount_roots()

    for root in roots:
        candidate = root / subpath
        if candidate.exists():
            return str(candidate)
    return None


def _resolve_default(env_var: str, subpath: Path) -> str:
    """
    Resolve a DEM path in priority order:
      1. Environment variable (IFSAR_PATH / SRTM_PATH)
      2. Auto-detected removable drive scan
      3. Empty string (will raise FileNotFoundError at access time)
    """
    if env_var in os.environ:
        return os.environ[env_var]
    found = _find_on_removable(subpath)
    return found or ""


# Lazily evaluated at construction time (not import time) so tests that set
# env vars before instantiating SmartFetcher pick them up correctly.
IFSAR_DEFAULT = _resolve_default("IFSAR_PATH", _DEM_SUBPATH_IFSAR)
SRTM_DEFAULT  = _resolve_default("SRTM_PATH",  _DEM_SUBPATH_SRTM)


class SmartFetcher:
    """
    Abstracts DEM sources.
    Priority: Local IfSAR (5 m) > Local SRTM (30 m).

    Both datasets are single nationwide GeoTIFFs — no tile-lookup needed.

    Path resolution order (for each source):
      1. config dict key  ('ifsar_path' / 'srtm_path')
      2. Environment variable (IFSAR_PATH / SRTM_PATH)
      3. Auto-scan of removable drive mount points (Linux) or drive letters (Windows)

    Raises FileNotFoundError if neither source is accessible.
    """

    def __init__(self, config=None):
        self.config = config or {}
        self.ifsar_path = self.config.get("ifsar_path") or \
                          _resolve_default("IFSAR_PATH", _DEM_SUBPATH_IFSAR)
        self.srtm_path  = self.config.get("srtm_path")  or \
                          _resolve_default("SRTM_PATH",  _DEM_SUBPATH_SRTM)

    def fetch_dem_path(self, bounds=None):
        """
        Returns the path to the best available DEM.

        Args:
            bounds: unused — nationwide files cover all of PH.

        Returns:
            (str, str): (path, source_type) where source_type is one of
                        'local_override', 'ifsar', 'srtm'.

        Raises:
            FileNotFoundError: if neither IfSAR nor SRTM file is accessible.
        """
        # Explicit path override — used in tests and one-off runs.
        if "local_dem_path" in self.config:
            path = self.config["local_dem_path"]
            if os.path.exists(path):
                return path, "local_override"
            raise FileNotFoundError(f"local_dem_path override not found: {path}")

        if self.ifsar_path and os.path.exists(self.ifsar_path):
            return self.ifsar_path, "ifsar"

        if self.srtm_path and os.path.exists(self.srtm_path):
            print(f"Warning: IfSAR not found at '{self.ifsar_path}'. Falling back to SRTM (30 m).")
            return self.srtm_path, "srtm"

        drive_hint = (
            "Ensure the 'Backup Plus' drive is connected.\n"
            "  Linux : auto-detected under /run/media/<user>/Backup Plus/\n"
            "  Windows: auto-detected by scanning all drive letters\n"
            "  Override: set IFSAR_PATH and/or SRTM_PATH environment variables"
        )
        raise FileNotFoundError(
            f"No DEM source available. {drive_hint}\n"
            f"  IfSAR expected subpath : {_DEM_SUBPATH_IFSAR}\n"
            f"  SRTM  expected subpath : {_DEM_SUBPATH_SRTM}"
        )

    def validate_resolution(self, dem_path):
        """
        Checks whether the DEM resolution meets the ≤5 m requirement.
        Resolution is read from the file's native CRS units (metres for projected DEMs).
        """
        try:
            with rasterio.open(dem_path) as src:
                res_x, res_y = src.res
                if res_x <= 5.0 and res_y <= 5.0:
                    return True, f"{res_x}m"
                else:
                    return False, f"{res_x}m"
        except Exception:
            return False, "error_reading_file"
