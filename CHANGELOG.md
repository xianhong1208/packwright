# Changelog

All notable changes to Packwright (formerly Build Center) are documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- **Renamed Build Center to Packwright**: packages, console title, login page, docs, scripts, the
  systemd unit (`deploy/packwright.service`, `/opt/packwright`) and the repository
  (`xianhong1208/packwright`). Names that live in existing data keep the old spelling, so nothing
  needs migrating: `data/build_center.db`, the default PostgreSQL database `build_center`,
  `build_center_backups/`, and `BUILD_CENTER_SMOKE_TEST`, which smoke-tested binaries still receive
  next to the new `PACKWRIGHT_SMOKE_TEST`.
- **No default admin password.** With `BOOTSTRAP_ADMIN_PASSWORD` unset, the first start generates a
  random password and prints it once in the log (it used to be `password123`). An empty value still
  disables the account in favour of self-registration.
- **`GITLAB_TOKEN` is sent to one host only**: the new `GITLAB_TOKEN_HOST` (default `gitlab.com`).
  Set it to your server's name if you rely on the fallback with a self-hosted GitLab.
- Docker exports are stored per task (`<DOCKER_IMAGES_DIR>/<task_id>.tar.gz`); exports made before
  are still served from their old image-named file.
- Console development needs Node.js 22.12+ (Vitest 5).
- **MCP Center is now MCP Gate** (the SSO provider was renamed): the setting is `MCP_GATE_URL` and the
  button reads "Sign in with MCP Gate". `MCP_CENTER_URL` is still read when `MCP_GATE_URL` is unset;
  linked accounts are unaffected.
- `.env.example` no longer claims a PostgreSQL connection is required (SQLite is the default).

### Added
- `/health` reports the version, and the console shows it; `pyproject.toml` is the only place a
  version is written (`app/version.py`, `npm run sync-version`).
- CI (`.github/workflows/ci.yml`): backend (ruff, unit + integration tests, schema-drift check),
  frontend (lint, typecheck, tests, build) and a dependency audit; Dependabot.
- SSO sign-in redeems a one-time code (`POST /auth/oauth/mcp/exchange`) instead of reading tokens
  from the URL.

### Security
- A download ticket was accepted as a bearer token on every API for its 30-minute lifetime. Only
  access tokens authenticate now (REST and WebSocket).
- Git-mode artifact downloads read from the service's working directory; with `output_dir="data"`
  they could stream the service's own database. They now serve the task's workspace.
- SSO login CSRF: a crafted link could sign a victim into the attacker's account.
- A role holding only `user:reset_password` or `user:manage` could reset, deactivate or demote an
  account with more permissions (e.g. take over the admin).
- Git tokens are no longer written into each workspace's `.git/config` or visible in `ps`; they reach
  git as a header scoped to the repository's host.
- The frontend preview no longer follows symlinks out of the cloned repository (which could return
  the service's own `.env`).
- The Git URL check recognises alternate loopback spellings (`127.1`, `2130706433`, `0x7f000001`,
  `*.localhost`, IPv4-mapped IPv6).
- Directory names in build configs are confined to the project in git mode too, and every delete or
  copy joins them safely.
- New-build drafts no longer store the Docker runtime environment; sign-out clears the draft and the
  previous user's cached data.
- Dependency updates: pip-audit 53 → 0 (pyjwt, python-multipart, starlette/fastapi, …), npm
  production 5 → 0 (axios, react-router).

### Fixed
- SSO sign-in returned 500 for every approved user.
- Two builds with the same image name overwrote each other's export.
- Reloading while the backend restarted signed the user out (and destroyed remember-me sessions).
- The JWT `permissions` claim ignored inherited roles, hiding menus the API allowed.
- The monitoring page recorded samples twice and assumed a fixed 2 s between them.
- `git_credentials.host` was declared differently in the model and the migration.
- An in-process migration silenced every logger that already existed.
- The per-project build lock entry was never released.
- External-mode builds failed with a `SyntaxError` when the entry point used
  `from __future__ import ...`: the libs/ loader was inserted above it. It now goes after the
  docstring and `__future__` imports, prints nothing (it used to write a Chinese line to the
  program's stdout) and leaves no names in `__main__`.
- Build logs were flooded with progress-bar redraws: a hello-world Nuitka build filled the
  3,000-line log with 2,574 frames and pushed out its first lines. Output is now read the way a
  terminal shows it (only the final frame of a `\r`-redrawn line), Nuitka no longer runs with the
  obsolete `--show-progress`, its progress bars still drive the progress indicator, and a
  multi-byte character split across two reads is no longer mangled.
- Frontend builds showed no duration and no artifact on their detail page. Every build now
  records its wall time, a frontend build records its output's size and file count, and a blank
  binary name shows the name derived from the entry point instead of an empty row.
- A build's link (`/task/<id>`) opened onto a spinner once the build had left memory (after a
  restart or eviction); it now redirects to the stored record under Builds.
- When the service ran as a non-root user, a project whose venv links its python into a directory
  that user cannot enter (root's uv store) crashed the build's preflight: Python 3.13's
  `Path.exists()` raises `PermissionError` there instead of returning False.

## [1.0.0] — 2026-09-10

First release, as Build Center: a full-stack build and packaging platform that compiles Python with
Nuitka, builds frontends and exports Docker images from a web console with live logs, accounts and
role-based permissions.

### Added
- Per-host Git credentials managed in the console (GitHub, GitLab, self-hosted), chosen by the clone
  URL's host.
- Optional "Sign in with MCP Center" SSO, with local login preserved.
- SQLite by default, PostgreSQL via `DATABASE_URL`; migrations applied on startup.
- A seeded admin account on first start.
- English console in an "Instrument" style.

### Fixed
- SSO: no email auto-linking; JWKS signature verification required.
- Timezone-safe token expiry on SQLite; portable build statistics.
- Git credentials feedback in the console; no pre-filled personal paths in New build.

[Unreleased]: https://github.com/xianhong1208/packwright/compare/v1.0.0...dev
[1.0.0]: https://github.com/xianhong1208/packwright/releases/tag/v1.0.0
