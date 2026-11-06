# Packwright — the build server and everything its builds need, in one image.
#
#   docker compose up -d          # see docker-compose.yml
#
# Everything Packwright keeps (database, generated secrets, clones, outputs,
# exported images, the compile cache) lives under /data: mount a volume there.
# Builds run as the unprivileged user "packwright" (uid 1000). Read SECURITY.md:
# anyone who can start a build can run code inside this container.

# ---- Console (React) ---------------------------------------------------------
FROM node:22-bookworm-slim AS console
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# prebuild syncs the version shown in the console from ../pyproject.toml.
COPY pyproject.toml /src/pyproject.toml
RUN npm run build

# ---- Tools copied in as single binaries --------------------------------------
FROM ghcr.io/astral-sh/uv:0.13.7 AS uv
FROM docker:27-cli AS dockercli
FROM node:22-bookworm-slim AS node

# ---- Runtime -------------------------------------------------------------------
FROM python:3.13-slim-bookworm

# gcc/g++ + patchelf: Nuitka standalone builds. ccache: rebuilds reuse unchanged
# C files. git: Git-source builds. pigz: faster image export. tini: reaps the
# compilers and test runs builds start.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential patchelf ccache git ca-certificates pigz tini \
 && rm -rf /var/lib/apt/lists/*

# Node for frontend builds (npm; yarn and pnpm through corepack) and the docker
# CLI for Docker output. Copied rather than installed: no extra repositories.
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
 && ln -s ../lib/node_modules/corepack/dist/corepack.js /usr/local/bin/corepack \
 && corepack enable
COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=uv /uv /uvx /usr/local/bin/

RUN useradd --create-home --uid 1000 packwright \
 && mkdir -p /app /data /opt/uv \
 && chown packwright:packwright /app /data /opt/uv

# Interpreters uv installs (for the Nuitka venvs below and for the .venv of each
# Git-source build) live in the image, writable by the service so a build can
# add a version it needs.
ENV UV_PYTHON_INSTALL_DIR=/opt/uv/python \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PATH=/app/.venv/bin:$PATH

USER packwright
WORKDIR /app

# The service's own dependencies first, so code changes reuse this layer.
COPY --chown=packwright:packwright pyproject.toml uv.lock .python-version ./
RUN UV_PYTHON_DOWNLOADS=never uv sync --locked --no-dev --no-install-project --no-cache

# One Nuitka venv per Python version a build can target (3.12, 3.13, 3.14): an
# executable is bound to the Python that compiled it.
COPY --chown=packwright:packwright scripts/setup_nuitka_venvs.sh scripts/
RUN UV_CACHE_DIR=/tmp/uv-cache bash scripts/setup_nuitka_venvs.sh && rm -rf /tmp/uv-cache

COPY --chown=packwright:packwright main.py alembic.ini ./
COPY --chown=packwright:packwright alembic/ alembic/
COPY --chown=packwright:packwright app/ app/
COPY --chown=packwright:packwright deploy/docker/entrypoint.sh deploy/docker/
COPY --chown=packwright:packwright --from=console /src/frontend/dist frontend/dist

# Every default path is ./data/... (database, workspace, images); generated
# secrets are appended to /app/.env. Both point into the /data volume.
RUN ln -s /data /app/data && ln -s /data/.env /app/.env

ENV HOST=0.0.0.0 \
    PORT=5018 \
    NUITKA_CACHE_DIR=/data/nuitka-cache \
    BOOTSTRAP_UV_CACHE_DIR=/data/uv-cache \
    UV_CACHE_DIR=/data/uv-cache

VOLUME ["/data"]
EXPOSE 5018
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"5018\")}/health', timeout=4)"

ENTRYPOINT ["tini", "--", "deploy/docker/entrypoint.sh"]
CMD ["python", "main.py"]
