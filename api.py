import logging
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
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


class AssessmentRequest(BaseModel):
    project_id: str
    geometry: Dict[str, Any]
    config: Dict[str, Any] = {"mode": "compliance"}


@app.post("/api/v1/assess", response_model=Dict[str, Any])
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
