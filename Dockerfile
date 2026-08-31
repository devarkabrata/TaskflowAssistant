# --- Build stage: resolve/install dependencies with uv ---
FROM python:3.14-slim AS builder

# Python 3.14 is very recent — some dependencies may not yet ship prebuilt
# wheels for it, forcing a source build. Keep build tools in this stage only;
# they are never copied into the final runtime image.
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies first, in their own layer — only invalidated when
# pyproject.toml/uv.lock actually change, not on every source-code edit.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Now install the project itself.
COPY . .
RUN uv sync --frozen --no-dev

# --- Runtime stage: just the built venv + source, no compilers ---
FROM python:3.14-slim

WORKDIR /app
COPY --from=builder /app /app

ENV PATH="/app/.venv/bin:$PATH"

# Render assigns the actual port via $PORT at runtime — taskflow-agent
# (src/taskflowassistant/main.py) already reads that and binds 0.0.0.0.
CMD ["taskflow-agent"]
