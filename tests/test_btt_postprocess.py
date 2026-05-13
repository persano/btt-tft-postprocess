import base64

import pytest

from btt_postprocess import (
    M73_RE,
    collapse_blank_lines,
    extract_png_from_gcode,
    format_time_left,
    inject_m155_throttle,
    inject_m73_notifications,
    minify_float_coordinates,
    move_final_notifications_before_print_end,
    move_initial_notifications_after_print_start,
    rgb_to_rgb565_hex,
    strip_comment_leading_whitespace,
    strip_existing_btt_thumbnail,
    strip_inline_command_comments,
    strip_m115_queries,
    strip_png_thumbnail_blocks,
    strip_slicer_config_block,
    strip_slicer_feature_comments,
    strip_trailing_whitespace,
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


class TestStripSlicerConfigBlock:
    def test_strips_block(self):
        gcode = (
            "G1 X10\r\n"
            "; CONFIG_BLOCK_START\r\n"
            "; layer_height = 0.2\r\n"
            "; nozzle_diameter = 0.4\r\n"
            "; CONFIG_BLOCK_END\r\n"
        )
        result, dropped = strip_slicer_config_block(gcode)
        assert dropped == 4
        assert result == "G1 X10\r\n"

    def test_strips_block_with_trailing_content(self):
        gcode = (
            "G1 X10\r\n"
            "; CONFIG_BLOCK_START\r\n"
            "; a = 1\r\n"
            "; CONFIG_BLOCK_END\r\n"
            "; some final comment\r\n"
        )
        result, dropped = strip_slicer_config_block(gcode)
        assert dropped == 3
        assert result == "G1 X10\r\n; some final comment\r\n"

    def test_missing_end_marker_keeps_text(self):
        gcode = "G1 X10\r\n; CONFIG_BLOCK_START\r\n; a = 1\r\n"
        result, dropped = strip_slicer_config_block(gcode)
        assert dropped == 0
        assert result == gcode

    def test_missing_start_marker_keeps_text(self):
        gcode = "G1 X10\r\n; a = 1\r\n; CONFIG_BLOCK_END\r\n"
        result, dropped = strip_slicer_config_block(gcode)
        assert dropped == 0
        assert result == gcode

    def test_no_markers_unchanged(self):
        gcode = "G28\r\nG1 X10\r\n"
        result, dropped = strip_slicer_config_block(gcode)
        assert dropped == 0
        assert result == gcode


class TestStripMetadataComments:
    """Coverage for the metadata patterns added to _FEATURE_COMMENT_RE."""

    def test_strips_generated_by(self):
        gcode = "; generated by OrcaSlicer 2.4.0\r\nG28\r\n"
        result, count = strip_slicer_feature_comments(gcode)
        assert count == 1
        assert "generated by" not in result

    def test_strips_layer_number(self):
        gcode = "; total layer number: 86\r\nG28\r\n"
        result, count = strip_slicer_feature_comments(gcode)
        assert count == 1
        assert "total layer number" not in result

    def test_strips_filament_metadata(self):
        gcode = (
            "; filament_density: 1.24\r\n"
            "; filament_diameter: 1.75\r\n"
            "; filament: 1\r\n"
            "G28\r\n"
        )
        result, count = strip_slicer_feature_comments(gcode)
        assert count == 3
        assert "G28\r\n" in result

    def test_strips_max_z_height(self):
        gcode = "; max_z_height: 17.20\r\nG28\r\n"
        result, count = strip_slicer_feature_comments(gcode)
        assert count == 1

    def test_strips_extrusion_width(self):
        gcode = (
            "; external perimeters extrusion width = 0.42mm\r\n"
            "; first layer extrusion width = 0.50mm\r\n"
            "G28\r\n"
        )
        result, count = strip_slicer_feature_comments(gcode)
        assert count == 2

    def test_strips_printing_object(self):
        gcode = "; printing object Foo id:0 copy 0\r\nG28\r\n"
        result, count = strip_slicer_feature_comments(gcode)
        assert count == 1

    def test_strips_klipper_fan_marker(self):
        gcode = ";_SET_FAN_SPEED_CHANGING_LAYER\r\nG28\r\n"
        result, count = strip_slicer_feature_comments(gcode)
        assert count == 1

    def test_strips_bare_semicolon_separator(self):
        gcode = ";\r\nG28\r\n;   \r\nG1 X10\r\n"
        result, count = strip_slicer_feature_comments(gcode)
        assert count == 2
        assert result == "G28\r\nG1 X10\r\n"

    def test_preserves_layer_count_metadata(self):
        # LAYER_COUNT is firmware-readable -- do not strip even though it
        # looks similar to total-layer-number.
        gcode = ";LAYER_COUNT:86\r\nG28\r\n"
        result, count = strip_slicer_feature_comments(gcode)
        assert count == 0
        assert "LAYER_COUNT" in result


class TestMinifyFloatCoordinates:
    def test_strips_trailing_zeros(self):
        gcode = "G1 X100.000 Y50.500 F1500.0\r\n"
        result, count = minify_float_coordinates(gcode)
        assert count == 1
        assert result == "G1 X100 Y50.5 F1500\r\n"

    def test_preserves_meaningful_decimals(self):
        gcode = "G1 X100.123 Y50.456 E0.789\r\n"
        result, count = minify_float_coordinates(gcode)
        assert count == 0
        assert result == gcode

    def test_handles_negative_numbers(self):
        gcode = "G1 X-10.500 Y-20.0\r\n"
        result, count = minify_float_coordinates(gcode)
        assert count == 1
        assert result == "G1 X-10.5 Y-20\r\n"

    def test_handles_z_height_pattern(self):
        gcode = "G1 Z0.20\r\n"
        result, count = minify_float_coordinates(gcode)
        assert count == 1
        assert result == "G1 Z0.2\r\n"

    def test_skips_comment_lines(self):
        gcode = "; some comment with 1.000 in it\r\n"
        result, count = minify_float_coordinates(gcode)
        assert count == 0
        assert result == gcode

    def test_skips_m117_message(self):
        gcode = "M117 Time 1.000 left\r\n"
        result, count = minify_float_coordinates(gcode)
        assert count == 0
        assert result == gcode

    def test_skips_m118_message(self):
        gcode = "M118 P0 A1 action:notification 1.000\r\n"
        result, count = minify_float_coordinates(gcode)
        assert count == 0
        assert result == gcode

    def test_no_floats_unchanged(self):
        gcode = "G28\r\nM104 S220\r\n"
        result, count = minify_float_coordinates(gcode)
        assert count == 0
        assert result == gcode

    def test_temperature_with_decimal(self):
        gcode = "M104 S220.0\r\n"
        result, count = minify_float_coordinates(gcode)
        assert count == 1
        assert result == "M104 S220\r\n"


class TestMoveInitialNotificationsAfterPrintStart:
    def test_inserts_after_print_start_and_drops_stale_before(self):
        # M73 + injected M118s come BEFORE print_start, where the TFT
        # can't see them. They should move to AFTER print_start.
        gcode = (
            "M155 S30\r\n"
            "M73 P0 R12\r\n"
            "M118 P0 A1 action:notification Time Left 00h12m00s\r\n"
            "M118 P0 A1 action:notification Data Left 0/100\r\n"
            "M201 X2000 Y2000 Z500 E5000\r\n"
            "M118 P0 A1 action:print_start\r\n"
            "M83\r\n"
        )
        result, moved = move_initial_notifications_after_print_start(gcode)
        assert moved == 1
        lines = result.splitlines(keepends=True)
        # Pre-print_start notifications dropped; M73 + non-notification lines kept.
        assert "M155 S30\r\n" in result
        assert "M73 P0 R12\r\n" in result
        assert "M201 X2000 Y2000 Z500 E5000\r\n" in result
        # Notification pair now sits immediately AFTER print_start.
        ps_idx = next(i for i, ln in enumerate(lines)
                      if "action:print_start" in ln)
        assert lines[ps_idx + 1] == (
            "M118 P0 A1 action:notification Time Left 00h12m00s\r\n"
        )
        assert lines[ps_idx + 2] == (
            "M118 P0 A1 action:notification Data Left 0/100\r\n"
        )
        # Only one set of notifications survives.
        assert result.count("action:notification") == 2

    def test_no_print_start_unchanged(self):
        gcode = "G28\r\nM73 P0 R12\r\nG1 X10 E5\r\n"
        result, moved = move_initial_notifications_after_print_start(gcode)
        assert moved == 0
        assert result == gcode

    def test_no_m73_falls_back_to_zero_percent(self):
        gcode = "M118 P0 A1 action:print_start\r\nG28\r\n"
        result, moved = move_initial_notifications_after_print_start(gcode)
        assert moved == 1
        # No Time Left line (no R minutes available), but Data Left fires.
        assert "Time Left" not in result
        assert "M118 P0 A1 action:notification Data Left 0/100\r\n" in result

    def test_lf_endings(self):
        gcode = "M73 P0 R12\nM118 P0 A1 action:print_start\n"
        result, moved = move_initial_notifications_after_print_start(gcode)
        assert moved == 1
        lines = result.splitlines(keepends=True)
        # All notifications use \n endings, not \r\n
        for line in lines:
            if "action:notification" in line:
                assert line.endswith("\n") and not line.endswith("\r\n")

    def test_idempotent_on_already_processed_file(self):
        # Re-running shouldn't stack duplicate notification pairs after
        # print_start.
        gcode = (
            "M73 P0 R12\r\n"
            "M118 P0 A1 action:print_start\r\n"
            "M118 P0 A1 action:notification Time Left 00h12m00s\r\n"
            "M118 P0 A1 action:notification Data Left 0/100\r\n"
            "M83\r\n"
        )
        once, _ = move_initial_notifications_after_print_start(gcode)
        twice, _ = move_initial_notifications_after_print_start(once)
        assert twice.count("action:notification") == 2
        assert twice == once


class TestMoveFinalNotificationsBeforePrintEnd:
    def test_inserts_before_print_end_and_drops_stale_after(self):
        # Classic case: print_end fires, then M73 P100 + 100% notifications
        # come after, so the TFT never sees the completion state.
        gcode = (
            "M84 X Y E\r\n"
            "M118 P0 A1 action:print_end\r\n"
            "M73 P100 R0\r\n"
            "M118 P0 A1 action:notification Time Left 00h00m00s\r\n"
            "M118 P0 A1 action:notification Data Left 100/100\r\n"
            "; filament used 304 mm\r\n"
        )
        result, moved = move_final_notifications_before_print_end(gcode)
        assert moved == 1
        lines = result.splitlines(keepends=True)
        # New ordering:
        assert lines[0] == "M84 X Y E\r\n"
        assert lines[1] == "M118 P0 A1 action:notification Time Left 00h00m00s\r\n"
        assert lines[2] == "M118 P0 A1 action:notification Data Left 100/100\r\n"
        assert lines[3] == "M118 P0 A1 action:print_end\r\n"
        # M73 stays (Marlin uses it natively); stale notifications dropped.
        assert "M73 P100 R0\r\n" in result
        assert result.count("action:notification") == 2
        assert "; filament used 304 mm\r\n" in result

    def test_no_print_end_unchanged(self):
        gcode = "G28\r\nG1 X10 E5\r\nM84\r\n"
        result, moved = move_final_notifications_before_print_end(gcode)
        assert moved == 0
        assert result == gcode

    def test_lf_endings(self):
        gcode = "M118 P0 A1 action:print_end\n"
        result, moved = move_final_notifications_before_print_end(gcode)
        assert moved == 1
        lines = result.splitlines(keepends=True)
        assert lines[0].endswith("\n") and not lines[0].endswith("\r\n")
        assert lines[0] == "M118 P0 A1 action:notification Time Left 00h00m00s\n"
        assert lines[2] == "M118 P0 A1 action:print_end\n"

    def test_idempotent_on_already_processed_file(self):
        # Re-running shouldn't stack duplicate notification pairs before
        # print_end.
        gcode = (
            "M84 X Y E\r\n"
            "M118 P0 A1 action:notification Time Left 00h00m00s\r\n"
            "M118 P0 A1 action:notification Data Left 100/100\r\n"
            "M118 P0 A1 action:print_end\r\n"
            "M73 P100 R0\r\n"
        )
        once, _ = move_final_notifications_before_print_end(gcode)
        twice, _ = move_final_notifications_before_print_end(once)
        assert twice.count("action:notification") == 2
        assert twice == once

    def test_first_print_end_wins_if_multiple(self):
        # In the wild there's only one, but if a file has two we should
        # use the earliest as the anchor and treat the later one as
        # post-end content that survives.
        gcode = (
            "M118 P0 A1 action:print_end\r\n"
            "M73 P100\r\n"
            "M118 P0 A1 action:notification Data Left 100/100\r\n"
            "M118 P0 A1 action:print_end\r\n"
        )
        result, moved = move_final_notifications_before_print_end(gcode)
        assert moved == 1
        # First two output lines are the injected notifs
        lines = result.splitlines(keepends=True)
        assert lines[0].startswith("M118 P0 A1 action:notification Time Left")
        assert lines[1].startswith("M118 P0 A1 action:notification Data Left 100/100")
        assert lines[2] == "M118 P0 A1 action:print_end\r\n"
        # Stale notification dropped, second print_end kept
        assert result.count("action:print_end") == 2
        assert result.count("action:notification") == 2  # only the two we inserted


class TestNewlineRoundTrip:
    """Round-trip a file through process_gcode and confirm line endings
    stay clean. Prior versions produced CRCRLF on disk because of Windows
    text-mode newline translation re-applying CRLF to our already-CRLF
    string literals."""

    def test_does_not_emit_crcrlf(self, tmp_path):
        # Minimal gcode with our usual transforms applicable.
        gcode_text = (
            "M118 P0 A1 action:print_start\r\n"
            "M73 P0 R12\r\n"
            "G28\r\n"
            "G1 X10 Y10 E5\r\n"
            "M118 P0 A1 action:print_end\r\n"
        )
        gcode = tmp_path / "test.gcode"
        gcode.write_bytes(gcode_text.encode("utf-8"))

        from btt_postprocess import process_gcode
        process_gcode(gcode)

        raw = gcode.read_bytes()
        assert b"\r\r\n" not in raw, (
            "Double CR found on disk -- newline translation bug regressed"
        )

    def test_heals_existing_crcrlf(self, tmp_path):
        # Simulate a file produced by the buggy previous version.
        damaged = (
            "M118 P0 A1 action:print_start\r\r\n"
            "M73 P0 R12\r\r\n"
            "G28\r\r\n"
            "M118 P0 A1 action:print_end\r\r\n"
        )
        gcode = tmp_path / "damaged.gcode"
        gcode.write_bytes(damaged.encode("utf-8"))

        from btt_postprocess import process_gcode
        process_gcode(gcode)

        raw = gcode.read_bytes()
        assert b"\r\r\n" not in raw


class TestStripCommentLeadingWhitespace:
    def test_strips_single_space(self):
        gcode = "; UBL - load and activate saved mesh\r\nG28\r\n"
        result, count = strip_comment_leading_whitespace(gcode)
        assert count == 1
        assert result == ";UBL - load and activate saved mesh\r\nG28\r\n"

    def test_strips_multiple_spaces(self):
        gcode = ";   indented comment\r\n"
        result, count = strip_comment_leading_whitespace(gcode)
        assert count == 1
        assert result == ";indented comment\r\n"

    def test_strips_tab(self):
        gcode = ";\tindented with tab\r\n"
        result, count = strip_comment_leading_whitespace(gcode)
        assert count == 1
        assert result == ";indented with tab\r\n"

    def test_strips_bigtree_thumbnail_end_marker(self):
        # The (legacy) form had a leading space; verify we collapse it
        # so older files normalize on re-processing.
        gcode = "; bigtree thumbnail end\r\nG28\r\n"
        result, count = strip_comment_leading_whitespace(gcode)
        assert count == 1
        assert ";bigtree thumbnail end\r\n" in result

    def test_no_space_unchanged(self):
        gcode = ";LAYER_CHANGE\r\n;LAYER:5\r\n"
        result, count = strip_comment_leading_whitespace(gcode)
        assert count == 0
        assert result == gcode

    def test_does_not_touch_g_m_lines(self):
        gcode = "G1 X10\r\nM104 S220\r\n"
        result, count = strip_comment_leading_whitespace(gcode)
        assert count == 0
        assert result == gcode

    def test_handles_lf_endings(self):
        gcode = "; foo\n"
        result, count = strip_comment_leading_whitespace(gcode)
        assert count == 1
        assert result == ";foo\n"

    def test_bare_semicolon_untouched(self):
        # No leading whitespace to remove.
        gcode = ";\r\n"
        result, count = strip_comment_leading_whitespace(gcode)
        assert count == 0
        assert result == gcode

    def test_btt_thumbnail_pixel_rows_unchanged(self):
        # Pixel rows are `;0000...` -- no leading whitespace.
        gcode = ";00460046\r\n;0000ffffaaaa\r\n"
        result, count = strip_comment_leading_whitespace(gcode)
        assert count == 0
        assert result == gcode


class TestStripTrailingWhitespace:
    def test_trims_trailing_spaces(self):
        gcode = "G1 X10 Y20   \r\nG28  \r\nM104 S220\r\n"
        result, count = strip_trailing_whitespace(gcode)
        assert count == 2
        assert result == "G1 X10 Y20\r\nG28\r\nM104 S220\r\n"

    def test_trims_trailing_tabs(self):
        gcode = "G1 X10\t\t\r\n"
        result, count = strip_trailing_whitespace(gcode)
        assert count == 1
        assert result == "G1 X10\r\n"

    def test_handles_lf_endings(self):
        gcode = "G1 X10  \n"
        result, count = strip_trailing_whitespace(gcode)
        assert count == 1
        assert result == "G1 X10\n"

    def test_no_trailing_whitespace_unchanged(self):
        gcode = "G28\r\nG1 X10\r\n"
        result, count = strip_trailing_whitespace(gcode)
        assert count == 0
        assert result == gcode


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
