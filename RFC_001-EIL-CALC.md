Here is the comprehensive, fully compiled **Request for Comments (RFC)** document. It integrates the core proposal, technical specifications, architecture decisions (ADR), and the cross-divisional glossary into a single professional artifact.

---

# RFC: Automated Earthquake-Induced Landslide (EIL) Assessment Engine ("EIL-Calc")

| Meta Data | Details |
| --- | --- |
| **RFC ID** | 001-EIL-CALC |
| **Status** | Draft / Request for Comments |
| **Date** | January 28, 2026 |
| **Target Audience** | PHIVOLCS GGRDD (Geology, Geophysics & RDD), Geomatics Team |
| **Topic** | Automating EIL Certification & Hazard Mapping |

---

## 1. Abstract

This document proposes the architecture for **"EIL-Calc,"** a Python-based geoprocessing engine designed to replace manual Google Earth profile "slicing" with a reproducible, algorithmic workflow. The goal is to standardize site-specific hazard assessments by processing GeoJSON parcel data against high-resolution Digital Elevation Models (DEMs).

We are seeking feedback on the validity of the proposed algorithms, specifically the transition from current deterministic thresholds to a **Hybrid Physically-Based/ML** model (Newmark + XGBoost) that aligns with modern geostatistical literature.

## 2. Motivation & Strategic Alignment

While PHIVOLCS currently employs the **REDAS (Rapid Earthquake Damage Assessment System)** methodology for regional-scale hazard estimation, there is a gap in applying these physics-based principles to **parcel-level certification**.

Current certification relies on manual slope profiling, which is subjective and labor-intensive. This proposal aims to bridge that gap by implementing a **"Micro-Newmark"** analysis:

* **Alignment:** Utilizes the same **Newmark Sliding Block** theoretical framework used in REDAS (Bautista et al.).
* **Innovation:** Transitions from regional scenario modeling to deterministic, lot-specific compliance using high-resolution IfSAR data.
* **Modernization:** Adopts the 2024 global trend of **"Hybrid" modeling**—using Machine Learning to refine physics-based predictions rather than replacing them (Jibson, 2011; Yang et al., 2024).

---

## 3. System Architecture & Tech Stack

The system follows a modular "Pipe and Filter" architecture to run as a headless backend service.

* **Runtime:** Python 3.11+ (Managed via `uv` for high-performance dependency resolution).
* **Orchestrator:** Manages data ingestion (GeoJSON) and module execution.
* **Layer 1 (Data):** "Smart-Fetcher" abstracts DEM sources (Local IfSAR > Cloud SRTM).
* **Layer 2 (Core Logic):**
  * *Module A:* Slope Stability (Zonal Statistics).
  * *Module B:* Depositional Safety (Geometric Runout).
* **Layer 3 (Advanced/Hybrid):** Landlab Physics Engine + XGBoost Error Correction.

### 3.1 Data Requirements

To automate the Newmark calculation, the system requires digital access to the **Philippine Earthquake Model (PEM)**.

* **Requirement:** Access to the 2017 PEM (or latest) in **Raster (GeoTIFF)** or **Vector (Shapefile)** format.
* **Constraint:** Visual reference maps (PDFs) are insufficient for algorithmic processing. If a digital API is unavailable, the Geomatics team will need to internally rasterize the official probabilistic hazard maps to create a static lookup library for the engine.

---

## 4. Phase 1: The Core Deliverable (Compliance Engine)

*Objective: Replicate the current manual PHIVOLCS decision logic using automated zonal statistics to achieve an MVP (Minimum Viable Product).*

### 4.1 Component A: Zonal Slope Analysis

Instead of a single profile line, this module analyzes every pixel within the parcel to catch micro-topographic hazards.

* **Input:** 5m IfSAR DEM.
* **Algorithm:** Calculate gradient vectors ($dz/dx$, $dz/dy$) using `NumPy`/`RichDEM` to derive slope in degrees.
* **Decision Logic:**

$$
Slope_{\max} \leq 14.0\degree : \textbf{SAFE}
$$

$$
14\degree \leq Slope_{\max} \leq 16\degree : \textbf{FLAG FOR REVIEW (Buffer Zone)}
$$

$$
Slope_{\max} > 16\degree : \textbf{SUSCEPTIBLE}
$$

### 4.2 Component B: Depositional Zone Calculator

Automates the geometric safety formula relative to mountain peaks/catchments.

* **Algorithm:**
  1. Identify **Peak** ($P$): Highest pixel value in the immediate catchment/vicinity buffer.
  2. Identify **Site** ($S$): Lowest pixel value within the target polygon.
  3. Calculate **Elevation Difference** ($\Delta E = E_{\max} - E_{\min}$).
  4. Calculate **Horizontal Distance** ($H$) using Euclidean distance between $P$ and $S$.

* **Decision Logic:**

$$
\text{If} \text{H} > 3 \cdot \Delta E \Longrightarrow \text{Status: Safe (Beyond Runout)}
$$

$$
\text{Else} \Longrightarrow \text{Status: Prone}
$$

---

## 5. Phase 2: Hybrid Physically-Based/ML Ensemble

