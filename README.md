# EIL-Calc: Earthquake-Induced Landslide Calculator

**EIL-Calc** is a headless geoprocessing engine designed to automate the certification of Earthquake-Induced Landslide (EIL) hazards for individual land parcels. It serves as a backend service that abstracts DEM data acquisition and runs compliance-grade geometric algorithms.

## Features

- **Smart Data Fetcher:** Prioritizes local, high-resolution IfSAR (5m) data and falls back to SRTM 30m if unavailable.
- **Compliance Module (Phase 1):**
    - **Slope Stability:** Calculates maximum gradient to flag SAFE vs. SUSCEPTIBLE zones.
    - **Depositional Safety:** Analyzes runout zones using the geometric shadow angle separation (H > 3 * Delta_E).
- **Hybrid Architecture (Phase 2 - Planned):** Future integration of Physically-Guided ML (Landlab + XGBoost). See RFC for details.
- **Orchestrator:** Single entry-point for managing the full assessment pipeline.

## Installation

This project uses `uv` for dependency management.

```bash
# Install uv (if not installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone repository
git clone https://github.com/alfieprojectsdev/eil-calc.git
cd eil-calc

# Install dependencies
uv sync
```

## Usage

### Running Tests
Verify the installation and logic:

```bash
uv run python -m unittest test_orchestrator.py
uv run python -m unittest test_eil_calc.py
```

### Running the Orchestrator (Example)
You can run the orchestrator script directly to see a mock assessment:

```bash
uv run python orchestrator.py
```

## Project Structure

- `orchestrator.py`: Main entry point.
- `smart_fetcher.py`: Data abstraction layer.
- `slope_stability.py`: Core logic for slope hazards.
- `calculate_depositional_safety.py`: Core logic for depositional/runout hazards.
- `RFC_001-EIL-CALC.md`: Technical Specifications, ADRs, and RFC documentation.

## License
Proprietary / Internal Use Only.
