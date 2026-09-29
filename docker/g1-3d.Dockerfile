# syntax=docker/dockerfile:1
#
# G1 Concierge Studio image (UI on :8000, robot Viser on :8001, map Viser on :8002).
#
# Build from the repository root (linux/amd64 for Harbor / Kubernetes nodes):
#   docker build --platform linux/amd64 -f docker/g1-3d.Dockerfile \
#     -t harbor.chs.gto-stc-aida.com/sysadmin-pub/g1-3d:<TAG> .
#
# Run:
#   docker run --rm \
#     -e BYTEPLUS_API_KEY=... \
#     -p 8000:8000 -p 8001:8001 -p 8002:8002 \
#     harbor.chs.gto-stc-aida.com/sysadmin-pub/g1-3d:<TAG>
#
# Behind a reverse proxy / Ingress where Viser has its own public hostname:
#   -e VISER_PUBLIC_URL=https://g1-3d-viser.example.com
#   -e MAP_VISER_PUBLIC_URL=https://g1-3d-map-viser.example.com

FROM ghcr.io/astral-sh/uv:python3.10-bookworm-slim

# MuJoCo EGL headless rendering libraries; build-essential compiles python-lzf (no Linux wheel).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
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
    G1_RECORDER_HOST=0.0.0.0 \
    G1_RECORDER_PORT=8000 \
    G1_RECORDER_VISER_HOST=0.0.0.0 \
    G1_RECORDER_VISER_PORT=8001 \
    G1_RECORDER_MAP_VISER_HOST=0.0.0.0 \
    G1_RECORDER_MAP_VISER_PORT=8002

# Install Python dependencies first for better layer caching.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

# Install the project itself after the full source tree is present.
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

ENV PATH="/app/.venv/bin:$PATH"

COPY docker/g1-3d-entrypoint.sh /usr/local/bin/g1-3d-entrypoint.sh
RUN chmod +x /usr/local/bin/g1-3d-entrypoint.sh

EXPOSE 8000 8001 8002

# Require BYTEPLUS_API_KEY at container start, then launch the console.
ENTRYPOINT ["/usr/local/bin/g1-3d-entrypoint.sh"]
CMD ["uv", "run", "python", "app/main.py"]