*Objective: Move beyond simple slope thresholds to a "Grey Box" model that combines soil physics with data-driven validation.*

### 5.1 The Physics Engine (Newmark via Landlab)

Instead of static slope thresholds, we will simulate the **Factor of Safety ($F_s$)** under seismic loading.

* **Method:** Newmark Sliding Block analysis (Standard REDAS approach).
* **Implementation:** Use the **Landlab** Python toolkit to model transient pore-water pressure and Critical Acceleration ($a_c$) across the DEM grid.
* **Input:** PGA from PEM Grids + Soil parameters ($C$, $\phi$) derived from local surrogates.

### 5.2 The ML Correction Layer (Hybrid Approach)

Pure physics models often fail in complex terrain due to parameter uncertainty. We propose a **Residual Correction Model**:

* **Algorithm:** **XGBoost** or **Random Forest**.
* **Role:** The ML model does *not* predict landslides directly (avoiding the "Black Box" problem); it predicts the *error* in the Newmark model based on topographic signatures (Curvature, Aspect, Roughness).
* **Precedent:** This "Physically-Guided ML" approach has been shown to outperform pure ML models in recent studies (e.g., *Yang et al., 2024*).

---

## 6. Architecture Decision Records (ADR)

| ID | Title | Context & Decision |
| --- | --- | --- |
| **001** | **Python Stack** | **Decision:** Use the standard scientific stack (`Rasterio`, `Landlab`, `NumPy`) over proprietary ArcPy. **Reasoning:** Enables headless execution, Docker containerization, and access to modern ML libraries. |
| **002** | **Deterministic Logic** | **Decision:** Phase 1 will strictly replicate binary logic ($> 15\degree$) rather than probabilistic outputs. **Reasoning:** Legal compliance requires defensible, binary certification (Safe/Unsafe), not probabilities. |
| **003** | **Hybrid Model** | **Decision:** Use ML only for *residual correction* of the physics model. **Reasoning:** Pure ML requires too much labeled training data; Physics-first ensures explainability for geologists. |
| **004** | **Static Grid Data** | **Decision:** Ingest PEM/PGA data as static local rasters rather than live API calls. **Reasoning:** Certification requires the official 475-year return period baseline, not real-time event data. |

---

## 7. Request for Comments (Specific Feedback Needed)

We specifically need feedback on the following operational and scientific points:

1. **Threshold Validity:** Is the strictly binary $15\degree$ cutoff sufficient for an automated MVP, or is the proposed **Review Buffer** ($14\degree - 16\degree$) necessary for safety?
2. **Peak Identification:** For the Depositional Zone calculator, is a simple radius search sufficient, or do we need to strictly delineate the HUC-12 hydrological catchment first?
3. **Data Access:** Can the Seismology Division provide the 2017 PEM in GeoTIFF format for internal ingestion?
4. **Acceptance:** Would a generated PDF report from this engine be legally sufficient for certification, provided it includes the raw calculation logs?

---

## 8. Selected References

1. **Bautista, B. C., et al.** (2002). *The REDAS Software: Rapid Earthquake Damage Assessment System.* PHIVOLCS.
2. **Jibson, R. W.** (2011). "Methods for assessing the stability of slopes during earthquakes." *Engineering Geology*.
3. **Castillo, L. A., et al.** (2023). "Seismic-induced landslide hazard analysis... Makiling Botanic Gardens." *The Palawan Scientist*.
4. **Yang, Y., et al.** (2024). "Dynamic Earthquake-Induced Landslide Susceptibility Assessment Model." *Remote Sensing*.

---

# Appendix A: Technical Glossary & Contextual Guide

### **Newmark Sliding Block Analysis**

* **Relevance:** Seismology / Geotech
* **Definition:** A method to estimate slope displacement during an earthquake. It treats a landslide mass as a rigid block sliding on an inclined plane.
* **Key Parameter:** **Critical Acceleration ($a_c$)**. If the ground shaking (PGA) exceeds $a_c$, the block "slides." This is the core logic of **REDAS**.

### **Residual Correction (ML)**

* **Relevance:** Data Science
* **Definition:** A "Hybrid" technique where ML predicts the *error* of a physics model rather than the outcome itself.
* **Logic:** If the Physics Model calculates $F_s > 1$ (Safe) but a landslide occurred, the ML model learns to correct that specific error based on terrain features (e.g., curvature).

### **IfSAR vs. SRTM**

* **SRTM (30m):** Standard global data. Too coarse for parcel-level analysis (misses small creeks).
* **IfSAR (5m):** High-resolution airborne radar. Required for this project to detect micro-topography (cut slopes) effectively.

### **Seismic Loading Input (PGA)**

* **Relevance:** Seismology
* **Definition:** **Peak Ground Acceleration**. The maximum shaking experienced at a site.
* **Source:** **Philippine Earthquake Model (PEM)** or **REDAS-generated Ground Shaking Scenarios**.
* **Usage:** Serves as the "Driving Force" in the Factor of Safety equation:

$$
k_h = \frac{\text{PGA}}{\text{g}} \times f_{amp}
$$

Where $k_h$ is the horizontal seismic coefficient derived from PGA.
