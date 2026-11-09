# Packwright

**A full-stack build & packaging platform.** Point it at a local path or a Git URL and it compiles Python to a standalone executable with [Nuitka](https://nuitka.net/), builds frontends with npm / yarn / pnpm / bun, packages the two together, and can export the result as a Docker image `.tar.gz` — all from a web console with live build logs, user accounts and role-based permissions.

Packwright was called *Build Center* up to v1.0.0. Names that live in existing data keep the old spelling, so nothing needs migrating: the SQLite file `data/build_center.db`, the default PostgreSQL database `build_center`, and the `BUILD_CENTER_SMOKE_TEST` variable that smoke-tested binaries still receive (alongside the new `PACKWRIGHT_SMOKE_TEST`). The systemd unit is now `deploy/packwright.service`.

[繁體中文](README.zh-TW.md) · [Quick start](#quick-start) · [How it works](#how-it-works) · [Configuration](#configuration) · [Git credentials](#git-credentials) · [All settings](docs/configuration.md) · [Detailed manual (zh-TW)](docs/manual.zh-TW.md)

## Key features

- **Four build modes.** Backend-only (Nuitka), frontend-only (any Node package manager), full-stack (frontend bundled into the Nuitka build as data), and Docker output (the build packaged into an image and exported as `.tar.gz`).
- **Projects and versions.** Every build is filed under a project (the same name and source). A project's page lists its versions and builds a new one in one dialog; the version is read from the Git tag, pyproject.toml or package.json, names the download, tags the Docker image and is written into a `VERSION` file. Projects are shared by everyone who may build.
- **Notifications.** A project can send how its builds end to Discord, Slack or any URL that takes JSON: failed builds with the diagnosis, passed ones with how long they took. No mail server needed; webhook URLs are stored encrypted and never shown again.
- **Quick build.** Point it at a folder or a Git URL and it reads the project: backend, frontend or full stack, the entry point, where `package.json` is, the Python version and dependency groups. One click starts the build; every setting is still there under *All settings*.
- **Local path or Git URL sources.** Git mode clones the repo, bootstraps a `.venv` with `uv sync`, builds, and cleans the workspace afterward. SSRF-hardened URL validation, argv-only subprocess calls, and per-host clone timeouts.
- **Git credentials managed in the console.** Add GitHub, GitLab and self-hosted tokens in the UI; they are stored encrypted and chosen automatically by the clone URL's host — no secrets in `.env`.
- **Live logs and history.** Every build streams over WebSocket; finished builds keep a full record with the exact config that produced them, so a rebuild is deterministic.
- **Accounts, roles, permissions.** JWT sessions with refresh-token rotation, an RBAC model (users / roles / permissions), login history and an audit log. First run creates the administrator.
- **Built to run unattended.** Background sweeps reclaim workspace and exported-image disk on a TTL, and a systemd unit keeps the service up.

## Install

### With Docker

The image carries everything builds need: the Nuitka toolchain for Python 3.12 to 3.14, ccache, Node.js (npm, yarn and pnpm through corepack), git and the docker CLI.

```bash
git clone https://github.com/xianhong1208/packwright.git
cd packwright
docker compose up -d
docker compose logs packwright | grep "bootstrap admin"   # the first sign-in password
```

Open `http://localhost:5018` and sign in as **`admin`**. Everything Packwright keeps (database, generated secrets, workspaces, outputs, the compile cache) is in the `packwright-data` volume, so `docker compose up -d --build` after a `git pull` upgrades without losing anything. Builds run as uid 1000 inside the container. `docker-compose.yml` shows how to let builds read folders on the host and, if you trust every account, use the host's Docker for Docker output.

### From source

**Prerequisites:** Python 3.13+, [uv](https://docs.astral.sh/uv/), Node.js 22.12+ (to build the console, and for frontend builds), and — for the engines they drive — Nuitka's toolchain (a C compiler) and Docker (for Docker output). The database is a local SQLite file by default (no setup); PostgreSQL is optional (set `DATABASE_URL`). `pigz` is optional and speeds up image compression. [ccache](https://ccache.dev/) is optional and strongly recommended: with it, Nuitka reuses the C files that did not change, so a rebuild can be several times faster (the **Machine** page says whether it is on).

```bash
git clone https://github.com/xianhong1208/packwright.git
cd packwright
uv sync                       # backend deps
cd frontend && npm install && npm run build && cd ..
cp .env.example .env          # optional; SQLite works with no config
```

## Quick start

```bash
uv run python main.py         # applies migrations, then serves on http://0.0.0.0:5018
```

- Open `http://localhost:5018` and sign in as **`admin`** with the password printed in the startup log (`Created bootstrap admin 'admin' with generated password: …`). It is generated on first start and shown only once — change it after logging in, or set `BOOTSTRAP_ADMIN_USERNAME` / `BOOTSTRAP_ADMIN_PASSWORD` before first start.
- **Add a Git credential** (optional, for private repos): **Git credentials** (left rail) → choose GitHub, GitLab or a self-hosted server, paste a personal access token.
- **Create a build**: pick Local path or Git URL, choose the mode, and submit. Logs stream live; the finished artifact is downloadable (or exported as a Docker image `.tar.gz`).

For a development frontend with hot reload, run `npm run dev` in `frontend/` (it proxies the API to `:5018`). A step-by-step walkthrough (in Traditional Chinese) is in [docs/quickstart.zh-TW.md](docs/quickstart.zh-TW.md).

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

- **Sources.** A build is either a *local path* (confined to `LOCAL_SOURCE_ROOTS`) or a *Git URL*. Git mode validates the URL (no `file://`, `ssh://`, localhost, link-local or credential-bearing URLs), clones at a specific branch/tag, and — for Python projects — bootstraps a `.venv` before building.
- **Token injection.** For a private repo the token for that host is looked up, decrypted, and handed to `git` only for that call, as an HTTP auth header scoped to the repository's origin (through `GIT_CONFIG_*` environment variables, so it is not on the command line either). It never appears in the URL, the stored build config or the log, and the API never returns it.
- **Concurrency.** `MAX_CONCURRENT_BUILDS` bounds simultaneous builds (of every kind) behind a semaphore, and the rest queue; builds of one local folder run one at a time and wait for it without holding a slot; the process is intentionally single-worker because task state, WebSocket connections and the build semaphore live in process memory.
- **Cleanup.** A background loop deletes per-task workspaces and exported images by status and age, and (optionally) shrinks a successful build's workspace to just its output.

## Configuration

Everything is environment-driven, and nothing is required. `.env.example` lists the essentials and [docs/configuration.md](docs/configuration.md) documents every setting. The most important ones:

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | *(empty → SQLite)* | A local SQLite file by default; set a `postgresql+asyncpg://…` DSN to use PostgreSQL. |
| `HOST` / `PORT` | `0.0.0.0` / `5018` | Bind address. |
| `JWT_SECRET_KEY` | auto | Session signing key; generated to `.env` on first start if empty. |
| `SETTINGS_ENCRYPTION_KEY` | auto | Encrypts stored Git tokens; generated to `.env` if empty. |
| `CORS_ORIGINS` | dev ports | CSV of browser origins allowed to call the API. |
| `GIT_WORKSPACE_DIR` | `./data/workspace` | Where clones and build workspaces live (and where non-Docker outputs are downloaded from). |
| `DOCKER_IMAGES_DIR` | `./data/docker_images` | Where exported Docker images (`.tar.gz`) are written. |
| `NUITKA_CACHE_DIR` | *(empty → `~/.cache/Nuitka`)* | Nuitka's cache, including the ccache store that makes rebuilds faster. |
| `LOCAL_SOURCE_ROOTS` | *(empty)* | CSV of absolute prefixes a local-source build may read; empty disables local mode. |
| `UV_BIN` / `PRE_BUILD_PATH` | auto | uv binary and subprocess PATH; auto-detected when empty. |
| `BUILD_ENV_PASSTHROUGH` | *(empty)* | CSV of extra host variables builds may see. Builds get only the basics, proxy/CA settings and tool configuration (`NPM_CONFIG_*`, `DOCKER_*`, …), never the service's secrets. |
| `MAX_CONCURRENT_BUILDS` | `3` | Simultaneous builds; the rest wait in the queue. |
| `PUBLIC_URL` | *(empty)* | The address people open Packwright at; build notifications link to the build with it. |
| `TRUSTED_PROXY_IPS` | *(empty)* | Proxy IPs whose `X-Forwarded-For` may be trusted; empty is safest. |

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

## Git credentials

Access tokens for private repositories are managed in the console (**Git credentials** in the left rail, `user:manage` permission), not in `.env`:

- One token per host, for **GitHub**, **GitLab**, or a self-hosted instance (any host).
- Tokens are encrypted at rest with `SETTINGS_ENCRYPTION_KEY` and never returned by the API — the UI shows only the last four characters.
- When a build clones a URL, the token whose host matches exactly is selected automatically.
- `GITLAB_TOKEN` in `.env` remains a fallback when no stored credential matches, sent only to the exact host in `GITLAB_TOKEN_HOST` (default `gitlab.com`; set it to your server's name for a self-hosted GitLab).

## Testing

```bash
uv run pytest -q tests/unit          # backend unit tests (DB-free)
cd frontend && npx vitest run        # frontend unit tests
```

## Security & trust model

Packwright runs untrusted build commands by design, so account approval is the real security boundary: anyone who can create a task can run code as the service user. Git URL validation, local-path confinement, subprocess argv-only calls, token masking and rate limiting are defence in depth, not a sandbox. Run it on an isolated host, front it with HTTPS, and keep `TRUSTED_PROXY_IPS` empty unless a proxy actually rewrites `X-Forwarded-For`. [SECURITY.md](SECURITY.md) has the full trust model, known limitations and how to report a vulnerability.

## Contributing

Setup, the checks CI runs, branch and commit conventions, and the release steps are in [CONTRIBUTING.md](CONTRIBUTING.md). Changes are listed in [CHANGELOG.md](CHANGELOG.md).

## License

[MIT](LICENSE)
