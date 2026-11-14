# Changelog

All notable changes to Packwright (formerly Build Center) are documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- A failed smoke test is reported as one. The build said "Nuitka compilation failed" although the compile had
  succeeded, its failure report named the stage "finishing up", and on a full-stack build the diagnosis read
  "Frontend build failed", because that rule fired on "vite build" plus the word "error" anywhere in the log. The
  task now says "Smoke test failed", the report names the verification stage, and the frontend rule needs vite's
  own "error during build".
### Security
- The smoke test no longer leaves the program's state in the build output. The binary runs in the output
  directory, which is what the build hands out: packaging MCP Gate put the smoke run's `data/mcp_gate.db` (with its
  signing keys), `secrets/secrets.json` (encryption key and setup token) and `logs/` into the downloadable archive,
  so every deployment of that build would have started with the same keys. Whatever the program creates there is
  removed after the run, and existing files it changed are named in the build log.
### Fixed
- A Git build with no image name set is named after the repository (`mcp_gate:1.4.0`), as the docs say. It was
  named after the workspace the repository is cloned into, which is the task id, so every build made a new
  repository such as `be1d3c22-b30d-479d-8cc7-101d31c6ec90:1.3.1`. The Commands tab shows the same name.
- Git builds no longer ship the project's development tools. The `.venv` was created with `uv sync`, which also
  installs the `dev` dependency group, and External mode copies the whole `.venv` into `libs/`: packaging MCP Gate
  put pytest, pytest-asyncio, pytest-cov, pytest-mock, coverage and ruff into its binary's `libs/` and Docker image.
  The bootstrap now runs `uv sync --no-default-groups`, plus `--group <name>` for a group chosen in the build settings.

## [1.3.2] — 2026-11-13

### Changed
- Docs: roadmap and README rewritten. `ROADMAP.md` and `ROADMAP.zh-TW.md` list what shipped and the plan for
  1.3.2 to 1.7, each item with a GitHub issue under its milestone; the READMEs lead with a screenshot, key
  features, installation and a quick start, and the build pipeline, main settings, storage and Git
  credentials sections moved to `docs/how-it-works.md` (and `.zh-TW.md`).
- `MCP_CENTER_URL`, MCP Gate's name before its rename, is no longer read as a fallback for `MCP_GATE_URL`;
  set `MCP_GATE_URL` instead.
- Dependencies updated within their major versions, both lock files regenerated: Nuitka 4.3.5, uvicorn
  0.54, FastAPI 0.162.6, SQLAlchemy 2.1.8, asyncpg 0.32, psycopg2-binary 2.9.13, cryptography 50.0.2, pytest
  9.2; TanStack Query 5.107, Recharts 3.10, Zustand 5.1, Vite 7.3.8, Tailwind CSS 4.3, typescript-eslint 8.72.
  The Docker image now copies uv 0.13.8 and the Docker 28 CLI, and CI uses `actions/setup-python@v7` and
  `actions/cache@v6`. TypeScript 7 and Node 25 stay out until they pass CI, and `eslint-plugin-react-hooks`
  stays on 7.0 (7.1 turns on rules the console does not pass yet).

### Security
- `minimatch` under typescript-eslint is held at 11.0.1 or later (GHSA-g3hv-75wg-m249, a denial of service
  through crafted glob patterns). It is a lint-time dependency only and never reaches the built console.

### Fixed
- A role's parent can be removed. Clearing the parent in the Roles dialog sent `parent_role_id: null`, which
  `PUT /api/users/roles/{id}` read as "unchanged", so a parent could be set but never taken away. Null now
  clears the parent, leaving the field out keeps it, and `0` still clears it as before. Removing a parent
  goes through the same check as any role change: it is refused if no active account would be left able
  to manage roles. The dialog's empty parent field reads "No parent role".

## [1.3.1] — 2026-11-09

### Fixed
- A role change can no longer lock everyone out. Deleting or deactivating a built-in role was refused, but
  emptying its permissions was not: one `PUT /api/users/roles/1` with an empty list took every permission
  from the admin role, and with it the only way to give them back. A role change (permissions, parent or
  deactivation) that would leave no active account holding `role:manage` is now refused. Parent roles can
  no longer form a loop, and unknown permission codes are refused with their names instead of being
  dropped silently.
- A stored Git credential the host refuses (expired, revoked) no longer blocks that host's public
  repositories: the request is retried once without it, and a build's log says the credential needs
  updating. A private repository still fails with the original error.
