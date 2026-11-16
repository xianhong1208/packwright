"""Which TCP ports a smoke-tested program listens on, and whether that is the
port its Docker image exposes.

Quick build suggested port 8000 for MCP Gate, the image said `ENV PORT=8000` and
`EXPOSE 8000`, and MCP Gate listened on its own SERVER_PORT: the image built,
passed, and answered nothing on the port it published. The smoke test now
watches which ports the program opens and says so when they differ. The
setting is never changed for the user: a program can listen on several ports,
and only they know which one is the service.
"""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from pathlib import Path

_LISTEN = "0A"  # TCP_LISTEN in /proc/net/tcp


@dataclass(frozen=True, order=True)
class Listener:
    port: int
    address: str

    @property
    def loopback(self) -> bool:
        try:
            ip = ipaddress.ip_address(self.address)
        except ValueError:
            return False
        # Python 3.13 counts IPv4-mapped ::ffff:127.0.0.1 as loopback too.
        return ip.is_loopback


def _decode_address(hex_addr: str) -> str:
    """/proc/net/tcp writes addresses as 32-bit words in host (little-endian) order."""
    raw = bytes.fromhex(hex_addr)
    words = b"".join(raw[i:i + 4][::-1] for i in range(0, len(raw), 4))
    return str(ipaddress.ip_address(words))


def parse_proc_net_tcp(text: str, inodes: set[str] | None = None) -> set[Listener]:
    """The listening sockets in /proc/net/tcp or tcp6 text, optionally only those
    whose socket inode is in `inodes` (a process's own sockets)."""
    found: set[Listener] = set()
    for line in text.splitlines()[1:]:
        fields = line.split()
        if len(fields) < 10 or fields[3] != _LISTEN:
            continue
        if inodes is not None and fields[9] not in inodes:
            continue
        addr, _, port = fields[1].partition(":")
        try:
            found.add(Listener(int(port, 16), _decode_address(addr)))
        except ValueError:
            continue
    return found


def _group_socket_inodes(pgid: int, proc: Path = Path("/proc")) -> set[str]:
    """The socket inodes held by every process in a process group.

    The smoke-tested binary runs in its own group (a onefile launcher and the
    program it starts), so the group is exactly the program.
    """
    inodes: set[str] = set()
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
            # pid (comm) state ppid pgrp …; comm may contain spaces and parentheses.
            if int(stat.rsplit(")", 1)[1].split()[2]) != pgid:
                continue
            for fd in (entry / "fd").iterdir():
                target = os.readlink(fd)
                if target.startswith("socket:["):
                    inodes.add(target[8:-1])
        except (OSError, ValueError, IndexError):
            continue
    return inodes


def group_listeners(pgid: int, proc: Path = Path("/proc")) -> set[Listener]:
    """The TCP ports a process group listens on, read from /proc (Linux only)."""
    inodes = _group_socket_inodes(pgid, proc)
    if not inodes:
        return set()
    found: set[Listener] = set()
    for name in ("tcp", "tcp6"):
        try:
            found |= parse_proc_net_tcp((proc / "net" / name).read_text(), inodes)
        except OSError:
            continue
    return found


def port_check(listeners: set[Listener], expected: int, *, container: bool = False) -> dict | None:
    """Compare what the program listens on with the image's EXPOSE/PORT.

    Returns None when it listens on nothing (a CLI tool, or it exited first).
    Otherwise the ports, the expected one, and when they disagree a message and
    the suggested value: the lowest port on a non-loopback address, else the
    lowest. In a container (`container=True`) a program that listens only on
    loopback cannot be reached through a published port either, so that is
    reported too.
    """
    if not listeners:
        return None
    ports = sorted({lst.port for lst in listeners})
    reachable = sorted({lst.port for lst in listeners if not lst.loopback})
    result: dict = {"listening": ports, "expected": expected, "suggested": None, "message": ""}
    if expected not in ports:
        suggested = (reachable or ports)[0]
        result["suggested"] = suggested
        shown = ", ".join(str(p) for p in ports)
        result["message"] = (
            f"The program listens on {shown}, but the image exposes {expected} (EXPOSE and PORT). "
            f"Set Exposed port to {suggested}, or make the program use {expected}."
        )
    elif container and expected not in reachable:
        result["message"] = (
            f"The program listens on {expected} only on 127.0.0.1 inside the container, so the published "
            "port reaches nothing. Make it listen on 0.0.0.0 (the image sets HOST=0.0.0.0)."
        )
    return result
