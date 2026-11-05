"""Turn a subprocess's PTY output into the lines a terminal would end up showing.

Build tools draw progress bars by rewriting one line in place with ``\\r``. Read
naively — split on ``\\n`` only — every redraw lands in the build log: a hello-world
Nuitka build produced 3,000 log lines (731 KB), 86% of them progress frames, and the
``max_log_lines`` cap pushed the useful head of the log (options, preflight) out
before the build finished. A terminal shows only the last frame, so that is what we
keep; the in-place frame is reported separately so callers can still drive the
progress indicator from it without logging it.
"""
from __future__ import annotations

import codecs
import re

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

# A line with no newline at all (a tool writing one endless line, or binary output)
# would otherwise grow the pending buffer without bound.
MAX_PENDING_CHARS = 64 * 1024


def visible_text(raw: str) -> str:
    """The text a terminal shows for one ``\\n``-terminated chunk: the last non-blank
    ``\\r`` frame, ANSI escapes removed, trailing whitespace stripped."""
    clean = _ANSI.sub("", raw)
    for frame in reversed(clean.split("\r")):
        if frame.strip():
            return frame.rstrip()
    return ""


class TerminalLineBuffer:
    """Incremental PTY decoder: feed it chunks, get back finished lines.

    ``feed`` returns ``(lines, frame)``: ``lines`` are completed, non-empty lines to
    log; ``frame`` is the latest fully drawn in-place frame of the line still being
    written (or ``None``), for progress parsing only.
    """

    def __init__(self) -> None:
        self._pending = ""
        # PTY reads split the stream at arbitrary byte offsets; decoding each chunk
        # on its own turns a multi-byte character cut in half into U+FFFD.
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

    def feed(self, data: bytes) -> tuple[list[str], str | None]:
        self._pending += self._decoder.decode(data)
        lines: list[str] = []
        while "\n" in self._pending:
            raw, self._pending = self._pending.split("\n", 1)
            text = visible_text(raw)
            if text:
                lines.append(text)

        frame = None
        last_cr = self._pending.rfind("\r")
        if last_cr > 0:
            # Everything before the last \r is fully drawn; the part after it may
            # still be arriving. Keep only the line being drawn now.
            frame = visible_text(self._pending[:last_cr]) or None
            self._pending = self._pending[last_cr:]
        if len(self._pending) > MAX_PENDING_CHARS:
            text = visible_text(self._pending)
            self._pending = ""
            if text:
                lines.append(text)
        return lines, frame

    def flush(self) -> list[str]:
        """Return the final line if the process exited without a trailing newline."""
        text = visible_text(self._pending + self._decoder.decode(b"", final=True))
        self._pending = ""
        return [text] if text else []