- Browsing no longer signs you out. The API allowed 60 requests a minute per address, which one person
  reached in about 20 page loads (a page makes one to five calls), and a 429 on the session check sent a
  signed-in person to the sign-in page. The allowance is now 300 a minute and 6000 an hour, set with the new
  `RATE_LIMIT_PER_MINUTE` and `RATE_LIMIT_PER_HOUR`, and a rate-limited session check waits as long as the
  server asks (up to 90 s, with a note on the loading screen) and tries again instead.
- Building a project's new version is rate limited like any other build submission. `POST
  /api/projects/{id}/builds` had no limit, while `POST /api/tasks` refused the 21st build a minute; both now
  share `BUILD_SUBMIT_PER_MINUTE`.
- A build waiting for its folder no longer holds a build slot. Builds of one local folder run one at a time,
  but the second one took a slot first and then waited for the folder, so with the default three slots,
  three builds of one project stopped every other build on the server. A local build now waits for its
  folder first ("Queued — another build of this folder is running"), then for a slot.
- A local-mode build's download is now that build's output and nothing else. The output directory in the
  project folder was never emptied, so it collected every earlier build's files (a folder build's archive
  also held the one-file binary and `libs/` of the build before it, and a Docker build copied them into
  the image), and Download packed the folder when it was clicked, so a build downloaded after another
  build of the same folder served the other build's binary. The output directory is now emptied before a
  local build (unless it is the project itself or holds anything the build reads; the log says so), and a
  successful build's output is kept under `GIT_WORKSPACE_DIR/<task-id>/` (hard links on the same
  filesystem) and downloaded from there until `WORKSPACE_SUCCESS_TTL_DAYS` expires it. Builds from
  before this change still download from the folder.
- A Git credential's host is checked. `https://x.com/`, `localhost`, `a b.com` or a host with a port were
  accepted, could never match a clone URL (credentials are found by its host name), and the page then said
  builds clone from `https://https://x.com//`. They are now refused with a message saying what to enter, the
  form checks as you type, the host is stored in lower case without a trailing dot, and credentials saved
  earlier with such a host are marked on the page. A token shorter than 16 characters no longer shows its
  last four as a hint, which for a four-character token was all of it.

