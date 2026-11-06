"""Process-wide test environment, applied before any ``app`` module is imported.

app.config caches Settings and app.database builds its engine at import time,
so these must be in os.environ first. Unit tests touch no database, but without
this they would still point at ./data/build_center.db, and app.services.auth
would append a freshly generated JWT_SECRET_KEY to the repository's .env when
none is set. Everything here lives in a throwaway directory.
"""

import os
import tempfile

from cryptography.fernet import Fernet

_TMP = tempfile.mkdtemp(prefix="packwright-tests-")

os.environ.update({
    "DATABASE_URL": f"sqlite+aiosqlite:///{_TMP}/test.db",
    "JWT_SECRET_KEY": "test-only-jwt-secret-" + "x" * 32,
    "SETTINGS_ENCRYPTION_KEY": Fernet.generate_key().decode(),
    "GIT_WORKSPACE_DIR": os.path.join(_TMP, "workspace"),
    "DOCKER_IMAGES_DIR": os.path.join(_TMP, "docker_images"),
    "BOOTSTRAP_ADMIN_USERNAME": "admin",
    "BOOTSTRAP_ADMIN_PASSWORD": "integration-admin-pass",
    "WORKSPACE_CLEANUP_ENABLED": "false",
    # The integration suite submits more than the default 20 builds a minute from
    # one address; the limiter itself is covered by tests/unit/middleware.
    "BUILD_SUBMIT_PER_MINUTE": "1000",
})
