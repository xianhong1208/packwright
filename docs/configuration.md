# Configuration reference

Every setting Packwright reads, with its default and what it does. For an overview and the
handful of settings most installs touch, see the [Configuration](../README.md#configuration)
and [Storage & data](../README.md#storage--data) sections of the README.

## How settings are loaded

- Settings come from **environment variables** or **`.env` files**: the `.env` next to
  `main.py` is always read, then a `.env` in the directory you launch from, which overrides
  it. A real environment variable wins over both. Relative paths in settings (`./data/...`)
  are resolved against the launch directory, so launch from the Packwright directory
  (`start.sh` and the systemd unit do) unless you set absolute paths.
- The variable name is the setting name in upper case (`MAX_CONCURRENT_BUILDS`); matching is
  case-insensitive. The one exception is `MCP_GATE_URL`, which also accepts the legacy name
  `MCP_CENTER_URL` when `MCP_GATE_URL` is not set.
- Lists (`CORS_ORIGINS`, `TRUSTED_PROXY_IPS`, `GIT_ALLOWED_HOSTS`, `LOCAL_SOURCE_ROOTS`) are
  comma-separated; surrounding spaces and empty entries are ignored.
- Booleans accept `true`/`false`, `1`/`0`, `yes`/`no`, `on`/`off`.
- **Nothing is required.** With no `.env` at all, Packwright uses a local SQLite database,
  generates its secrets on first start (appending them to the `.env` next to `main.py`) and
  creates an admin account.
- `.env` holds signing and encryption keys, so keep it owner-only: `chmod 600 .env`.
  Packwright creates it with that mode when it writes a generated secret.
- Settings are read once at startup; restart the service after changing them.

`.env.example` in the repository root is a commented starting point.

## Database

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | *(empty)* | Full SQLAlchemy URL of the database. Empty uses a local SQLite file, `./data/build_center.db` (relative to the launch directory), created on first use. Set a PostgreSQL DSN such as `postgresql+asyncpg://user:password@localhost:5432/build_center` to use PostgreSQL; `postgresql://` and `sqlite:///…` URLs also work, as the right async/sync driver is substituted automatically. Takes precedence over every `DB_*` setting. |
| `DB_HOST` | *(empty)* | PostgreSQL host, used only when `DATABASE_URL` is empty. Setting it switches from SQLite to PostgreSQL with a DSN built from the `DB_*` settings below. |
| `DB_PORT` | `5432` | PostgreSQL port for the `DB_*` form. Ignored unless `DB_HOST` is set and `DATABASE_URL` is empty. |
| `DB_NAME` | `build_center` | PostgreSQL database name for the `DB_*` form. |
| `DB_USER` | `postgres` | PostgreSQL user for the `DB_*` form. |
| `DB_PASSWORD` | `admin` | PostgreSQL password for the `DB_*` form. The default is a placeholder: always set a real password when you use `DB_HOST`. |

Migrations run automatically on every start (`uv run python main.py`), whichever database is
configured.

## Server

| Variable | Default | Description |
|---|---|---|
| `HOST` | `0.0.0.0` | Address the HTTP server binds to. Use `127.0.0.1` to accept only local connections (for example behind a reverse proxy on the same host). |
| `PORT` | `5018` | TCP port the HTTP server listens on. If you change it and use MCP Gate sign-in, update `MCP_OAUTH_REDIRECT_URI` to match. |
| `DEBUG` | `false` | Development mode: enables uvicorn auto-reload on code changes and echoes every SQL statement to the log. Leave off in production. |
| `CORS_ORIGINS` | `http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000` | Comma-separated browser origins allowed to call the API with credentials. The defaults cover the Vite and CRA dev servers; the built console is served from Packwright's own origin and does not need an entry. Add an origin only when a console on a different origin calls this API. |
| `LOG_LEVEL` | `INFO` | Level for the application's own log output (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`). An unrecognised value falls back to `INFO`. |

## Tasks and builds

| Variable | Default | Description |
|---|---|---|
| `MAX_LOG_LINES` | `3000` | Maximum number of log lines kept in memory per running task; older lines are dropped first. Raise it if long builds lose their early output in the live log view. |
| `FINISHED_TASK_RETENTION_MINUTES` | `60` | Minutes a finished (completed, failed or cancelled) task stays in the in-memory live-task list, with its log buffer, before it is evicted. Build history in the database is not affected; this only bounds memory use. |
| `MAX_CONCURRENT_BUILDS` | `3` | How many builds run at the same time. Further submissions wait in the queue ("Queued — waiting for build slot") until a slot frees. Each build can saturate several CPU cores, so size this to the machine. |

## Compile cache

Nuitka compiles every module it includes into C and runs the C compiler on each file. When
[ccache](https://ccache.dev/) is installed on the build host, Nuitka routes the compiler through
it on its own and a rebuild only compiles the files that changed: a Full-mode build of a small
Starlette app took 123 s the first time and 21 s when rebuilt from a fresh clone, reusing 80 of
its 81 C files. Install it with the system package manager (`apt install ccache`,
`dnf install ccache`); the next build picks it up without a restart. The **Machine** page shows
whether it is on, how big the store is and where it lives, and each build's log and result say
how many C files came from it.

| Variable | Default | Description |
|---|---|---|
| `NUITKA_CACHE_DIR` | *(empty)* | Nuitka's cache directory, which holds the ccache store (`<dir>/ccache`). Empty leaves Nuitka's default, `~/.cache/Nuitka` of the user running the service. Set it when that home is not persistent (a container) or too small. |

ccache caps its store at 5 GiB by default and evicts the oldest files itself. Change the cap with
`CCACHE_MAXSIZE` in the service's environment (e.g. `CCACHE_MAXSIZE=20G`), or clear the store with
`CCACHE_DIR=<dir>/ccache ccache -C`. `NUITKA_CCACHE_BINARY` points Nuitka at a ccache that is not
on `PATH`.

## Notifications

A project's settings have a **Notifications** tab: Discord and Slack incoming webhooks, or any URL
that accepts a JSON `POST`, each sent when a build of the project fails, passes, or both. Its
creator and holders of `project:manage` change them; everyone who may build sees them. Webhook URLs
are credentials, so they are stored encrypted with `SETTINGS_ENCRYPTION_KEY` and only their host and
last characters are ever shown. Messages are sent after the build, outside its build slot; a
destination that does not answer is retried once and its last result is shown on the tab.

| Variable | Default | Description |
|---|---|---|
| `PUBLIC_URL` | *(empty)* | The address people open Packwright at, e.g. `https://packwright.example.com`. Messages link to the build's page with it; empty sends them without a link. |

The plain webhook receives:

```json
{"event": "failed", "project": "shop", "version": "1.2.0", "build_id": "…", "status": "failed",
 "triggered_by": "mei", "duration_seconds": 252.4,
 "diagnosis": {"problem": "…", "suggestion": "…"}, "url": "https://…/history/…", "title": "shop 1.2.0 failed"}
```

`event` is `passed`, `failed` or `test` (the tab's *Send test*); `diagnosis` is `null` unless the
build failed.

## Secrets

| Variable | Default | Description |
|---|---|---|
| `JWT_SECRET_KEY` | *(generated)* | Key that signs session tokens (HS256). When unset, a random key is generated on first start and appended to `.env` so sessions survive restarts. Changing it signs every user out. |
| `SETTINGS_ENCRYPTION_KEY` | *(generated)* | Fernet key that encrypts stored Git credentials at rest. When unset, one is generated on first use and appended to `.env`. Keep it with your backups: if it changes, stored credentials can no longer be decrypted and must be re-entered. Set it explicitly if you ever run more than one process. |

## Bootstrap admin

On first start, when the database has no users at all, Packwright creates an administrator
account so you can sign in immediately. Nothing happens on later starts, so these settings
never reset an existing password.

| Variable | Default | Description |
|---|---|---|
| `BOOTSTRAP_ADMIN_USERNAME` | `admin` | Username of the account created on first start. |
| `BOOTSTRAP_ADMIN_PASSWORD` | *(unset)* | **Unset**: a random password is generated and printed once in the startup log (it is not stored anywhere else). **Set to a value**: that password is used; change it after first sign-in. **Set to an empty string**: no bootstrap account is created, and you use self-registration instead (new accounts await administrator approval). |

## MCP Gate single sign-on

Optional. When enabled, the sign-in page offers **Sign in with MCP Gate**: Packwright runs the
OAuth 2.1 authorization-code flow with PKCE against MCP Gate and then issues its own session.
Local username/password sign-in stays available. An account created through SSO starts inactive
with the `user` role and needs administrator approval, like a self-registration (unless it is the
very first account in the database, which becomes an active administrator).

| Variable | Default | Description |
|---|---|---|
| `MCP_OAUTH_ENABLED` | `false` | Turns MCP Gate sign-in on. It is only offered when this is true **and** `MCP_GATE_URL` and `MCP_OAUTH_CLIENT_ID` are both set. |
| `MCP_GATE_URL` | `http://localhost:4568` | MCP Gate's issuer URL (its `OAUTH_ISSUER`); the browser is sent to `<MCP_GATE_URL>/oauth/authorize`. Must match the issuer exactly, including `localhost` vs `127.0.0.1`. The legacy name `MCP_CENTER_URL` is read when this one is not set. |
| `MCP_OAUTH_CLIENT_ID` | *(empty)* | Client ID of the OAuth client registered for Packwright in MCP Gate. |
| `MCP_OAUTH_CLIENT_SECRET` | *(empty)* | Client secret for a confidential client. Leave empty for a public client (PKCE only). |
| `MCP_OAUTH_REDIRECT_URI` | `http://localhost:5018/auth/oauth/mcp/callback` | Callback URL MCP Gate redirects back to; it must be registered on the client exactly. Packwright also derives its own public origin from it (where users land after sign-in) and marks the SSO cookies `Secure` when it starts with `https`. Update it when you change `PORT` or put Packwright behind a domain. |
| `MCP_OAUTH_SCOPES` | `openid` | Space-separated scopes requested from MCP Gate. |

## Rate limiting

The rate limiter is always on: per client address, `RATE_LIMIT_PER_MINUTE` and
`RATE_LIMIT_PER_HOUR` API requests, with stricter limits on sign-in, registration and
password-recovery endpoints and on build submission. Static files and the console itself are
never counted, nor is the build list the dashboard polls. These settings tune how clients are
identified and how much they may do.

| Variable | Default | Description |
|---|---|---|
| `TRUSTED_PROXY_IPS` | *(empty)* | Comma-separated IP addresses of reverse proxies whose `X-Forwarded-For` header is believed. **Empty means `X-Forwarded-For` is never trusted** and every request is attributed to its real peer address, the safe setting for a directly exposed service. Set it to your proxy's address (for example `127.0.0.1` for nginx on the same host) only when a proxy really sits in front; the rightmost forwarded address is then used. This also determines the IP recorded in the audit log and login history. |
| `BUILD_SUBMIT_PER_MINUTE` | `20` | Per-client cap on build submissions per minute: `POST /api/tasks` and a project's *Build a new version* (`POST /api/projects/{id}/builds`) together. `MAX_CONCURRENT_BUILDS` limits how many builds run at once; this limits how fast the queue can grow. |
| `RATE_LIMIT_PER_MINUTE` | `300` | API requests a client address may make per minute outside the endpoints above. A page of the console makes one to five (Roles one per role), and everyone behind one NAT or proxy address shares the allowance, so keep it well above a person's browsing. When the console's session check is refused, it waits and asks again instead of signing the person out. |
| `RATE_LIMIT_PER_HOUR` | `6000` | The same, per hour. |

## Git source mode

| Variable | Default | Description |
|---|---|---|
| `GITLAB_TOKEN` | *(unset)* | Legacy single access token, used only when no Git credential stored in the console (Settings → Git credentials) matches the repository host. May be left unset; prefer console-managed credentials. |
| `GITLAB_TOKEN_HOST` | `gitlab.com` | The one exact host name `GITLAB_TOKEN` may be sent to. Set it to your server's name for a self-hosted GitLab; the token is never sent to any other host. |
| `GIT_WORKSPACE_DIR` | `./data/workspace` (relative to the launch directory) | Where Git-mode builds clone into: one directory per task holding the clone, its `.venv` and the build output. Non-Docker outputs are downloaded from here, so it must persist between restarts. Set an absolute path to move it to a larger disk. |
| `GIT_ALLOWED_HOSTS` | *(empty)* | Comma-separated host names (or IP addresses) Git URLs may point at. **Empty allows any `http`/`https` host**, except IP literals in loopback, private, link-local and other reserved ranges. When set, only the listed hosts are allowed, and listing an internal IP address explicitly permits it. `localhost` is always rejected. |
| `GIT_CLONE_TIMEOUT` | `600` | Maximum seconds a `git clone` may take before the build fails. |
| `LOCAL_SOURCE_ROOTS` | *(empty)* | Comma-separated absolute directory prefixes that local-path builds (and the directory browser in the build wizard) may read. **Empty disables local-source mode** so only Git URLs can be built. List only directories you trust every user with `task:create` to read. |

## Auto venv bootstrap (Git mode)

After cloning a Python project, Packwright creates its virtual environment with uv: `uv sync
--frozen` when a `uv.lock` exists, otherwise `uv sync`, or `uv venv` plus
`uv pip install -r requirements.txt`. Projects with neither `pyproject.toml` nor
`requirements.txt` skip this step.

| Variable | Default | Description |
|---|---|---|
| `GIT_AUTO_VENV` | `true` | Run the venv bootstrap after cloning. Turn it off only if your projects do not need one; the Nuitka build expects a usable `.venv` in the project. |
| `UV_BIN` | *(auto-detected)* | Path to the `uv` executable. Empty finds `uv` on the service's `PATH`; set an absolute path when uv is installed somewhere that `PATH` does not include (common under systemd). |
| `PRE_BUILD_PATH` | *(inherited)* | `PATH` given to pre-build and venv-bootstrap subprocesses. Empty uses the service's own `PATH`; set it to pin the tools those steps can find. |
| `BUILD_ENV_PASSTHROUGH` | *(empty)* | Extra host environment variables builds may see, comma-separated. Frontend builds, Docker builds and the Nuitka compile run project code, so they get only `PATH`, `HOME`, locale, `TZ`, `TMPDIR`, `TERM`, proxy variables (`HTTP(S)_PROXY`, `NO_PROXY`, lower-case too), CA bundles (`SSL_CERT_FILE`, `NODE_EXTRA_CA_CERTS`, …), `CC`/`CXX` and names starting with `NPM_CONFIG_`, `YARN_`, `PNPM_`, `COREPACK_`, `BUN_`, `DOCKER_`, `BUILDKIT_`, `CCACHE_` or `NUITKA_` (`app/services/build_env.py`). List anything else your builds read from the host here. Values a single project needs belong in its build settings instead. |
| `VENV_BOOTSTRAP_TIMEOUT` | `900` | Maximum seconds for the venv bootstrap step. Raise it for projects with very large dependency sets. |
| `BOOTSTRAP_UV_CACHE_DIR` | *(empty)* | uv cache directory used only by the bootstrap step. Empty uses uv's default user cache. Put it on the **same filesystem as `GIT_WORKSPACE_DIR`** so uv can hardlink packages instead of copying them into every clone. Created if missing. |

## Workspace cleanup (Git mode)

A background sweep deletes per-task workspaces under `GIT_WORKSPACE_DIR` by task status and
age. It first runs about a minute after start-up and never touches running or queued tasks.

| Variable | Default | Description |
|---|---|---|
| `WORKSPACE_CLEANUP_ENABLED` | `true` | Run the periodic workspace sweep. Disabling it means workspaces accumulate until deleted by hand. |
| `WORKSPACE_SUCCESS_TTL_DAYS` | `7` | Days after a successful build ends before its workspace is deleted. Because a non-Docker output is downloaded from its workspace, **this is also how long that output stays downloadable**. |
| `WORKSPACE_FAILED_TTL_DAYS` | `30` | Days to keep the workspace of a failed or cancelled build, longer by default so there is time to investigate. |
| `WORKSPACE_ORPHAN_TTL_DAYS` | `2` | Days to keep directories under `GIT_WORKSPACE_DIR` that have no matching build in history (usually left by an interrupted clone), judged by modification time. |
| `WORKSPACE_CLEANUP_INTERVAL_HOURS` | `6` | Hours between sweeps (minimum 1). The same loop also runs the Docker-image and refresh-token cleanups. |
| `WORKSPACE_SHRINK_ON_SUCCESS` | `true` | After a successful non-Docker build, delete everything in its workspace except the output directory (source, `.venv`, `.git`), keeping the download working while reclaiming most of the space. |
| `WORKSPACE_DOCKER_DELETE_ON_SUCCESS` | `true` | After a successful Docker build, delete the whole workspace, since the exported image in `DOCKER_IMAGES_DIR` already holds the result. |

## Refresh token retention

| Variable | Default | Description |
|---|---|---|
| `REFRESH_TOKEN_RETENTION_DAYS` | `7` | Days an expired or revoked refresh token is kept before the background sweep deletes it (minimum 1). Every token refresh creates a new row and revokes the old one, so without this the table only grows; the window keeps recently ended sessions visible in the session list. Does not change how long sessions last. |

## Docker image exports

A successful Docker build is saved as a gzip-compressed tarball that users download and load
with `docker load -i <file>`.

| Variable | Default | Description |
|---|---|---|
| `DOCKER_EXPORT_COMPRESS_THREADS` | `32` | Threads used to compress the exported image when `pigz` is installed. Plain `gzip` is single-threaded and takes minutes on multi-GB images. Kept below "all cores" so exports do not starve concurrent builds; ignored (falls back to `gzip`) when `pigz` is not installed. |
| `DOCKER_IMAGES_DIR` | `./data/docker_images` (relative to the launch directory) | Where exported images (`<task-id>.tar.gz`) are written and downloaded from. Set an absolute path to move them to a larger disk. |
| `DOCKER_IMAGES_CLEANUP_ENABLED` | `true` | Periodically delete exported images older than `DOCKER_IMAGES_TTL_DAYS`. Runs in the same background loop as the workspace sweep. |
| `DOCKER_IMAGES_TTL_DAYS` | `30` | Days an exported image stays available for download, judged by file modification time (the export time). |
