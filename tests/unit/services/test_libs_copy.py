"""
Tests for what External mode copies into libs/, and the onefile compression check.
Source: app/services/nuitka_worker.py (ships_in_libs, has_zstandard)

uv installs a Git project itself in editable mode. Its finder,
__editable___<name>_finder.py, pointed at the deleted build workspace and was
copied into libs/ and every Docker image.
"""

import sys

import pytest

from app.services.nuitka_worker import has_zstandard, ships_in_libs


@pytest.mark.unit
@pytest.mark.parametrize(
    "name",
    ["__editable___mcp_gate_1_4_0_finder.py", "__editable__.mcp_gate-1.4.0.pth", "_mcp_gate.pth",
     "pip", "setuptools", "nuitka", "__pycache__", ".lock", "_distutils_hack"],
)
def test_tc_dlib_008_left_out_of_libs(name):
    """TC-DLIB-008: ships_in_libs — the editable finder, .pth hooks and packaging tools stay out."""
    assert ships_in_libs(name) is False


@pytest.mark.unit
@pytest.mark.parametrize(
    "name", ["fastapi", "_cffi_backend.cpython-313-x86_64-linux-gnu.so", "mcp_gate-1.4.0.dist-info", "typing_extensions.py"]
)
def test_tc_dlib_009_packages_are_copied(name):
    """TC-DLIB-009: ships_in_libs — real packages, underscore extensions and dist-info are copied."""
    assert ships_in_libs(name) is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_dlib_010_zstandard_check(tmp_path):
    """TC-DLIB-010: has_zstandard — true for this venv (nuitka[onefile]); false for a missing interpreter."""
    assert await has_zstandard(sys.executable) is True
    assert await has_zstandard(str(tmp_path / "no-python")) is False
