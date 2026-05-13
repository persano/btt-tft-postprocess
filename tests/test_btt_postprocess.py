import base64

import pytest

from btt_postprocess import (
    M73_RE,
    collapse_blank_lines,
    extract_png_from_gcode,
    format_time_left,
    inject_m155_throttle,
    inject_m73_notifications,
    rgb_to_rgb565_hex,
    strip_existing_btt_thumbnail,
    strip_inline_command_comments,
    strip_m115_queries,
    strip_png_thumbnail_blocks,
    strip_slicer_feature_comments,
    upgrade_final_warmup_m104_to_m109,
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

    def test_idempotent_when_notifications_already_present(self):
        # Second pass on already-processed gcode should not stack duplicates.
        gcode = (
            "M73 P25 R30\r\n"
            "M118 P0 A1 action:notification Time Left 00h30m00s\r\n"
            "M118 P0 A1 action:notification Data Left 25/100\r\n"
            "G1 X10\r\n"
        )
        result, count = inject_m73_notifications(gcode)
        assert count == 0
        assert result == gcode


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


class TestStripM115Queries:
    def test_strips_bare_m115(self):
        gcode = "M115\r\nG28\r\n"
        result, removed = strip_m115_queries(gcode)
        assert removed == 1
        assert "M115" not in result
        assert "G28\r\n" in result

    def test_strips_m115_with_args_and_comment(self):
        gcode = "G28\r\nM115 U2.0.9 ; firmware check\r\nG1 X10\r\n"
        result, removed = strip_m115_queries(gcode)
        assert removed == 1
        assert "M115" not in result

    def test_strips_lowercase_m115(self):
        gcode = "m115\r\n"
        _, removed = strip_m115_queries(gcode)
        assert removed == 1

    def test_does_not_strip_m1150(self):
        # Word boundary must reject longer command names that happen to start with M115.
        gcode = "M1150 S1\r\n"
        result, removed = strip_m115_queries(gcode)
        assert removed == 0
        assert result == gcode

    def test_does_not_strip_commented_m115(self):
        gcode = "; M115 here\r\nG28\r\n"
        result, removed = strip_m115_queries(gcode)
        assert removed == 0
        assert result == gcode

    def test_no_match_returns_unchanged(self):
        gcode = "G28\r\nG1 X10\r\n"
        result, removed = strip_m115_queries(gcode)
        assert removed == 0
        assert result == gcode


class TestUpgradeFinalWarmupM104ToM109:
    def test_lone_m104_in_header_is_upgraded(self):
        # Classic OrcaSlicer #4337 case: bed waits, nozzle doesn't.
        gcode = (
            "M140 S60\r\n"
            "M190 S60\r\n"
            "M104 S220\r\n"
            "G28\r\n"
            "G1 X10 Y10 E5 F600\r\n"
        )
        result, count = upgrade_final_warmup_m104_to_m109(gcode)
        assert count == 1
        assert "M109 S220\r\n" in result
        assert "M104 S220\r\n" not in result
        # Other lines untouched
        assert "M140 S60\r\n" in result
        assert "M190 S60\r\n" in result

    def test_m104_followed_by_m109_left_alone(self):
        # User already has an M109 wait -- nothing to fix.
        gcode = (
            "M104 S150 ; early warmup\r\n"
            "M190 S60\r\n"
            "M109 S220\r\n"
            "G1 X10 E5\r\n"
        )
        result, count = upgrade_final_warmup_m104_to_m109(gcode)
        assert count == 0
        assert result == gcode

    def test_m104_after_m109_is_upgraded(self):
        # An M104 emitted *after* an M109 (duplicate-temp pattern from #7571)
        # is what actually controls the nozzle, so upgrade that one.
        gcode = (
            "M109 S220\r\n"
            "M104 S220\r\n"
            "G1 X10 E5\r\n"
        )
        result, count = upgrade_final_warmup_m104_to_m109(gcode)
        assert count == 1
        lines = result.splitlines()
        assert lines[0] == "M109 S220"
        assert lines[1] == "M109 S220"

    def test_m104_s0_cooldown_ignored(self):
        # Cooling the nozzle is intentionally non-blocking.
        gcode = "M104 S0\r\nG1 X10 E5\r\n"
        result, count = upgrade_final_warmup_m104_to_m109(gcode)
        assert count == 0
        assert result == gcode

    def test_m109_with_r_counts_as_wait(self):
        gcode = "M104 S220\r\nM109 R210\r\nG1 X10 E5\r\n"
        _, count = upgrade_final_warmup_m104_to_m109(gcode)
        assert count == 0

    def test_no_extrusion_move_still_processes(self):
        # File with no extrusion at all (e.g. test gcode) -- still upgrade.
        gcode = "M104 S220\r\nG28\r\n"
        result, count = upgrade_final_warmup_m104_to_m109(gcode)
        assert count == 1
        assert "M109 S220\r\n" in result

    def test_m104_after_extrusion_is_ignored(self):
        # The print body legitimately uses M104 for per-layer temp tweaks --
        # don't make those blocking.
        gcode = (
            "M109 S220\r\n"
            "G1 X10 E5\r\n"
            "M104 S210\r\n"
            "G1 X20 E10\r\n"
        )
        result, count = upgrade_final_warmup_m104_to_m109(gcode)
        assert count == 0
        assert result == gcode

    def test_m104_dot_1_variant_ignored(self):
        # M104.1 is a filament-change variant -- different semantics.
        gcode = "M104.1 S220\r\nG1 X10 E5\r\n"
        result, count = upgrade_final_warmup_m104_to_m109(gcode)
        assert count == 0
        assert result == gcode

    def test_lowercase_m104(self):
        gcode = "m104 s220\r\nG1 X10 E5\r\n"
        result, count = upgrade_final_warmup_m104_to_m109(gcode)
        assert count == 1
        # Replacement keeps the rest of the line; only the command token changes.
        assert "M109 s220\r\n" in result

    def test_preserves_trailing_comment(self):
        gcode = "M104 S220 ; set nozzle\r\nG1 X10 E5\r\n"
        result, count = upgrade_final_warmup_m104_to_m109(gcode)
        assert count == 1
        assert "M109 S220 ; set nozzle\r\n" in result


class TestInjectM155Throttle:
    def test_injects_before_first_executable(self):
        gcode = "; metadata\r\n; more meta\r\nG28\r\nM104 S220\r\n"
        result, count = inject_m155_throttle(gcode, interval_seconds=30)
        assert count == 1
        lines = result.splitlines(keepends=True)
        assert lines[0] == "; metadata\r\n"
        assert lines[1] == "; more meta\r\n"
        assert lines[2] == "M155 S30\r\n"
        assert lines[3] == "G28\r\n"

    def test_skips_if_user_already_has_m155(self):
        gcode = "M155 S5\r\nG28\r\nG1 X10 E5\r\n"
        result, count = inject_m155_throttle(gcode)
        assert count == 0
        assert result == gcode

    def test_no_exec_lines_returns_unchanged(self):
        gcode = "; just comments\r\n; nothing else\r\n"
        result, count = inject_m155_throttle(gcode)
        assert count == 0
        assert result == gcode

    def test_lf_line_endings(self):
        gcode = "G28\nG1 X10 E5\n"
        result, count = inject_m155_throttle(gcode, interval_seconds=60)
        assert count == 1
        assert result.startswith("M155 S60\n")
        assert "\r\n" not in result

    def test_skip_if_m155_in_warmup_only(self):
        # M155 in the print body (after first extrusion) shouldn't block
        # injection -- that's a different concern.
        gcode = "G28\r\nG1 X10 E5\r\nM155 S5\r\n"
        result, count = inject_m155_throttle(gcode)
        assert count == 1
        # injected before G28
        assert result.splitlines()[0] == "M155 S30"


class TestStripPngThumbnailBlocks:
    def test_strips_single_block(self):
        gcode = (
            "G28\r\n"
            "; thumbnail begin 70x70 1036\r\n"
            "; AAAAAAAAAAAAAAA\r\n"
            "; BBBBBBBBBBBBBBB\r\n"
            "; thumbnail end\r\n"
            "G1 X10\r\n"
        )
        result, blocks = strip_png_thumbnail_blocks(gcode)
        assert blocks == 1
        assert "thumbnail begin" not in result
        assert "thumbnail end" not in result
        assert "AAAA" not in result
        assert "G28\r\n" in result
        assert "G1 X10\r\n" in result

    def test_strips_multiple_variants(self):
        gcode = (
            "; thumbnail begin 70x70 100\r\n; data\r\n; thumbnail end\r\n"
            "; thumbnail_QOI begin 200x200 5000\r\n; data\r\n; thumbnail_QOI end\r\n"
            "; thumbnail_JPG begin 400x400 9999\r\n; data\r\n; thumbnail_JPG end\r\n"
            "G28\r\n"
        )
        result, blocks = strip_png_thumbnail_blocks(gcode)
        assert blocks == 3
        assert "thumbnail" not in result
        assert "G28\r\n" in result

    def test_no_thumbnail_returns_unchanged(self):
        gcode = "G28\r\nG1 X10\r\n"
        result, blocks = strip_png_thumbnail_blocks(gcode)
        assert blocks == 0
        assert result == gcode

    def test_does_not_strip_bigtree_marker(self):
        # Our own "; bigtree thumbnail end" sentinel must survive.
        gcode = "; bigtree thumbnail end\r\nG28\r\n"
        result, blocks = strip_png_thumbnail_blocks(gcode)
        assert blocks == 0
        assert "bigtree" in result


class TestStripSlicerFeatureComments:
    def test_strips_type_marker(self):
        gcode = ";TYPE:Outer wall\r\nG1 X10\r\n"
        result, count = strip_slicer_feature_comments(gcode)
        assert count == 1
        assert "TYPE:" not in result
        assert "G1 X10\r\n" in result

    def test_strips_width_height_z(self):
        gcode = ";WIDTH:0.42\r\n;HEIGHT:0.2\r\n;Z:0.2\r\nG1 X10\r\n"
        result, count = strip_slicer_feature_comments(gcode)
        assert count == 3
        assert "G1 X10\r\n" in result

    def test_preserves_layer_change(self):
        gcode = ";LAYER_CHANGE\r\n;BEFORE_LAYER_CHANGE\r\n;AFTER_LAYER_CHANGE\r\nG1 X10\r\n"
        result, count = strip_slicer_feature_comments(gcode)
        assert count == 0
        assert "LAYER_CHANGE\r\n" in result
        assert "BEFORE_LAYER_CHANGE\r\n" in result
        assert "AFTER_LAYER_CHANGE\r\n" in result

    def test_strips_change_layer_distinct_from_layer_change(self):
        gcode = ";CHANGE_LAYER\r\n;LAYER_CHANGE\r\n"
        result, count = strip_slicer_feature_comments(gcode)
        assert count == 1
        assert ";LAYER_CHANGE\r\n" in result
        assert ";CHANGE_LAYER" not in result

    def test_strips_orca_block_markers(self):
        gcode = (
            "; HEADER_BLOCK_START\r\n; HEADER_BLOCK_END\r\n"
            "; THUMBNAIL_BLOCK_START\r\n; THUMBNAIL_BLOCK_END\r\n"
            "; EXECUTABLE_BLOCK_START\r\n; EXECUTABLE_BLOCK_END\r\n"
            "G28\r\n"
        )
        result, count = strip_slicer_feature_comments(gcode)
        assert count == 6
        assert "G28\r\n" in result

    def test_strips_wipe_markers(self):
        gcode = ";WIPE_START\r\n;WIPE_END\r\nG1 X10\r\n"
        result, count = strip_slicer_feature_comments(gcode)
        assert count == 2

    def test_does_not_touch_g_m_lines(self):
        gcode = "G1 X10\r\nM104 S220\r\nG28\r\n"
        result, count = strip_slicer_feature_comments(gcode)
        assert count == 0
        assert result == gcode


class TestStripInlineCommandComments:
    def test_strips_trailing_comment(self):
        gcode = "G1 X10 Y10 ; move to start\r\n"
        result, count = strip_inline_command_comments(gcode)
        assert count == 1
        assert result == "G1 X10 Y10\r\n"

    def test_preserves_standalone_comment(self):
        gcode = "; just a comment\r\nG28\r\n"
        result, count = strip_inline_command_comments(gcode)
        assert count == 0
        assert result == gcode

    def test_preserves_m117(self):
        # M117 display message may legitimately contain ';'
        gcode = "M117 Hello;World\r\n"
        result, count = strip_inline_command_comments(gcode)
        assert count == 0
        assert result == gcode

    def test_preserves_m118(self):
        gcode = "M118 P0 A1 action:notification something;else\r\n"
        result, count = strip_inline_command_comments(gcode)
        assert count == 0
        assert result == gcode

    def test_no_comment_unchanged(self):
        gcode = "G1 X10 Y10\r\n"
        result, count = strip_inline_command_comments(gcode)
        assert count == 0
        assert result == gcode

    def test_strips_comment_without_space_before_semicolon(self):
        gcode = "G92 E0; reset extruder\r\n"
        result, count = strip_inline_command_comments(gcode)
        assert count == 1
        assert result == "G92 E0\r\n"

    def test_handles_lf_endings(self):
        gcode = "G1 X10 ; foo\n"
        result, count = strip_inline_command_comments(gcode)
        assert count == 1
        assert result == "G1 X10\n"

    def test_handles_m104_dot_variant(self):
        gcode = "M104.1 S220 ; filament change\r\n"
        result, count = strip_inline_command_comments(gcode)
        assert count == 1
        assert result == "M104.1 S220\r\n"


class TestStripExistingBttThumbnail:
    def test_strips_full_btt_block(self):
        gcode = (
            ";00460046\r\n"
            ";0000000000000000\r\n"
            ";ffffffffffffffff\r\n"
            "; bigtree thumbnail end\r\n"
            "\r\n"
            "G28\r\n"
        )
        result, dropped = strip_existing_btt_thumbnail(gcode)
        assert dropped == 1
        assert result == "G28\r\n"

    def test_strips_without_trailing_blank(self):
        gcode = (
            ";00460046\r\n"
            ";0000\r\n"
            "; bigtree thumbnail end\r\n"
            "G28\r\n"
        )
        result, dropped = strip_existing_btt_thumbnail(gcode)
        assert dropped == 1
        assert result == "G28\r\n"

    def test_no_btt_block_unchanged(self):
        gcode = "; FLAVOR: Marlin\r\nG28\r\n"
        result, dropped = strip_existing_btt_thumbnail(gcode)
        assert dropped == 0
        assert result == gcode

    def test_orca_thumbnail_does_not_trigger(self):
        # Orca's PNG block starts with "; thumbnail begin ...", NOT a hex
        # header. Our regex should not match it.
        gcode = "; thumbnail begin 70x70 1036\r\n; abc\r\n; thumbnail end\r\n"
        result, dropped = strip_existing_btt_thumbnail(gcode)
        assert dropped == 0
        assert result == gcode

    def test_missing_end_marker_is_safe(self):
        # Hex header but no terminator -- refuse to nuke unrelated content.
        gcode = ";00460046\r\n;0000\r\nG28\r\n"
        result, dropped = strip_existing_btt_thumbnail(gcode)
        assert dropped == 0
        assert result == gcode


class TestCollapseBlankLines:
    def test_drops_blank_lines(self):
        gcode = "G28\r\n\r\nG1 X10\r\n\r\n\r\nG1 X20\r\n"
        result, dropped = collapse_blank_lines(gcode)
        assert dropped == 3
        assert result == "G28\r\nG1 X10\r\nG1 X20\r\n"

    def test_drops_whitespace_only_lines(self):
        gcode = "G28\r\n   \r\nG1 X10\r\n"
        result, dropped = collapse_blank_lines(gcode)
        assert dropped == 1
        assert result == "G28\r\nG1 X10\r\n"

    def test_no_blanks_unchanged(self):
        gcode = "G28\r\nG1 X10\r\n"
        result, dropped = collapse_blank_lines(gcode)
        assert dropped == 0
        assert result == gcode
