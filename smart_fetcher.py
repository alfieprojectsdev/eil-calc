import os
import rasterio

# Default paths — single nationwide GeoTIFFs on the 'Backup Plus' external drive.
# Drive mount point: /run/media/finch/Backup Plus/
IFSAR_DEFAULT = "/run/media/finch/Backup Plus/eil-calc/IfSAR/IfSAR_PH.tif"
SRTM_DEFAULT  = "/run/media/finch/Backup Plus/eil-calc/SRTM/SRTM30m.tif"


class SmartFetcher:
    """
    Abstracts DEM sources.
    Priority: Local IfSAR (5m) > Local SRTM (30m).

    Both datasets are single nationwide GeoTIFFs — no tile-lookup needed.
    Raises FileNotFoundError if neither source is accessible (e.g. drive not mounted).
    """

    def __init__(self, config=None):
        self.config = config or {}
        self.ifsar_path = self.config.get('ifsar_path', IFSAR_DEFAULT)
        self.srtm_path  = self.config.get('srtm_path',  SRTM_DEFAULT)

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
        if 'local_dem_path' in self.config:
            path = self.config['local_dem_path']
            if os.path.exists(path):
                return path, 'local_override'
            raise FileNotFoundError(f"local_dem_path override not found: {path}")

        if os.path.exists(self.ifsar_path):
            return self.ifsar_path, 'ifsar'

        if os.path.exists(self.srtm_path):
            print(f"Warning: IfSAR not found at '{self.ifsar_path}'. Falling back to SRTM (30m).")
            return self.srtm_path, 'srtm'

        raise FileNotFoundError(
            "No DEM source available. Ensure the 'Backup Plus' drive is mounted.\n"
            f"  IfSAR expected : {self.ifsar_path}\n"
            f"  SRTM  expected : {self.srtm_path}"
        )

    def validate_resolution(self, dem_path):
        """
        Checks whether the DEM resolution meets the ≤5m requirement.
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
