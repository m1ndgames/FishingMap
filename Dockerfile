FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

# Install dependencies first so this layer is cached unless the lockfile changes
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

# App code
COPY . .
RUN uv sync --frozen

EXPOSE 5000

CMD ["uv", "run", "python", "app.py"]
