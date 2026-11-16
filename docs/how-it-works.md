# How Packwright works

[繁體中文](how-it-works.zh-TW.md) · [README](../README.md) · [Every setting](configuration.md)

What happens to a build, the settings most installs touch, where Packwright keeps its data, and how
Git credentials are used. Every setting with its default is in [configuration.md](configuration.md).

## How it works

```
Console (React + antd)  ──HTTP / WebSocket──▶  FastAPI
                                                 │
   auth (JWT + RBAC) ── tasks ── monitoring      │
                                                 ▼
                          build dispatcher ──▶ Nuitka / npm / Docker workers
                                                 │  (git clone → uv sync → build)
                                                 ▼
                          artifacts + Docker image .tar.gz
```

- **Sources.** A build is either a *local path* (confined to `LOCAL_SOURCE_ROOTS`) or a *Git URL*. Git mode validates the URL (no `file://`, `ssh://`, localhost, link-local or credential-bearing URLs), clones at a specific branch/tag, and — for Python projects — bootstraps a `.venv` before building. git sends only the credentials stored in Packwright, never the server account's own git configuration or login.
- **Token injection.** For a private repo the token for that host is looked up, decrypted, and handed to `git` only for that call, as an HTTP auth header scoped to the repository's origin (through `GIT_CONFIG_*` environment variables, so it is not on the command line either). It never appears in the URL, the stored build config or the log, and the API never returns it.
- **Concurrency.** `MAX_CONCURRENT_BUILDS` bounds simultaneous builds (of every kind) behind a semaphore, and the rest queue; builds of one local folder run one at a time and wait for it without holding a slot; the process is intentionally single-worker because task state, WebSocket connections and the build semaphore live in process memory.
- **Cleanup.** A background loop deletes per-task workspaces and exported images by status and age, and (optionally) shrinks a successful build's workspace to just its output.

## The settings most installs touch

Everything is environment-driven, and nothing is required. `.env.example` lists the essentials and [docs/configuration.md](configuration.md) documents every setting. The most important ones:

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | *(empty → SQLite)* | A local SQLite file by default; set a `postgresql+asyncpg://…` DSN to use PostgreSQL. |
| `HOST` / `PORT` | `0.0.0.0` / `5018` | Bind address. |
| `JWT_SECRET_KEY` | auto | Session signing key; generated to `.env` on first start if empty. |
| `SETTINGS_ENCRYPTION_KEY` | auto | Encrypts stored Git tokens; generated to `.env` if empty. |
| `CORS_ORIGINS` | dev ports | CSV of browser origins allowed to call the API. |
| `GIT_WORKSPACE_DIR` | `./data/workspace` | Where clones and build workspaces live, and where each non-Docker build's output is kept and downloaded from (local builds included). |
| `DOCKER_IMAGES_DIR` | `./data/docker_images` | Where exported Docker images (`.tar.gz`) are written. |
| `NUITKA_CACHE_DIR` | *(empty → `~/.cache/Nuitka`)* | Nuitka's cache, including the ccache store that makes rebuilds faster. |
| `LOCAL_SOURCE_ROOTS` | *(empty)* | CSV of absolute prefixes a local-source build may read; empty disables local mode. |
| `UV_BIN` / `PRE_BUILD_PATH` | auto | uv binary and subprocess PATH; auto-detected when empty. |
| `BUILD_ENV_PASSTHROUGH` | *(empty)* | CSV of extra host variables builds may see. Builds get only the basics, proxy/CA settings and tool configuration (`NPM_CONFIG_*`, `DOCKER_*`, …), never the service's secrets. |
| `MAX_CONCURRENT_BUILDS` | `3` | Simultaneous builds; the rest wait in the queue. |
| `PUBLIC_URL` | *(empty)* | The address people open Packwright at; build notifications link to the build with it. |
| `TRUSTED_PROXY_IPS` | *(empty)* | Proxy IPs whose `X-Forwarded-For` may be trusted; empty is safest. |
| `RATE_LIMIT_PER_MINUTE` / `RATE_LIMIT_PER_HOUR` | `300` / `6000` | API requests one client address may make (everyone behind one NAT or proxy shares it); sign-in, registration and build submission have their own, stricter limits. |

## Storage & data

Packwright writes everything under a single `data/` directory. By default these paths are **relative to the working directory you launch from** (where you run `uv run python main.py`), so a default install keeps all state inside the project:

```
data/
├── build_center.db     # SQLite database (users, roles, history, Git credentials)
├── workspace/          # one dir per build: clone, .venv, and the compiled output
└── docker_images/      # exported Docker images, as <task-id>.tar.gz
```

**Where a finished build ends up:**
- **Binary / bundle** (backend, frontend, full-stack): stays in that build's workspace under `data/workspace/<task-id>/`, and the console's **Download** button streams it from there.
- **Docker output**: the image is saved to `data/docker_images/` as a `.tar.gz`; load it later with `docker load -i <file>`.