### Security
- The entry point must be a file inside the project. Output, data, extra-code and frontend directories were
  confined to the project, but the entry point was not: `entry_point="../../elsewhere/app.py"` on a local
  build was accepted, the libs loader was written into that file outside `LOCAL_SOURCE_ROOTS`, and it was
  compiled and packaged. Builds (local and Git, including a project's new versions and settings) and the
  project analysis now refuse an absolute, `..` or symlinked-out entry point with 400, and the Nuitka worker
  checks the resolved path again before touching it, which also covers a symlink committed to a Git repo.
- Git no longer uses the server's own git login. Clones, ref listings and scans ran with the service
  account's `HOME`, so its `~/.gitconfig` and `/etc/gitconfig` applied, credential helpers included: with
  `gh auth git-credential` configured there, anyone allowed to build could clone whatever that GitHub login
  could reach, and a failed login made git tell the helper to erase the credential. git now runs with no
  system or global configuration, no credential helper and an empty `HOME` (so no `~/.netrc` either); only
  the credentials stored in Packwright are sent. Proxy and CA settings reach git through `HTTPS_PROXY`,
  `NO_PROXY`, `GIT_SSL_CAINFO`, `SSL_CERT_FILE` and similar variables instead of git configuration.

## [1.3.0] — 2026-11-09

### Fixed
- The frontend test run sometimes failed with `window is not defined` although every test passed. React
  work queued outside `act()` (antd's message countdown sets state on every animation frame) could run
  after Vitest had removed jsdom's globals. Tests now run in `test-env/settledJsdom.ts`, Vitest's jsdom
  environment with a teardown that stops jsdom's timers, lets the work already queued finish, and only
  then removes the globals.

### Security
- Builds no longer inherit the service's whole environment. Frontend builds, Docker builds and the Nuitka
  compile run the project's own code, and under a systemd `EnvironmentFile=` or a container
  `environment:` block that environment holds `JWT_SECRET_KEY` and `SETTINGS_ENCRYPTION_KEY` — enough
  for anyone who may start a build to sign an admin token and decrypt every stored Git credential. They
  now get only the basics, proxy and CA settings, tool configuration (`NPM_CONFIG_*`, `YARN_*`,
  `DOCKER_*`, `CCACHE_*`, …) and the names listed in the new `BUILD_ENV_PASSTHROUGH` setting.

## [1.2.0] — 2026-11-06

### Added
- **Projects.** The code the team builds again and again is now a project: its source, the settings new
  versions start from, and every build of it, grouped by version. **Projects** lists them; a project's
  page shows each version with its latest outcome, its builds and a download of the last one that
  passed, and *Build a new version* starts one in a dialog that reads the version from the code, picks
  the branch or tag for Git projects, takes the usual settings for this build only, and says when that
  version already passed. Projects are shared by everyone who may build; their creator and holders of
  the new `project:manage` permission may rename or delete one (its builds stay). Every build is filed
  under a project — the one it was built from, or the project with its name and source, created on the
  first build — and upgrading files existing builds the same way.
- **Project settings.** A project's page has *Settings*: the settings new versions are built with, as
  tabs (General, Backend, Frontend, Docker, Commands) that reuse the New build steps. A field the project
  itself states (type, entry point, frontend directory, build tool and command, output directory) says
  whether it matches, or offers the project's value with *Use it*. *Commands* shows the Nuitka, npm and
  docker lines a build would run, worked out by the same code the build uses, with notes on what only a
  build can find out. Saving is for the project's creator and project managers.
- **Versions.** A build can say which version of the project it is: read from the Git tag, pyproject.toml
  or package.json, shown on New build and changeable. The version names the download
  (`shop-1.2.0.tar.gz`), tags the Docker image (`shop:1.2.0`, with the `org.opencontainers.image.version`
  label and `PACKWRIGHT_BUILD_VERSION`), and is written into a `VERSION` file beside the output and
  inside the program, next to its main module. Building a version that already passed asks first.
- **Notifications.** A project's settings have a *Notifications* tab: Discord, Slack or any URL that
  takes JSON, each sent when a build fails, passes or both. A failure says what went wrong (the
  diagnosis), a pass who built it and how long it took; with `PUBLIC_URL` set the message links to the
  build. Webhook URLs are stored encrypted and only their host and last characters are shown; *Send test*
  checks one, and the tab shows whether the last message arrived. Messages go out after the build,
  outside its build slot, so a dead webhook never holds up builds. No mail server is needed.
- **Quick build.** New build now opens on one screen that needs only a source: a folder on the server or
  a Git repository and branch. Packwright reads the project (a Python entry point or pyproject.toml, a
  package.json and where it is) and shows what it found row by row: backend, frontend or full stack, the
  entry point, the frontend directory and build command, the Python version and dependency groups. A
  wrong type is corrected in place; an unrecognised project has to be given one before it can start.
  The settings people change most (packing, one file or a folder, the start-up check, a Docker image)
  are changed in place, and every other one is listed with the value it will use and a *Change* link to
  its step in the full wizard. *All settings* opens that wizard with everything already found filled
  in; rebuilds go straight there. A source the server may not read says why. Git scans now return the
  same fingerprints a local path gets.
- **Animations that explain.** A first build is preceded by a short animation of what happens to the
  code (on an empty home page and on Quick build before a source is given); found settings pop in as
  they are read; and a running build shows a stage track whose current stage pulses and whose rail
  fills as it advances, for every project type (it used to be backend-only). All of them hold still
  when the system asks for reduced motion.

- **Compile cache.** With [ccache](https://ccache.dev/) installed on the build host, Nuitka reuses the C
  files that did not change, and a rebuild can be several times faster (a Full-mode build of a small app:
  123 s, then 21 s rebuilt from a fresh clone). Packwright now says whether that is happening: the
  **Machine** page shows the compile cache on or off, how big it is and where it lives, and tells how to
  turn it on; each build's log and result say how many C files came from the cache. `NUITKA_CACHE_DIR`
  moves Nuitka's cache, with the ccache store, to another directory.

- **Docker image.** `docker compose up -d` runs Packwright with everything its builds need: the Nuitka
  toolchain for Python 3.12 to 3.14, ccache, Node.js with npm, yarn and pnpm, git and the docker CLI.
  Everything it keeps is in one volume, so recreating the container keeps the database, the generated
  secrets (nobody is signed out), the builds and the compile cache. Builds run as an unprivileged user.
  CI builds the image and runs two real builds in it on every change.

### Changed
- **Users, Roles and Git credentials have a new layout.** The page is called Users again (it was People
  in 1.1.0). Accounts waiting to be let in are listed first, with an Activate button; the list tells a
  new registration (Waiting) from an account that was switched off (Disabled), filters by status with
  a count each, and changes a role in place. Roles are cards that group their permissions by category
  and say who inherits what and how many users have the role. Git credentials are cards that say which
  clones use them and when they were last used.
- **Builds share the cores.** A build that leaves CPU jobs on Auto used one compile job per core even
  when other builds were running, so three builds on a 128-core machine ran 384 compilers. Auto now uses
  every core for a build that runs alone and an equal share (at least 4) when several run together; the
  build log says which. A CPU jobs value set on the form is used as before.
- **Machine load is collected once for everyone.** Each Machine and home page poll collected it from
  scratch, sleeping 0.2 s and reading a file per core; one open Machine page cost the server about 13x
  its idle CPU, and each extra viewer as much again. One snapshot is now shared for 1.5 s, the core
  frequency is re-read every 10 s, and the GPU probe is skipped on machines without nvidia-smi.

### Fixed
- **External builds of any project with a dependency failed when started.** Nuitka 4 compiles an
  ImportError into the program for every package it was told not to compile, and External mode tells it
  exactly that so the packages can come from `libs/`; the program then refused its own `libs/`
  ("Module 'starlette' was actively excluded from Nuitka compilation") and the start-up check failed the
  build. External and *One file* is New build's default. The guard is now turned off when packages are
  left to `libs/`.
- **New build suggested folders that broke the program.** It ticks the folders it suggests; for a project
  like MCP Gate it compiled the Alembic migrations in as Python (the program then could not find
  `alembic/` and stopped), shipped `tests/` and `examples/`, and copied `docs/` and the frontend's sources
  beside the binary. Top-level tests, examples, docs and benchmarks are now skipped, a folder with its own
  `package.json` is left to the frontend step, and Alembic migrations (`env.py` beside `versions/`) are
  copied as data.
- **A program that could not start passed as "no GPU on the build host".** Any output containing "failed
  to initialize" (for example "Failed to initialize database") was excused as a missing GPU, and the build
  was marked completed. Only a failure that names a GPU (CUDA, ROCm, HIP, NVML) is excused now.
- **Every build of a service left it running on the build host.** A onefile binary is a launcher that
  starts the real program; the start-up check stopped only the launcher, so the program kept running and
  held its port (the next build then failed with "port already in use"). The whole process group is
  stopped now.
- Quick build showed a project it had just recognised as "Could not tell from the files", without its
  backend settings, for one render after reading it: the page watched the project type, which is only on
  screen once the project is read, in a way that reports an absent field as empty. It also made a
  frontend test fail now and then on a busy machine.
- A rebuild's frontend build tool, command and output directory were replaced by whatever detection found
  as soon as the form opened. Detection now fills only fields nobody set on a new build, and offers its
  values next to the fields of a stored config.
- An option added to the Nuitka command after the program file would have been taken as an argument to
  the program; the program file is always last.
- An image without a configured name was tagged with the project folder's name as it was, and Docker
  refuses upper-case repository names, so a folder like `MCP_Center` could not be built into an image.
  The default name is lowercased.
- Builds started within the same second had no order on SQLite (its timestamp keeps whole seconds); the
  start time is now set to the microsecond.
- The Machine page reported the logical core count as the physical one ("128 threads on 128 cores").

## [1.1.0] — 2026-11-06

### Changed
- **The console is redesigned.** Warm graphite with a brass accent, and teal for anything running; a
  narrow tool rail, a quick jump to any page or recent build (Ctrl/Cmd+K), and one page heading on every
  screen. The home page (**On the bench**) lists running and recent builds by day: a running build shows
  its stage and last log lines, and three or more cancelled builds in a row fold into one line. Beside it
  are the last 30 days and the machine's load. **Builds** is a searchable list with a count per status,
  **Machine** shows every core as one cell, and **Users** is now **People**. Deactivating someone asks
  first, and isn't offered on your own account (the server refused it anyway).
- **Sign-in has its own layout**: the form on a narrow strip, and beside it what a build goes through
  (Preflight, Compile, Bundle, Verify, Image). Registering and password recovery use the same frame; on
  phones it is the form alone.
- **New icons and mark.** The console draws its icons from Phosphor instead of antd's built-in set
  (`components/ui/icons.tsx` is the one place to import them from), and the logo and browser-tab icon
  are a new P whose bowl closes like a box flap.
- **`pack_mode` defaults to `external` in the API**, as the console already did; leaving it out used
  to select `full`, which compiles every dependency and takes hours. Stored builds keep their mode.
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
- Backend messages are in English, like the console: failure diagnoses and their suggested actions,
  validation errors, build-log lines and the project-scan labels.

### Added
- `docs/configuration.md` documents every setting with its default. The manual
  (`docs/manual.zh-TW.md`) is rewritten for the current release: it described one particular machine
  (paths, a LAN host, a PostgreSQL-only install, a removed path allow-list) and older flows.
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
- **Source code to bundle** passed a selected file to `--follow-import-to` by its file name and to
  `--include-data-dir`, which only takes directories. A `.py` file is now one module, any other file a
  data file (`--include-data-files`).
- A missing `package.json` was reported as an unknown failure; it now points at the frontend directory.
  The dependency-install diagnosis also recognises npm 10, which writes `npm error` instead of `npm ERR!`.
- **Dependency group** asked for the project path even after one was entered, when the project simply
  defines no groups. It now says whether pyproject.toml was read, had no groups, or could not be read.
- The Builds list and home page did not show an output's size or smoke test: the history list left the
  build result out. It now carries the parts a row shows (size, smoke test, failed stage, first
  diagnosis), not the preflight checks and error lines the detail page has.
- Success rates counted cancelled and running builds as failures. They count only builds that passed or
  failed now, in the summary, per day (which gains `failed`) and per project.
- The sessions list marked every sign-in from the same address as "this device", so the current one
  couldn't be told apart from the rest, or kept while signing the others out. Access tokens now carry
  `sid`, the sign-in they belong to; tokens issued before this mark none until they're refreshed.
- Times in the console were read as the browser's local time, but the server sends UTC without a zone, so
  in a UTC+8 browser they were eight hours off (people, login history, Git credentials, build detail).
- The same project produced a differently ordered Nuitka command on every build: the installed
  packages it excludes were listed in set order, which changes with each process. They are sorted.
- The Builds page showed an empty "Build result" card for builds whose result held only a duration,
  never showed which stage a failed build stopped in, and listed Nuitka settings (pack mode,
  one-file) for frontend-only builds. The task and history pages now share one failure report and
  one result panel instead of two drifting copies.
- **Cancel did not stop most of a build.** Only the top process was signalled: Nuitka's scons and
  gcc children and npm's node children kept running (reparented to init) while the build showed as
  cancelled, Cancel did nothing at all to a frontend install or build, and a cancelled full-stack
  build started its next step anyway. Each build step now runs in its own process group that Cancel,
  timeouts and the end of the step stop as a whole, and no step starts once a build is cancelled.
  Cancelling a full-stack build during its frontend step stops the backend (and Docker) steps too,
  and the build reads "Cancelled by user" instead of the step's "failed" message.
- `scripts/backup_db.sh` backs up SQLite (the default) as well as PostgreSQL, and finds the database
  the way the service does: it used to read only `DB_*`, so it dumped the wrong database when
  `DATABASE_URL` was set and could not back up a default install at all. A failed backup leaves no
  partial file and rotates nothing.
- **A failed frontend build replaced the project's `.env` for good.** The configured env content
  was written over it, the original was kept only in memory, and a failed install or build returned
  before the restore. Files a local-source build changes (frontend env file, entry-point loader,
  `.dockerignore`, `Dockerfile.generated`) are now journaled on disk before the change and put back
  on every exit; journals left by a crash are replayed at the next startup. An entry point left with
  the loader by an earlier crash is restored from its `.py.backup` on the next build.
- Started from a directory other than its own, the service generated a new JWT and encryption key
  on every start (everyone logged out, stored Git credentials undecryptable): the generated keys
  were written to the `.env` beside `main.py` but only the launch directory's `.env` was read. Both
  are read now, and a key that cannot be saved is reported in the log.
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
- A failed frontend or Docker build was explained as having "ended while it was still queued": only
  the Nuitka worker recorded a build stage. Those steps now record theirs, with matching messages.
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

[Unreleased]: https://github.com/xianhong1208/packwright/compare/v1.3.2...dev
[1.3.2]: https://github.com/xianhong1208/packwright/compare/v1.3.1...v1.3.2
[1.3.1]: https://github.com/xianhong1208/packwright/compare/v1.3.0...v1.3.1
[1.3.0]: https://github.com/xianhong1208/packwright/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/xianhong1208/packwright/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/xianhong1208/packwright/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/xianhong1208/packwright/releases/tag/v1.0.0
