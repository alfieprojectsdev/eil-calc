import os
import rasterio

class SmartFetcher:
    """
    Abstracts DEM sources. 
    Prioritizes Local IfSAR (5m) > Cloud SRTM (30m).
    """

    def __init__(self, config=None):
        self.config = config or {}
        self.preferred_source = self.config.get('dem_source', 'auto')
        # In a real app, these paths would be in config or env vars
        self.local_ifsar_path = "/data/ifsar/philippines/" 
        self.srtm_fallback_url = "https://srtm-source.example.com/api" # Mock URL

    def fetch_dem_path(self, bounds):
        """
        Locates the best available DEM for the given bounds.
        
        Args:
            bounds (tuple): (minx, miny, maxx, maxy)
        
        Returns:
            str: Path or URL to the DEM.
            str: Metadata/Source type ('ifsar', 'srtm', 'srtm-fallback').
        """
        
        # 1. Check Local specific path override (for testing)
        if 'local_dem_path' in self.config:
            if os.path.exists(self.config['local_dem_path']):
                return self.config['local_dem_path'], 'local_override'
        
        # 2. Logic to search for IfSAR tiles covering these bounds
        # (Mock implementation: Checking if a file exists in updated structure)
        # For prototype, we might just assume if a file is passed in config it's the one.
        
        # 3. Fallback
        print("Warning: High-res IfSAR not found (Mock). Falling back to global SRTM.")
        return "mock_srtm_30m.tif", "srtm_30m_fallback"

    def validate_resolution(self, dem_path):
        """
        Checks if resolution meets the < 5m requirement for certain modules.
        """
        try:
            with rasterio.open(dem_path) as src:
                res_x, res_y = src.res
                # Assuming meters
                if res_x <= 5.0 and res_y <= 5.0:
                    return True, f"{res_x}m"
                else:
                    return False, f"{res_x}m"
        except Exception as e:
            return False, "error_reading_file"
