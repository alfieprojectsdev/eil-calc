import logging
from contextlib import asynccontextmanager
from typing import Any, Optional, Union

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from shapely.geometry import shape

from health import DemProbe
from orchestrator import EILOrchestrator
from settings import get_settings
from smart_fetcher import SmartFetcher

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Resolve the DEM once, at startup, and refuse to start without one.

    A misconfigured DEM path is a deployment error, not a per-request error.
    Failing here surfaces it in `systemctl status` on the first start, instead
    of as a 503 the first time an assessor submits a parcel.
    """
    fetcher = SmartFetcher()
    resolved = fetcher.resolved_source()
    if resolved is None:
        raise RuntimeError(fetcher.describe_failure())
    path, source_type = resolved
    logger.info("DEM resolved at startup: %s (%s)", path, source_type)
    # /readyz reports what startup resolved rather than re-deriving it, so the
    # two answers cannot drift apart.
    app.state.dem_probe = DemProbe(path=path, source_type=source_type)
    yield


app = FastAPI(
    title="EIL-Calc API",
    description="HTTP API for Earthquake-Induced Landslide hazard certification",
    version="1.0.0",
    lifespan=lifespan,
)

# Normally empty: one reverse proxy serves the SPA and proxies /api/ to this
# process, and `npm run dev` proxies through Vite — both same-origin. Set
# EIL_CORS_ALLOW_ORIGINS only if something really does call in cross-origin.
if settings.cors_allow_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------

class AssessmentRequest(BaseModel):
    project_id: str
    geometry: dict[str, Any]
    config: dict[str, Any] = {"mode": "compliance"}


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class ErrorResult(BaseModel):
    error: str


class SlopeMetricsResponse(BaseModel):
    max_slope_degrees: float
    avg_slope_degrees: float


class SlopeAssessmentResponse(BaseModel):
    status: str
    threshold_used: str


class SlopeStabilityResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    metrics: SlopeMetricsResponse
    assessment: SlopeAssessmentResponse
    viz_grid: list[list[Optional[float]]] = Field(alias="_viz_grid")


class DepositionalMetricsResponse(BaseModel):
    elevation_peak: float
    elevation_site: float
    delta_e: float
    horizontal_distance_h: float
    required_runout_3x: float


class DepositionalAssessmentResponse(BaseModel):
    status: str
    is_compliant: bool


class TransectPathPoint(BaseModel):
    dist_m: float
    elev_m: float


class TransectResponse(BaseModel):
    metrics: DepositionalMetricsResponse
    assessment: DepositionalAssessmentResponse
    path: list[TransectPathPoint]
    threat_ratio: float


class DepositionalHazardResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    metrics: DepositionalMetricsResponse
    assessment: DepositionalAssessmentResponse
    viz_transects: list[TransectResponse] = Field(alias="_viz_transects")


class Phase1ComplianceResponse(BaseModel):
    slope_stability: Union[SlopeStabilityResponse, ErrorResult]
    depositional_hazard: Union[DepositionalHazardResponse, ErrorResult]
    overall_status: str


class AssessmentResponse(BaseModel):
    project_id: str
    data_source: str
    phase_1_compliance: Phase1ComplianceResponse
    phase_2_scientific: Optional[Any] = None
    final_decision: str


# ---------------------------------------------------------------------------
# Operational endpoints
#
# Excluded from the OpenAPI schema: these are for the proxy and the init
# system, not part of the assessment contract ADR-002 governs.
# ---------------------------------------------------------------------------

@app.get("/healthz", include_in_schema=False)
async def healthz():
    """Liveness — is this process up and is the event loop still turning?

    Deliberately touches nothing external: no filesystem, no DEM. Whatever
    consumes this (systemd `Restart=on-failure`, a container liveness probe)
    should only ever be told "this process is wedged, restart it" — never
    "a mount you do not control went away", which restarting cannot fix.
    """
    return {"status": "ok"}


@app.get("/readyz", include_in_schema=False)
async def readyz():
    """Readiness — should the proxy send this instance real traffic?

    A strictly stronger question than liveness, and here it means one thing:
    is the DEM readable *right now*. `/srv/eil-data` is a separate LV mounted
    `nofail`, so it can vanish under a long-running process; that is exactly
    the case this exists to catch.

    Returns 503 rather than raising, so the reason is visible in `curl` output
    and in the nginx error log.
    """
    probe = getattr(app.state, "dem_probe", None)
    if probe is None:
        # Only reachable if startup has not finished — the lifespan hook either
        # sets this or refuses to start the process at all.
        return JSONResponse(
            status_code=503,
            content={"status": "not ready", "reason": "startup has not completed"},
        )

    result = await probe.check()
    if not result.ready:
        logger.warning("Readiness check failed: %s", result.reason)
        return JSONResponse(
            status_code=503,
            content={"status": "not ready", "reason": result.reason},
        )

    return {
        "status": "ready",
        "dem": {"path": probe.path, "source": probe.source_type},
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/api/v1/assess", response_model=AssessmentResponse, response_model_by_alias=True)
def assess_parcel(request: AssessmentRequest):
    """
    Run the EIL hazard assessment on the provided GeoJSON polygon.
    """
    try:
        # Validate the geometry can be parsed
        geom = shape(request.geometry)
        if not geom.is_valid:
            raise ValueError("Geometry is invalid (self-intersecting or poorly structured)")
    except Exception as e:
        logger.error(f"Invalid GeoJSON: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid GeoJSON geometry: {str(e)}")

    payload = {
        "project_id": request.project_id,
        "geometry": request.geometry,
        "config": request.config,
    }

    try:
        orc = EILOrchestrator()
        result = orc.run_assessment(payload)
        return result
    except FileNotFoundError as e:
        logger.error(f"DEM Data Missing: {e}")
        raise HTTPException(status_code=503, detail=f"DEM Data Missing: {str(e)}")
    except Exception as e:
        logger.exception("Assessment failed")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    # Make sure to run the server from the `packages/eil-calc` directory.
    # Host/port/reload come from EIL_HOST / EIL_PORT / EIL_RELOAD; the defaults
    # bind loopback with reload off, which is what the deployment wants.
    uvicorn.run(
        "api:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
    )
