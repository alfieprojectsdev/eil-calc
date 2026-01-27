Here is the consolidated **Technical Specification** and **Architecture Decision Record (ADR)** package for the EIL-Calc project. This document serves as the "Blueprints" for the implementation.

---

# Part 1: Technical Specification (EIL-Calc)

**Version:** 1.0.0
**Status:** Approved for Prototyping
**Owner:** Geomatics / GGRDD

## 1. System Overview

**EIL-Calc** is a headless geoprocessing engine designed to automate the certification of Earthquake-Induced Landslide (EIL) hazards for individual land parcels. It replaces manual GIS profiling with a reproducible, two-phase algorithmic pipeline.

## 2. Architecture

The system follows a modular "Pipe and Filter" architecture using Python 3.9+.

* **Orchestrator:** Manages data ingestion and module execution.
* **Layer 1 (Data):** "Smart-Fetcher" abstracts DEM sources (Local IfSAR > Cloud SRTM).
* **Layer 2 (Core Logic):**
* *Module A:* Slope Stability (Zonal Statistics).
* *Module B:* Depositional Safety (Geometric Runout).


* **Layer 3 (Advanced/Hybrid):** Landlab Physics Engine + XGBoost Error Correction.
* **Output:** JSON Assessment Object + PDF Report Generation.

## 3. Data Flow Specification

### 3.1 Input Schema

The system accepts a payload defining the site and assessment parameters.

```json
{
  "project_id": "UUID-v4",
  "geometry": { "type": "Polygon", "coordinates": [...] }, // GeoJSON
  "config": {
    "dem_source": "auto", // or 'local_ifsar', 'srtm'
    "mode": "compliance", // or 'research' (triggers Phase 2)
    "buffer_search_m": 1000
  }
}

```

### 3.2 Processing Logic (Phase 1: Compliance)

**A. Slope Analysis Module**

* **Operation:** Mask DEM to Parcel Geometry  Calculate Gradient.
* **Constraint:** Resolution must be  (IfSAR) where available.
* **Threshold:**
* : **SAFE**
* : **FLAG FOR REVIEW** (Buffer Zone)
* : **SUSCEPTIBLE**



**B. Depositional Zone Module**

* **Operation:** Identify local maxima (Peak) within `buffer_search_m`.
* **Formula:** Euclidean Distance () vs. Elevation Delta ().
* **Threshold:**
* : **SAFE (Beyond Runout)**
* : **PRONE**



### 3.3 Processing Logic (Phase 2: Hybrid Scientific)

* **Physics Engine:** `Landlab.components.ShallowLandslider`.
* *Input:*  (Cohesion),  (Friction Angle),  (Soil Density), PGA (Seismic).
* *Output:* Factor of Safety ().


* **ML Correction:** `XGBoost` Regressor.
* *Input:* Topographic Roughness, Curvature, Distance to Fault.
* *Target:* Residual error between  and historical inventory data.



---

# Part 2: Architecture Decision Records (ADR)

## ADR 001: Adoption of Python Ecosystem over ArcPy/QGIS

**Status:** Accepted
**Context:**
The current workflow relies on Google Earth (Manual) or desktop GIS software (ArcGIS/QGIS). We need a solution that can run as a backend service (Headless) and integrate with modern ML libraries.
**Decision:**
We will build EIL-Calc using the **standard Scientific Python Stack** (`Rasterio`, `ShallowLandslider`, `NumPy`, `XGBoost`).
**Consequences:**

* (+) **Positives:** Free, open-source, easy to dockerize, direct access to ML libraries.
* (-) **Negatives:** Geologists accustomed to GUI-based ArcMap may find the CLI/Script interface difficult initially (Requires building a simple Web UI later).

## ADR 002: Implementation of Deterministic Thresholds for Phase 1

**Status:** Accepted
**Context:**
EIL certification is a legal compliance document. Using probabilistic models (e.g., "78% chance of failure") is difficult to regulate and defend in court.
**Decision:**
Phase 1 will strictly replicate the **binary deterministic logic** currently used in manual assessment (Slope > X, Runout > Y).
**Consequences:**

* (+) **Positives:** Legally defensible, transparent, fully backward-compatible with existing PHIVOLCS guidelines.
* (-) **Negatives:** Ignores nuance; "Hard thresholds" (e.g., 15.1 degrees) can lead to edge-case disputes (Mitigated by the "Review Buffer" implemented in Spec 3.2).

## ADR 003: Selection of "Hybrid" Model over Pure Deep Learning

**Status:** Accepted
**Context:**
Modern computer vision (CNNs) can detect landslides from satellite imagery. However, deep learning models are "Black Boxes" and require massive training datasets of labeled landslide polygons, which are scarce at the parcel level in the Philippines.
**Decision:**
We will use a **Physically-Guided ML Approach** (Hybrid). We run the Newmark Physics model first, then use XGBoost to correct its errors based on terrain features.
**Consequences:**

* (+) **Positives:**
* **Explainable:** We can show the physics equation () as the primary driver.
* **Data-Efficient:** Requires significantly less training data than CNNs.
* **Aligned:** Matches the 2024 global research trend (Yang et al.).


* (-) **Negatives:** Requires managing two distinct logic pipelines (Physics + ML).

## ADR 004: Priority of IfSAR Data with SRTM Fallback

**Status:** Accepted
**Context:**
Parcel-level assessment requires detecting micro-topography (e.g., a 3-meter cut slope) which SRTM (30m resolution) blurs out. However, IfSAR coverage is not 100% nationwide.
**Decision:**
The system will implement a "Waterfall" fetcher. It *must* attempt to locate local 5m IfSAR data first. If unavailable, it falls back to SRTM-30 but appends a **"Low Confidence/Resolution Warning"** to the final report.
**Consequences:**

* (+) **Positives:** Ensures highest accuracy where possible while maintaining system uptime.
* (-) **Negatives:** Results for adjacent lots may differ significantly if one falls on the edge of IfSAR coverage (Edge artifact risk).
