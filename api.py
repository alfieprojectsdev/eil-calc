import logging
from typing import Any, Optional, Union

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field
from shapely.geometry import shape

from orchestrator import EILOrchestrator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="EIL-Calc API",
    description="HTTP API for Earthquake-Induced Landslide hazard certification",
    version="1.0.0",
)

# Allow CORS for local dev servers (e.g., Vite on 5173)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000"],
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
    # Make sure to run the server from the `packages/eil-calc` directory
    uvicorn.run("api:app", host="127.0.0.1", port=8000, reload=True)