**Relocating storage** (e.g. onto a larger disk) — set absolute paths in `.env` and restart:

```bash
GIT_WORKSPACE_DIR=/srv/packwright/workspace     # clones, builds, downloadable outputs
DOCKER_IMAGES_DIR=/srv/packwright/docker_images # exported image tarballs
# Move the database too (SQLite file, or point at PostgreSQL):
DATABASE_URL=sqlite+aiosqlite:////srv/packwright/build_center.db
```

Put `GIT_WORKSPACE_DIR` on the same filesystem as `BOOTSTRAP_UV_CACHE_DIR` so `uv` can hardlink instead of copying during dependency install.

**Retention** — a background sweep reclaims disk on a TTL, so the disk doesn't grow without bound. Because a non-Docker output is downloaded from its workspace, the success TTL doubles as *how long that output stays downloadable*:

| Variable | Default | What it keeps |
|---|---|---|
| `WORKSPACE_SUCCESS_TTL_DAYS` | `7` | Successful non-Docker workspaces (i.e. how long the output is downloadable). |
| `WORKSPACE_FAILED_TTL_DAYS` | `30` | Failed / cancelled workspaces (kept longer for debugging). |
| `DOCKER_IMAGES_TTL_DAYS` | `30` | Exported image tarballs. |

On a successful build the workspace is also trimmed automatically: a non-Docker build's workspace is shrunk to just its output (dropping the clone, `.venv` and `.git`), and a Docker build's workspace is deleted outright since the image tarball already holds the result.

## Docker images

A backend or full-stack build with Docker on is compiled on the host first, and the image only copies
the result into a slim base image (`python:3.13-slim` by default):

- **System packages.** The image installs `libpq5 zlib1g libxml2 libxslt1.1`, plus a GUI or graphics
  library (OpenGL, GLib, X11, xcb, fontconfig…) only when a shipped extension needs it: Packwright reads
  the libraries each `.so` in the output asks for (ELF `DT_NEEDED`). OpenCV or Qt bring theirs; most
  programs need none. The build log names each extra package and the file that needs it. A library a
  program loads with `dlopen()` or `ctypes` is not listed anywhere: add it with an `apt-get` line under
  *Custom commands*.
- **Compression.** A onefile binary is compressed with zstandard (`nuitka[onefile]`, installed with
  Packwright and by `scripts/setup_nuitka_venvs.sh`); without it the preflight check *Onefile compression*
  says so.
- **No build leftovers.** The finder of an editable install (`__editable___<name>_finder.py`, which uv
  writes for a Git project) is left out of `libs/`: the program's own code is compiled into the binary.
- The build log and the build result show the image's size.
- **State and user.** The program runs as the user `app` (uid 10001), which owns its files (given on
  the `COPY`, so nothing is stored twice) and `/app`. *Run as root* (Docker settings → Advanced) turns
  this off. The **Volumes** setting lists the folders the program keeps its state in (relative to `/app`
  or absolute); each is created in the image, owned by `app`, and declared as a `VOLUME`. Left empty,
  the folders the program created during the smoke test are used (MCP Gate: `data`, `logs`, `secrets`)
  and saved into the build's settings, and into the project's while it has none, so the field shows them
  next time. The build suggests a `docker run` that keeps them:

  ```bash
  docker run -d --name mcp_gate -p 4598:4598 -v mcp_gate-data:/app/data -v mcp_gate-secrets:/app/secrets mcp_gate:1.4.0
  ```

  A new named volume starts with the image folder's contents and owner, so the non-root program can
  write to it. For a bind mount, give the host folder to uid 10001 (`chown 10001:10001 <dir>`).

## Git credentials

Access tokens for private repositories are managed in the console (**Git credentials** in the left rail, `user:manage` permission), not in `.env`:

- One token per host, for **GitHub**, **GitLab**, or a self-hosted instance (any host).
- Tokens are encrypted at rest with `SETTINGS_ENCRYPTION_KEY` and never returned by the API — the UI shows only the last four characters.
- When a build clones a URL, the token whose host matches exactly is selected automatically.
- `GITLAB_TOKEN` in `.env` remains a fallback when no stored credential matches, sent only to the exact host in `GITLAB_TOKEN_HOST` (default `gitlab.com`; set it to your server's name for a self-hosted GitLab).

## Names kept from Build Center

Packwright was called *Build Center* up to v1.0.0. Names that live in existing data keep the old spelling, so nothing needs migrating: the SQLite file `data/build_center.db`, the default PostgreSQL database `build_center`, and the `BUILD_CENTER_SMOKE_TEST` variable that smoke-tested binaries still receive (alongside the new `PACKWRIGHT_SMOKE_TEST`). The systemd unit is now `deploy/packwright.service`.
