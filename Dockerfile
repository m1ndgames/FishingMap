FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

# rasterio's manylinux wheel bundles GDAL/GEOS/PROJ but dynamically links against
# the system libexpat/libgomp, which bookworm-slim doesn't include by default.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libexpat1 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first so this layer is cached unless the lockfile changes
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

# App code
COPY . .
RUN uv sync --frozen

EXPOSE 5000

CMD ["uv", "run", "python", "app.py"]
