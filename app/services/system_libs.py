"""Which system packages a backend Docker image installs.

Every backend image used to install the same list, GUI and OpenGL libraries
included: 221 MB for MCP Gate, which loads none of them (libgl1 alone pulls in
Mesa and LLVM). Only some dependencies need them, OpenCV and Qt above all, and
those say so in their compiled extensions: an ELF file lists the shared
libraries it loads (DT_NEEDED). So the image gets the small base list always,
and a GUI/graphics package only when a shipped .so asks for one of its
libraries.

What a program loads with dlopen() or ctypes is not listed anywhere and cannot
be found this way; such packages are added with a custom apt-get command.
"""

from __future__ import annotations

import os
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

# Installed into every backend image, as before: small, and loaded by common
# database and XML packages built against the system copy.
BASE_PACKAGES: tuple[str, ...] = ("libpq5", "zlib1g", "libxml2", "libxslt1.1")

# Shared library (soname without its version) -> the Debian package with it.
# Only libraries a slim Python image lacks are listed; glibc's, libstdc++ and
# the like are always there.
_SONAME_PACKAGES: dict[str, str] = {
    # OpenGL / EGL
    "libGL.so": "libgl1",
    "libGLX.so": "libglx0",
    "libEGL.so": "libegl1",
    "libOpenGL.so": "libopengl0",
    "libGLU.so": "libglu1-mesa",
    # GLib (OpenCV's highgui, GTK and Qt builds)
    "libglib-2.0.so": "libglib2.0-0",
    "libgthread-2.0.so": "libglib2.0-0",
    "libgobject-2.0.so": "libglib2.0-0",
    "libgio-2.0.so": "libglib2.0-0",
    "libgmodule-2.0.so": "libglib2.0-0",
    # X11
    "libX11.so": "libx11-6",
    "libX11-xcb.so": "libx11-xcb1",
    "libXext.so": "libxext6",
    "libXrender.so": "libxrender1",
    "libXi.so": "libxi6",
    "libXrandr.so": "libxrandr2",
    "libXfixes.so": "libxfixes3",
    "libXcursor.so": "libxcursor1",
    "libXcomposite.so": "libxcomposite1",
    "libXdamage.so": "libxdamage1",
    "libXtst.so": "libxtst6",
    "libSM.so": "libsm6",
    "libICE.so": "libice6",
    "libxcb.so": "libxcb1",
    "libxkbcommon.so": "libxkbcommon0",
    "libxkbcommon-x11.so": "libxkbcommon-x11-0",
    # Fonts, desktop bus
    "libfontconfig.so": "libfontconfig1",
    "libfreetype.so": "libfreetype6",
    "libdbus-1.so": "libdbus-1-3",
    # The base list, so a match explains why it is there
    "libpq.so": "libpq5",
    "libz.so": "zlib1g",
    "libxml2.so": "libxml2",
    "libxslt.so": "libxslt1.1",
    "libexslt.so": "libxslt1.1",
    # Other common ones
    "libgomp.so": "libgomp1",
    "libsndfile.so": "libsndfile1",
    "libmagic.so": "libmagic1",
}

# libxcb-icccm.so.4 -> libxcb-icccm4: Qt's xcb plugin needs a dozen of these.
_XCB_EXT = re.compile(r"^libxcb-([a-z0-9-]+)\.so\.(\d+)$")
_SO_SUFFIX = re.compile(r"\.so(\.\d+)*$")

# Reading stops here: no real extension has more sections than this, and a
# corrupt header must not make the build read gigabytes.
_MAX_SECTIONS = 4096
_MAX_DYNAMIC_BYTES = 1 << 20

SHT_DYNAMIC = 6
DT_NULL = 0
DT_NEEDED = 1


