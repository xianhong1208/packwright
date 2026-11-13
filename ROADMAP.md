# Roadmap

[繁體中文](ROADMAP.zh-TW.md)

Where Packwright is going after 1.3. Each line names what users get, not how it is built. Versions are
minor releases unless a change breaks something. Every item has an issue under its
[milestone](https://github.com/xianhong1208/packwright/milestones).

## Shipped

**1.0.0 (2026-09-10), the first release, as Build Center.** Python compiled with Nuitka, frontends
built with npm, yarn, pnpm or bun, both packaged together and optionally exported as a Docker image,
from a web console with live logs, accounts and role-based permissions. Git credentials per host,
SQLite by default and PostgreSQL through `DATABASE_URL`, optional sign-in through MCP Center (now MCP
Gate).

**1.1.0 (2026-11-06), renamed to Packwright and redesigned.** A new console (the *On the bench* home
page, a tool rail, a quick jump with Ctrl/Cmd+K) and a new sign-in page; no default admin password;
`docs/configuration.md` documents every setting; CI and Dependabot; security fixes for download
tickets, Git downloads and the GitLab token fallback.

**1.2.0 (2026-11-06), projects and versions.** Builds are filed under shared projects with their
versions, read from the Git tag, `pyproject.toml` or `package.json` and stamped into the download, the
image tag and a `VERSION` file. Project settings with a preview of the commands a build will run;
**Quick build**, which reads a folder or a Git URL and starts with one click; build notifications to
Discord, Slack or any JSON webhook; a compile cache with ccache; a Docker image and `docker compose`
setup with everything builds need; builds share the machine's cores.

**1.3.0 (2026-11-09), builds no longer see the service's secrets.** A build gets only the basics, proxy
and CA settings, tool configuration and the names listed in `BUILD_ENV_PASSTHROUGH`; the flaky frontend
test run is fixed.

**1.3.1 (2026-11-09), fixes from a full review.** A role change can no longer lock everyone out; a local
build's download is that build's output only; the entry point must be inside the project; git never
uses the server's own git login; browsing no longer hits the rate limit; a build waiting for its folder
no longer holds a build slot; Git credential hosts are checked.

See [CHANGELOG.md](CHANGELOG.md) for every change.

## Next

| Version | What you get |
|---|---|
| **1.3.2: up-to-date dependencies and a roles fix** | The open dependency updates, applied together and checked with a real build (TypeScript 7 and Node 25 are left out until they pass CI). The **Roles** dialog can clear a role's parent; today the change is silently ignored. |
| **1.4: automation** | **Build on push or tag:** webhooks from GitHub, GitLab and Gitea, each checked by its signature, plus a generic URL with a token for anything else. **Scheduled builds** for a project. **API tokens**, so scripts and CI can start builds and download results without a password. **`packwright.toml` in the repository:** a project can keep its build settings next to its code; the file wins field by field, and the console marks which values came from it. |
| **1.5: artifacts and publishing** | Every build comes with **`SHA256SUMS`, a manifest and a CycloneDX SBOM**. **Keep the last N artifacts** per project, and **caps for the build caches** (Nuitka, uv, npm) with a sweep, so the disk stops growing. **Publish after a successful build:** files to GitHub or Gitea Releases, and the image pushed to **any registry** (Docker Hub, GHCR, Gitea or a private one). Their tokens are stored encrypted, like Git credentials. |
| **1.6: isolation** | Each build runs **as a separate user or in its own container**, so it can no longer read the service's files or other builds. **Per-project secrets**, stored encrypted and given only to that project's builds. |
| **1.7: more platforms** | **Remote build agents** for Windows, macOS and arm64, so one console builds for all of them. **Code signing:** Authenticode on Windows, signing and notarization on macOS. |

## Later

- **An MCP interface behind MCP Gate.** Start builds, follow them and fetch results from an AI client,
  with MCP Gate's tokens deciding who may do what.
