FROM python:3.11-slim

# rasterio ships GDAL inside its wheel, but that GDAL still dynamically links
# against a few system libraries that python:3.11-slim does not carry. Without
# libexpat1 the image builds fine and then dies on `import rasterio` at startup.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libexpat1 \
    && rm -rf /var/lib/apt/lists/*

# uv, pinned so an image rebuilt months from now resolves the same way.
COPY --from=ghcr.io/astral-sh/uv:0.9.15 /uv /uvx /bin/

WORKDIR /app

# Dependency layer first, so application edits do not re-resolve the tree.
COPY pyproject.toml uv.lock ./

# `uv sync --system` is not a thing — --system belongs to `uv pip`. uv sync
# always manages a venv, so create it in-image and put it on PATH. --frozen
# makes the build fail loudly if uv.lock has drifted from pyproject.toml
# instead of silently resolving something else.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN uv sync --frozen --no-dev --no-install-project

# Application code. See .dockerignore — .env must never land here.
COPY . .

# Drop privileges. Nothing in the app writes to its own directory, and the DEM
# volume is mounted read-only.
RUN useradd --create-home --uid 10001 eilcalc && chown -R eilcalc:eilcalc /app
USER eilcalc

# Configuration comes from the environment; see .env.example. The DEM paths are
# required — the process refuses to start without a readable DEM.
ENV EIL_HOST=0.0.0.0
ENV EIL_PORT=8000

EXPOSE 8000

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
