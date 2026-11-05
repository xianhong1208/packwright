"""
Unit tests for turning PTY output into build-log lines, and for Nuitka progress parsing.
Source: app/services/terminal_output, app/services/nuitka_worker.parse_nuitka_progress
"""

import pytest

from app.services.nuitka_worker import parse_nuitka_progress
from app.services.terminal_output import MAX_PENDING_CHARS, TerminalLineBuffer, visible_text

# The shape of real Nuitka 4 output on a PTY: one "line" carries hundreds of
# \r-redrawn progress frames, a blanking frame, then the real message.
NUITKA_PASS_LINE = (
    "\r  0% 0/296 [00:00<?, ? modules/s]"
    "\rPASS 1:  34% 102/296 [00:18<00:39,  4.91 modules/s - dataclasses]"
    "\rPASS 1: 100% 296/296 [00:40<00:00,  7.20 modules/s - copy]"
    "\r                                                             "
    "\r\x1b[0mNuitka: Completed Python level compilation and optimization.\n"
)


class TestVisibleText:
    @pytest.mark.unit
    def test_tc_tout_001_keeps_only_the_last_frame(self):
        """TC-TOUT-001: a \\r-redrawn line collapses to what a terminal would show."""
        assert visible_text(NUITKA_PASS_LINE.rstrip("\n")) == (
            "Nuitka: Completed Python level compilation and optimization."
        )

    @pytest.mark.unit
    def test_tc_tout_002_trailing_blanking_frame_does_not_erase_the_line(self):
        """TC-TOUT-002: a final all-space frame is skipped, not returned as empty."""
        assert visible_text("\rPASS 2: 100% 404/404\r              ") == "PASS 2: 100% 404/404"

    @pytest.mark.unit
    def test_tc_tout_003_ansi_escapes_are_removed(self):
        """TC-TOUT-003: colour codes never reach the log."""
        assert visible_text("\x1b[0m\x1b[93mNuitka-Scons:WARNING: no ccache\x1b[0m") == (
            "Nuitka-Scons:WARNING: no ccache"
        )


class TestTerminalLineBuffer:
    @pytest.mark.unit
    def test_tc_tout_010_progress_frames_are_not_logged(self):
        """TC-TOUT-010: hundreds of redraws produce exactly one log line."""
        lines, frame = TerminalLineBuffer().feed(NUITKA_PASS_LINE.encode())
        assert lines == ["Nuitka: Completed Python level compilation and optimization."]
        assert frame is None

    @pytest.mark.unit
    def test_tc_tout_011_in_place_frame_is_reported_for_progress(self):
        """TC-TOUT-011: while a bar is still being drawn, its latest complete frame is
        returned separately, and the partial frame after the last \\r is held back."""
        buf = TerminalLineBuffer()
        lines, frame = buf.feed(b"\rPASS 1:  10% 30/296\rPASS 1:  34% 102/296\rPASS 1:  3")
        assert lines == []
        assert frame == "PASS 1:  34% 102/296"
        lines, frame = buf.feed(b"5% 104/296\rNuitka: done\n")
        assert lines == ["Nuitka: done"]

    @pytest.mark.unit
    def test_tc_tout_012_pending_line_does_not_accumulate_frames(self):
        """TC-TOUT-012: a bar redrawn for minutes keeps only the current frame in memory."""
        buf = TerminalLineBuffer()
        for i in range(5000):
            buf.feed(f"\rPASS 1: {i % 100:3d}% {i}/5000".encode())
        assert len(buf._pending) < 40

    @pytest.mark.unit
    def test_tc_tout_013_multibyte_character_split_across_reads(self):
        """TC-TOUT-013: a UTF-8 character cut in half by a PTY read is not mangled."""
        data = "┃ 建置完成 ┃\n".encode()
        buf = TerminalLineBuffer()
        lines = []
        for i in range(len(data)):  # worst case: one byte per read
            lines += buf.feed(data[i:i + 1])[0]
        assert lines == ["┃ 建置完成 ┃"]

    @pytest.mark.unit
    def test_tc_tout_014_flush_returns_unterminated_last_line(self):
        """TC-TOUT-014: output that ends without a newline is not lost when the process exits."""
        buf = TerminalLineBuffer()
        assert buf.feed(b"first\nlast words")[0] == ["first"]
        assert buf.flush() == ["last words"]
        assert buf.flush() == []

    @pytest.mark.unit
    def test_tc_tout_015_endless_line_is_cut_instead_of_growing(self):
        """TC-TOUT-015: a line with no \\n and no \\r is emitted once it passes the cap."""
        buf = TerminalLineBuffer()
        lines, _ = buf.feed(b"x" * (MAX_PENDING_CHARS + 1))
        assert len(lines) == 1 and buf._pending == ""

    @pytest.mark.unit
    def test_tc_tout_016_blank_lines_are_dropped(self):
        """TC-TOUT-016: empty and whitespace-only lines are not logged."""
        assert TerminalLineBuffer().feed(b"a\n\n   \r\nb\n")[0] == ["a", "b"]


class TestParseNuitkaProgress:
    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("text", "expected", "status"),
        [
            ("PASS 1:  50% 148/296 [00:20<00:20]", 15, "Analyzing Python... 50%"),
            ("PASS 2: 100% 404/404", 40, "Optimizing... 100%"),
            ("Backend C:  40% 4/10 [00:05<00:07]", 68, "Compiling C code... 40%"),
            ("Nuitka: Running C compilation via Scons.", 50, "Compiling C code..."),
        ],
    )
    def test_tc_nui_100_progress_bars_and_phases_map_to_task_progress(self, text, expected, status):
        """TC-NUI-100: Nuitka's progress bars drive the task's 0-100 progress."""
        progress, message = parse_nuitka_progress(text, 0.0)
        assert progress == pytest.approx(expected)
        assert message == status

    @pytest.mark.unit
    def test_tc_nui_101_progress_never_moves_backwards(self):
        """TC-NUI-101: an earlier phase's bar seen late does not rewind the progress."""
        progress, _ = parse_nuitka_progress("PASS 1:  10% 30/296", 60.0)
        assert progress == 60.0

    @pytest.mark.unit
    def test_tc_nui_102_unrelated_text_keeps_status(self):
        """TC-NUI-102: lines that say nothing about the phase leave progress and status alone."""
        assert parse_nuitka_progress("Copied 9 packages", 42.0, "Linking...") == (42.0, "Linking...")

    @pytest.mark.unit
    def test_tc_nui_103_success_line_completes(self):
        """TC-NUI-103: Nuitka's success line is the only thing that reaches 100."""
        assert parse_nuitka_progress("Nuitka: Successfully created 'dist/main'.", 95.0)[0] == 100.0
