"""
Tests for what the generated backend Dockerfile stores.
Source: app/services/docker_worker.py (_generate_dockerfile, _outermost_dirs)

Packaging MCP Gate showed two layers that stored files a second time: a RUN chmod
after the binary's COPY (49.7 MB again), and the frontend output copied both as
part of static/ and as static/web/.
"""

import pytest

from app.schemas.task import BuildConfig
from app.services.docker_worker import _generate_dockerfile


@pytest.mark.unit
def test_tc_dlay_001_no_layer_stores_a_file_twice(tmp_path):
    """TC-DLAY-001: the binary gets its mode on the COPY, and a data dir inside
    another listed one is not copied a second time."""
    for d in ("static/web", "config"):
        (tmp_path / "dist" / d).mkdir(parents=True)
    config = BuildConfig(
        project_type="fullstack", project_path=str(tmp_path), docker_enabled=True,
        output_name="main", data_dirs="config, static, static/web, ./config",
    )
    dockerfile = _generate_dockerfile(config, precompiled=True)

    assert "COPY --chown=app:app --chmod=755 dist/main ./" in dockerfile
    assert "chmod +x" not in dockerfile
    assert "chown -R" not in dockerfile
    copies = [line for line in dockerfile.splitlines() if line.startswith("COPY --chown=app:app dist/") and "libs" not in line]
    assert copies == ["COPY --chown=app:app dist/config/ ./config/", "COPY --chown=app:app dist/static/ ./static/"]
