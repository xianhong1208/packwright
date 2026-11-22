"""
Tests for the system packages a backend Docker image installs.
Source: app/services/system_libs.py, app/services/docker_worker.py (_generate_dockerfile)

Every backend image used to install GUI and OpenGL libraries: 221 MB of MCP Gate's
449 MB image, for a program that loads none of them. They are now installed only
when a shipped shared object lists one of their libraries as DT_NEEDED.
"""

import struct
from pathlib import Path

import pytest

from app.schemas.task import BuildConfig
from app.services.docker_worker import _generate_dockerfile
from app.services.system_libs import BASE_PACKAGES, elf_needed, package_for, system_packages


def make_elf(path: Path, needed: list[str], *, is64: bool = True, little: bool = True) -> Path:
    """A minimal ELF file with a .dynstr and a .dynamic section listing `needed`."""
    e = "<" if little else ">"
    strtab = b"\0"
    offsets = []
    for name in needed:
        offsets.append(len(strtab))
        strtab += name.encode() + b"\0"
    dyn_fmt = e + ("qQ" if is64 else "iI")
    dynamic = b"".join(struct.pack(dyn_fmt, 1, off) for off in offsets) + struct.pack(dyn_fmt, 0, 0)
    ehsize = 64 if is64 else 52
    str_off = ehsize
    dyn_off = str_off + len(strtab)
    sh_off = dyn_off + len(dynamic)
    if is64:
        sh_fmt, shentsize = e + "IIQQQQIIQQ", 64
    else:
        sh_fmt, shentsize = e + "IIIIIIIIII", 40
    sections = [
        struct.pack(sh_fmt, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
        struct.pack(sh_fmt, 0, 3, 0, 0, str_off, len(strtab), 0, 0, 1, 0),  # SHT_STRTAB
        struct.pack(sh_fmt, 0, 6, 0, 0, dyn_off, len(dynamic), 1, 0, 8, 16),  # SHT_DYNAMIC -> 1
    ]
    ident = b"\x7fELF" + bytes([2 if is64 else 1, 1 if little else 2, 1]) + b"\0" * 9
    if is64:
        header = ident + struct.pack(e + "HHIQQQIHHHHHH", 3, 62, 1, 0, 0, sh_off, 0, ehsize, 0, 0, shentsize, 3, 0)
    else:
        header = ident + struct.pack(e + "HHIIIIIHHHHHH", 3, 3, 1, 0, 0, sh_off, 0, ehsize, 0, 0, shentsize, 3, 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + strtab + dynamic + b"".join(sections))
    return path


@pytest.mark.unit
@pytest.mark.parametrize("is64,little", [(True, True), (False, True), (True, False)])
def test_tc_dlib_001_reads_needed_libraries(tmp_path, is64, little):
    """TC-DLIB-001: elf_needed — the DT_NEEDED entries, in order, for 64/32-bit and either byte order."""
    so = make_elf(tmp_path / "a.so", ["libGL.so.1", "libc.so.6"], is64=is64, little=little)
    assert elf_needed(so) == ["libGL.so.1", "libc.so.6"]


@pytest.mark.unit
def test_tc_dlib_002_not_an_elf_file_needs_nothing(tmp_path):
    """TC-DLIB-002: elf_needed — a text file, a truncated header or a missing file is an empty list."""
    (tmp_path / "t.so").write_text("not elf")
    (tmp_path / "h.so").write_bytes(b"\x7fELF\x02\x01\x01")
    assert elf_needed(tmp_path / "t.so") == []
    assert elf_needed(tmp_path / "h.so") == []
    assert elf_needed(tmp_path / "missing.so") == []


@pytest.mark.unit
def test_tc_dlib_003_package_names():
    """TC-DLIB-003: package_for — versioned sonames, the xcb extension rule, and unknown libraries."""
    assert package_for("libGL.so.1") == "libgl1"
    assert package_for("libgthread-2.0.so.0") == "libglib2.0-0"
    assert package_for("libxcb-icccm.so.4") == "libxcb-icccm4"
    assert package_for("libc.so.6") is None
    assert package_for("libpq-a17e3caa.so.5.17") is None  # a wheel's own bundled copy


@pytest.mark.unit
def test_tc_dlib_004_base_list_only_without_gui_dependencies(tmp_path):
    """TC-DLIB-004: system_packages — a program whose extensions need only libc gets the base list."""
    make_elf(tmp_path / "libs" / "pkg" / "_ext.cpython-313-x86_64-linux-gnu.so", ["libc.so.6", "libm.so.6"])
    result = system_packages([tmp_path])
    assert result.packages == list(BASE_PACKAGES)
    assert result.reasons == {}


@pytest.mark.unit
def test_tc_dlib_005_gui_packages_when_an_extension_needs_them(tmp_path):
    """TC-DLIB-005: system_packages — an OpenCV-like extension brings libgl1 and GLib, with the reason."""
    make_elf(tmp_path / "libs" / "cv2" / "cv2.abi3.so", ["libGL.so.1", "libgthread-2.0.so.0", "libc.so.6"])
    result = system_packages([tmp_path])
    assert result.packages == [*BASE_PACKAGES, "libgl1", "libglib2.0-0"]
    assert result.reasons["libgl1"] == ("libGL.so.1", "libs/cv2/cv2.abi3.so")


@pytest.mark.unit
def test_tc_dlib_006_a_bundled_library_is_not_installed(tmp_path):
    """TC-DLIB-006: system_packages — a library a wheel bundles itself is what loads; no package for it."""
    make_elf(tmp_path / "libs" / "pkg" / "_ext.so", ["libX11.so.6"])
    make_elf(tmp_path / "libs" / "pkg.libs" / "libX11.so.6", ["libc.so.6"])
    assert system_packages([tmp_path]).packages == list(BASE_PACKAGES)


@pytest.mark.unit
def test_tc_dlib_007_dockerfile_installs_only_what_is_needed(tmp_path):
    """TC-DLIB-007: _generate_dockerfile — no GUI/GL package by default; libgl1 once a shipped .so needs it."""
    config = BuildConfig(project_type="backend_only", project_path=str(tmp_path), docker_enabled=True, output_name="main")
    plain = _generate_dockerfile(config, precompiled=True)
    assert "libpq5 zlib1g libxml2 libxslt1.1" in plain
    for gui in ("libgl1", "libxcb1", "libsm6", "libglib2.0-0", "libxrender1", "libxext6"):
        assert gui not in plain

    make_elf(tmp_path / "dist" / "libs" / "cv2" / "cv2.abi3.so", ["libGL.so.1"])
    assert "libgl1" in _generate_dockerfile(config, precompiled=True)
