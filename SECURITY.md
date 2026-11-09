# Security policy

## Report a vulnerability

Please report security issues privately through GitHub's
[security advisories](https://github.com/xianhong1208/packwright/security/advisories/new), not in a
public issue. Include the version (`/health` reports it), what you did and what happened.

## Supported versions

Only the latest release on `main` receives security fixes.

## Trust model

Packwright builds other people's code, so **`task:create` is effectively code execution on the build
host**: a Git build clones a repository and runs its `npm install` scripts, and the smoke test runs
the compiled binary. That is inherent to a build server.

The security boundary is therefore **account approval**: self-registered accounts start inactive
and an administrator must activate them. Path confinement, Git URL validation, argv-only
subprocesses, token masking and rate limiting are defence in depth, not a sandbox.

Run Packwright on a dedicated host or VM, behind HTTPS, and only for people you would give a shell.

## Known limitations

- **Single process.** Task state, WebSocket connections and the build semaphore live in memory, so
  run one server process (no multiple uvicorn workers).
- **Build environment values are stored in plain text.** The `.env` content and Docker runtime
  variables entered for a build are kept in the build history and shown to whoever can read that
  history, unmasked, by design: the history is how users see how a working build was configured,
  and anyone who can read it can already run a build. Treat the database and its backups as
  secrets.
- **Builds run as the service user.** They do not inherit the service's environment — only the
  basics, proxy and CA settings, tool configuration and what `BUILD_ENV_PASSTHROUGH` lists — so
  `JWT_SECRET_KEY` or `SETTINGS_ENCRYPTION_KEY` passed through systemd or a container stays out of
  them. They can still read any file that account can, including `.env` and the database. Prefer a
  dedicated, unprivileged service account over root, and keep secrets readable only by it.
- **First start.** Without `BOOTSTRAP_ADMIN_PASSWORD`, a random admin password is printed once in the
  startup log; sign in and change it.
- **Behind a proxy.** `X-Forwarded-For` is honoured only from addresses in `TRUSTED_PROXY_IPS`; leave
  it empty unless a proxy really sets the header.
- **SSRF.** Without `GIT_ALLOWED_HOSTS`, Git URLs that are IP literals in private, loopback or
  link-local ranges are refused, but host names are not resolved first. Set `GIT_ALLOWED_HOSTS` to
  the Git servers you use for a strict allow-list.