def elf_needed(path: Path) -> list[str]:
    """The shared libraries an ELF file asks for (DT_NEEDED), in order.

    Read from the section headers, so only the headers and the dynamic section
    are read, however large the file. Anything that is not a readable ELF file
    gives an empty list rather than an error: this only decides what to
    install, and a file it cannot read is one it cannot say anything about.
    """
    try:
        with open(path, "rb") as f:
            ident = f.read(16)
            if len(ident) < 16 or ident[:4] != b"\x7fELF":
                return []
            is64 = ident[4] == 2
            endian = "<" if ident[5] == 1 else ">"
            if is64:
                f.seek(0x28)
                (shoff,) = struct.unpack(endian + "Q", f.read(8))
                f.seek(0x3A)
                shentsize, shnum = struct.unpack(endian + "HH", f.read(4))
                sh_fmt = endian + "IIQQQQIIQQ"
                dyn_fmt = endian + "qQ"
            else:
                f.seek(0x20)
                (shoff,) = struct.unpack(endian + "I", f.read(4))
                f.seek(0x2E)
                shentsize, shnum = struct.unpack(endian + "HH", f.read(4))
                sh_fmt = endian + "IIIIIIIIII"
                dyn_fmt = endian + "iI"
            if not shoff or not shnum or shnum > _MAX_SECTIONS or shentsize < struct.calcsize(sh_fmt):
                return []
            f.seek(shoff)
            raw = f.read(shentsize * shnum)
            if len(raw) < shentsize * shnum:
                return []
            sections = [struct.unpack_from(sh_fmt, raw, i * shentsize) for i in range(shnum)]
            dyn_size = struct.calcsize(dyn_fmt)
            names: list[str] = []
            for sec in sections:
                sh_type, sh_offset, sh_size, sh_link = sec[1], sec[4], sec[5], sec[6]
                if sh_type != SHT_DYNAMIC or sh_link >= shnum:
                    continue
                strtab = sections[sh_link]
                f.seek(sh_offset)
                dyn = f.read(min(sh_size, _MAX_DYNAMIC_BYTES))
                offsets = []
                for i in range(len(dyn) // dyn_size):
                    tag, val = struct.unpack_from(dyn_fmt, dyn, i * dyn_size)
                    if tag == DT_NULL:
                        break
                    if tag == DT_NEEDED:
                        offsets.append(val)
                f.seek(strtab[4])
                strings = f.read(min(strtab[5], _MAX_DYNAMIC_BYTES))
                for off in offsets:
                    end = strings.find(b"\0", off)
                    if 0 <= off < len(strings) and end > off:
                        names.append(strings[off:end].decode("utf-8", "replace"))
            return names
    except (OSError, struct.error):
        return []


def package_for(soname: str) -> str | None:
    """The Debian package that provides a shared library, or None when unknown."""
    m = _XCB_EXT.match(soname)
    if m:
        return f"libxcb-{m.group(1)}{m.group(2)}"
    base = _SO_SUFFIX.sub(".so", soname)
    return _SONAME_PACKAGES.get(base)


def _shared_objects(roots: list[Path]):
    for root in roots:
        if not root.is_dir():
            continue
        for current, _dirs, files in os.walk(root):
            for name in files:
                if ".so" in name and _SO_SUFFIX.search(name):
                    yield Path(current) / name


@dataclass
class SystemPackages:
    """What the image installs, and why each package beyond the base list."""

    packages: list[str]
    # package -> (the library it provides, one file that needs it)
    reasons: dict[str, tuple[str, str]] = field(default_factory=dict)


def system_packages(roots: list[Path]) -> SystemPackages:
    """The base list plus the packages the shared objects under roots need.

    A library one of the scanned files provides itself (wheels bundle theirs in
    <package>.libs/) is not looked up: the bundled copy is what loads.
    """
    files = list(_shared_objects(roots))
    provided = {p.name for p in files}
    packages = list(BASE_PACKAGES)
    reasons: dict[str, tuple[str, str]] = {}
    for path in files:
        for soname in elf_needed(path):
            if soname in provided:
                continue
            pkg = package_for(soname)
            if pkg and pkg not in packages:
                packages.append(pkg)
                root = next((r for r in roots if path.is_relative_to(r)), None)
                reasons[pkg] = (soname, str(path.relative_to(root)) if root else path.name)
    return SystemPackages(packages=packages, reasons=reasons)
