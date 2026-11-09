"""The environment a build step runs with: what the build tools need, nothing else.

A build runs code from the repository being built — npm scripts, a Dockerfile's
RUN lines, the project's own Python while Nuitka compiles it. Anyone with
`task:create` chooses that code, so it must not see the service's environment.
That environment used to be passed whole, and it is not only Packwright's
configuration: it is whatever the shell, systemd unit or container that started
the service carried. Packwright reads its own secrets from .env, so they are
absent when it is started by hand, but a systemd EnvironmentFile= or a container
`environment:` block puts JWT_SECRET_KEY and SETTINGS_ENCRYPTION_KEY in it, and a
build could then sign an admin token and decrypt every stored Git credential.

So a build gets the names below, the tool-configuration prefixes, and whatever
the operator lists in BUILD_ENV_PASSTHROUGH. Anything else a build needs comes
from the project itself (its .env, the Docker ENV block), never from the host.

The smoke test's environment is narrower still (nuitka_worker._SMOKE_ENV_PASSTHROUGH):
it imitates the machine the binary ships to, not the build host.
"""

import os
from collections.abc import Mapping

from app.config import get_settings

# Passed through as they are.
BUILD_ENV_PASSTHROUGH = (
    "PATH", "HOME", "USER", "LOGNAME",
    "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TMPDIR", "TERM",
    # Builds behind a proxy, or reaching a registry signed by a private CA.
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "no_proxy", "all_proxy",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
    "NODE_EXTRA_CA_CERTS",
    # The C compiler Nuitka uses.
    "CC", "CXX",
)

# Tool configuration: registries and their auth, caches, the Docker daemon.
BUILD_ENV_PREFIXES = (
    "NPM_CONFIG_", "npm_config_", "YARN_", "PNPM_", "COREPACK_", "BUN_",
    "DOCKER_", "BUILDKIT_",
    "CCACHE_", "NUITKA_",
)


def build_environment(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """The host variables a build may see, then `extra` on top."""
    listed = set(get_settings().build_env_passthrough_names)
    env = {
        name: value
        for name, value in os.environ.items()
        if name in BUILD_ENV_PASSTHROUGH or name.startswith(BUILD_ENV_PREFIXES) or name in listed
    }
    env.update(extra or {})
    return env
