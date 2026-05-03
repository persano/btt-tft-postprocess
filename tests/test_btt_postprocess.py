import base64

import pytest

from btt_postprocess import (
    M73_RE,
    extract_png_from_gcode,
    format_time_left,
    inject_m73_notifications,
    rgb_to_rgb565_hex,
)


class TestRgbToRgb565Hex:
    def test_white(self):
        assert rgb_to_rgb565_hex(255, 255, 255) == "ffff"

    def test_black(self):
        assert rgb_to_rgb565_hex(0, 0, 0) == "0000"

    def test_red(self):
        assert rgb_to_rgb565_hex(255, 0, 0) == "f800"

    def test_green(self):
        assert rgb_to_rgb565_hex(0, 255, 0) == "07e0"

    def test_blue(self):
        assert rgb_to_rgb565_hex(0, 0, 255) == "001f"

    def test_near_black_0020_clamped(self):
        # (0, 4, 0) maps to raw "0020", which is in NEAR_BLACK_RGB565 -> "0000"
        assert rgb_to_rgb565_hex(0, 4, 0) == "0000"

    def test_near_black_0841_clamped(self):
        # (8, 8, 8) maps to raw "0841", which is in NEAR_BLACK_RGB565 -> "0000"
        assert rgb_to_rgb565_hex(8, 8, 8) == "0000"

    def test_near_black_0861_clamped(self):
        # (8, 12, 8) maps to raw "0861", which is in NEAR_BLACK_RGB565 -> "0000"
        assert rgb_to_rgb565_hex(8, 12, 8) == "0000"


class TestFormatTimeLeft:
    def test_zero(self):
        assert format_time_left(0) == "00h00m00s"

    def test_exactly_one_hour(self):
        assert format_time_left(60) == "01h00m00s"

    def test_two_hours_five_minutes(self):
        assert format_time_left(125) == "02h05m00s"


class TestM73Re:
    def test_matches_p_and_r(self):
        assert M73_RE.match("M73 P50 R45") is not None

    def test_matches_p_only(self):
        assert M73_RE.match("M73 P50") is not None

    def test_matches_lowercase_with_comment(self):
        assert M73_RE.match("m73 p50 r45 ; comment") is not None

    def test_no_match_comment_line(self):
        # regex anchors to ^, ";" doesn't match \s*M73
        assert M73_RE.match("; M73 P50") is None

    def test_no_match_missing_p(self):
        assert M73_RE.match("M73 R45") is None

    def test_no_match_wrong_command(self):
        assert M73_RE.match("G73 P50") is None


class TestInjectM73Notifications:
    def test_basic_injection(self):
        gcode = "G28 ; home\r\nM73 P25 R30\r\nG1 X10\r\n"
        result, count = inject_m73_notifications(gcode)
        lines = result.splitlines(keepends=True)
        assert lines[0] == "G28 ; home\r\n"
        assert lines[1] == "M73 P25 R30\r\n"
        assert lines[2] == "M118 P0 A1 action:notification Time Left 00h30m00s\r\n"
        assert lines[3] == "M118 P0 A1 action:notification Data Left 25/100\r\n"
        assert lines[4] == "G1 X10\r\n"
        assert count == 1

    def test_skips_commented_m73(self):
        gcode = "; M73 P50 R10\r\nG1 X5\r\n"
        result, count = inject_m73_notifications(gcode)
        assert count == 0
        assert result == gcode

    def test_no_r_omits_time_left(self):
        gcode = "M73 P50\r\n"
        result, count = inject_m73_notifications(gcode)
        lines = result.splitlines(keepends=True)
        assert count == 1
        assert not any("Time Left" in ln for ln in lines)
        assert any("Data Left 50/100" in ln for ln in lines)

    def test_multiple_m73_lines(self):
        gcode = "M73 P0 R60\r\nM73 P50 R30\r\nM73 P100 R0\r\n"
        _, count = inject_m73_notifications(gcode)
        assert count == 3


class TestExtractPngFromGcode:
    def test_round_trip(self):
        payload = b"\x89PNG\r\n\x1a\nfake_png_data_xyz_0123456789"
        b64 = base64.b64encode(payload).decode()
        gcode = f"; thumbnail begin 10x10\n; {b64}\n; thumbnail end\n"
        assert extract_png_from_gcode(gcode) == payload

    def test_no_thumbnail_returns_none(self):
        gcode = "G28\nG1 X10\n"
        assert extract_png_from_gcode(gcode) is None

    def test_multi_line_base64(self):
        payload = bytes(range(64))
        full_b64 = base64.b64encode(payload).decode()
        half = len(full_b64) // 2
        chunk1, chunk2 = full_b64[:half], full_b64[half:]
        gcode = f"; thumbnail begin\n; {chunk1}\n; {chunk2}\n; thumbnail end\n"
        assert extract_png_from_gcode(gcode) == payload
