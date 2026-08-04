"""Runtime configuration for eil-calc.

Everything that varies between a developer's laptop and the deployment host
lives here and is read from the environment. Two things deliberately do *not*:

* **Hazard thresholds** (14° / 16° / 1.5% / 10%). They change only after review,
  and a change must be visible in a diff and attributable to a commit. They stay
  in ``eil_status.py``.
* **DEM discovery by filesystem scan.** The old ``smart_fetcher`` scanned
  ``/run/media/*/Backup Plus/`` and every Windows drive letter *at import time*.
  On a server that finds nothing and fails opaquely long before the request that
  needed it. The DEM now comes from the environment; the scan survives only as
  an opt-in developer convenience (``EIL_DEM_ALLOW_REMOVABLE_SCAN``).
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="EIL_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- DEM sources ---------------------------------------------------------
    # Absolute paths to the two nationwide GeoTIFFs. IfSAR (5 m) is preferred;
    # SRTM (30 m) is the fallback. Empty means "not configured".
    dem_ifsar_uri: str = ""
    dem_srtm_uri: str = ""

    # Developer escape hatch: scan removable-drive mount points for the DEMs
    # when neither URI is set. Off by default so a server never does it.
    dem_allow_removable_scan: bool = False

    # --- HTTP ----------------------------------------------------------------
    # Origins allowed to call the API cross-origin. Empty is correct for the
    # deployment topology, where one reverse proxy serves the SPA and proxies
    # /api/ to this process, and for `npm run dev`, which proxies through Vite.
    # Populate it only if something genuinely calls the API from another origin.
    cors_allow_origins: list[str] = []

    # Bind address for `python api.py` / the container entrypoint. Loopback by
    # default: the reverse proxy is the only thing that should reach uvicorn.
    host: str = "127.0.0.1"
    port: int = 8000
    reload: bool = False


@lru_cache
def get_settings() -> Settings:
    """Process-wide settings singleton.

    Cached so that reading configuration is free at any call site. Tests that
    need to vary the environment should call ``get_settings.cache_clear()``.
    """
    return Settings()
