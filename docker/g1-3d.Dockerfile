# syntax=docker/dockerfile:1
#
# G1 3D authoring console image (UI on :8000, Viser on :8001).
#
# Build from the repository root:
#   docker build -f docker/g1-3d.Dockerfile -t g1-3d .
#
# Run:
#   docker run --rm \
#     -e BYTEPLUS_API_KEY=... \
#     -p 8000:8000 -p 8001:8001 \
#     g1-3d

FROM ghcr.io/astral-sh/uv:python3.10-bookworm-slim

# Node/npm are required at runtime for Tailwind + daisyUI CSS rebuilds.
COPY --from=node:22-bookworm-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=node:22-bookworm-slim /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -sf /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -sf /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

# MuJoCo EGL headless rendering libraries.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        libegl1 \
        libgl1 \
        libgomp1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    MUJOCO_GL=egl \
    G1_3D_HOST=0.0.0.0 \
    G1_3D_PORT=8000 \
    VISER_HOST=0.0.0.0 \
    VISER_PORT=8001

# Install Python dependencies first for better layer caching.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

# Install frontend build tooling used by TailwindAssetHelper.
COPY package.json package-lock.json ./
RUN npm ci

# Install the project itself after the full source tree is present.
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

ENV PATH="/app/.venv/bin:$PATH"

COPY docker/g1-3d-entrypoint.sh /usr/local/bin/g1-3d-entrypoint.sh
RUN chmod +x /usr/local/bin/g1-3d-entrypoint.sh

EXPOSE 8000 8001

# Require BYTEPLUS_API_KEY at container start, then launch the console.
ENTRYPOINT ["/usr/local/bin/g1-3d-entrypoint.sh"]
CMD ["uv", "run", "python", "app/g1_3d_main.py"]
