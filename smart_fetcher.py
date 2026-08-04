import os
import string
import sys
from pathlib import Path

import rasterio

from settings import get_settings

# ---------------------------------------------------------------------------
# DEM path resolution
#
# Paths come from the environment (see settings.py):
#
#   EIL_DEM_IFSAR_URI=/srv/eil-data/IfSAR_PH.tif
#   EIL_DEM_SRTM_URI=/srv/eil-data/SRTM30m.tif
#
# Nothing is discovered by scanning the filesystem unless a developer opts in
# with EIL_DEM_ALLOW_REMOVABLE_SCAN=1. The scan used to run at *import* time and
# walked /run/media/<user>/Backup Plus/ plus every Windows drive letter — on a
# server it found nothing and the failure surfaced far from its cause. It is
# also brittle by construction: it matches one hard-coded volume label, so a
# drive labelled anything else is invisible to it even when plugged in.
#
# The legacy IFSAR_PATH / SRTM_PATH variables are still honoured so existing
# local setups keep working; the EIL_-prefixed names win where both are set.
# ---------------------------------------------------------------------------

_DEM_SUBPATH_IFSAR = Path("eil-calc") / "IfSAR" / "IfSAR_PH.tif"
_DEM_SUBPATH_SRTM  = Path("eil-calc") / "SRTM"  / "SRTM30m.tif"


def _listdir(path: Path) -> list[Path]:
    """Children of `path`, or [] if it cannot be read.

    Each directory is guarded separately: /run/media/<other-user> is commonly
    root-owned and unreadable, and one such entry must not abort the walk.
    """
    try:
        return list(path.iterdir())
    except OSError:
        return []


def _linux_mount_roots() -> list[Path]:
    """Candidate removable-mount roots on Linux (covers multi-user setups)."""
    roots = []
    for base in (Path("/run/media"), Path("/media")):
        if not base.exists():
            continue
        for entry in _listdir(base):
            # /run/media/<user>/<label>/ on most desktops, /media/<label>/ on
            # others — try both depths rather than guessing a volume label.
            roots.append(entry)
            roots.extend(_listdir(entry))
    return roots


def _windows_drive_roots() -> list[Path]:
    """All accessible Windows drive-letter roots (A: through Z:)."""
    return [Path(f"{d}:\\") for d in string.ascii_uppercase]


def _find_on_removable(subpath: Path) -> str | None:
    """Scan platform-appropriate roots and return the first match, or None."""
    roots = _windows_drive_roots() if sys.platform == "win32" else _linux_mount_roots()

    for root in roots:
        candidate = root / subpath
        try:
            if candidate.exists():
                return str(candidate)
        except OSError:
            # Inaccessible mount root (e.g. another user's root-owned
            # /run/media/<user> dir). Skip it rather than crash the scan.
            continue
    return None


def _resolve(configured: str, legacy_env_var: str, subpath: Path, allow_scan: bool) -> str:
    """
    Resolve one DEM path in priority order:
      1. Explicit setting (EIL_DEM_*_URI, or a SmartFetcher config key)
      2. Legacy environment variable (IFSAR_PATH / SRTM_PATH)
      3. Removable-drive scan, only when explicitly enabled
      4. Empty string — treated as "not configured" by the caller
    """
    if configured:
        return configured
    if os.environ.get(legacy_env_var):
        return os.environ[legacy_env_var]
    if allow_scan:
        return _find_on_removable(subpath) or ""
    return ""


class SmartFetcher:
    """
    Abstracts DEM sources.
    Priority: Local IfSAR (5 m) > Local SRTM (30 m).

    Both datasets are single nationwide GeoTIFFs — no tile-lookup needed.

    Path resolution order (for each source):
      1. config dict key ('ifsar_path' / 'srtm_path')
      2. Settings / environment (EIL_DEM_IFSAR_URI / EIL_DEM_SRTM_URI)
      3. Legacy environment variable (IFSAR_PATH / SRTM_PATH)
      4. Removable-drive scan, only if EIL_DEM_ALLOW_REMOVABLE_SCAN is set

    Raises FileNotFoundError if neither source is accessible.
    """

    def __init__(self, config=None):
        self.config = config or {}
        settings = get_settings()
        allow_scan = settings.dem_allow_removable_scan

        self.ifsar_path = _resolve(
            self.config.get("ifsar_path") or settings.dem_ifsar_uri,
            "IFSAR_PATH", _DEM_SUBPATH_IFSAR, allow_scan,
        )
        self.srtm_path = _resolve(
            self.config.get("srtm_path") or settings.dem_srtm_uri,
            "SRTM_PATH", _DEM_SUBPATH_SRTM, allow_scan,
        )

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

        raise FileNotFoundError(self.describe_failure())

    def describe_failure(self) -> str:
        """Actionable message naming what was tried and what to set."""
        tried = []
        for label, path in (("IfSAR", self.ifsar_path), ("SRTM", self.srtm_path)):
            if not path:
                tried.append(f"  {label:<5}: not configured")
            else:
                tried.append(f"  {label:<5}: {path} (does not exist)")
        return (
            "No DEM source available.\n"
            + "\n".join(tried)
            + "\n\nSet the DEM locations in the environment:\n"
            "  EIL_DEM_IFSAR_URI=/path/to/IfSAR_PH.tif\n"
            "  EIL_DEM_SRTM_URI=/path/to/SRTM30m.tif\n"
            "Developers using a removable drive may instead set "
            "EIL_DEM_ALLOW_REMOVABLE_SCAN=1 to search mounted volumes for "
            f"'{_DEM_SUBPATH_IFSAR}'."
        )

    def resolved_source(self) -> tuple[str, str] | None:
        """(path, source_type) of the DEM that would be used, or None if none is."""
        try:
            return self.fetch_dem_path()
        except FileNotFoundError:
            return None

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
