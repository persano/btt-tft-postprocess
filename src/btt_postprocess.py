#!/usr/bin/env python3
"""
Orca/PrusaSlicer post-processing script for BIGTREETECH TFT screens.

Combines several jobs into one pass over the sliced .gcode:

1) Converts the slicer's PNG thumbnail into the BIGTREETECH TFT's
   RGB565-hex format (multiple sizes), prepending it to the gcode file.
   Equivalent in behavior to BIQU's biqu_convert_p24.py but uses Pillow
   instead of PyQt5 so the resulting frozen .exe is much smaller.

2) After every M73 line emitted by the slicer (P=percent, R=minutes left),
   injects two M118 action:notification lines so a BTT TFT shows live
   Time Left and a 0-100% progress bar.

3) Strips M115 firmware-info queries from the file. They have no effect on
   a print but their multi-line response can race with M105 temperature
   polls on the serial line and overflow the RX buffer on hosts that proxy
   serial (Mintion Beagle camera, some ESP3D variants).
   See https://forum.prusa3d.com/forum/.../beagle-camera-v2-and-mk4/paged/4/

4) Upgrades the final pre-print M104 (set hotend temp, no wait) to M109
   (wait) when the slicer's auto-generated header forgot to wait. Works
   around OrcaSlicer issues #2334 and #4337 where the print starts moving
   before the nozzle has reached temperature.

The original gcode lines (M73, thumbnail block) are preserved -- we only
ADD content. Marlin still uses M73 for its own internal progress tracking.

Usage in Orca:
    Print Settings -> Others -> Post-processing scripts
        "C:\\Path\\To\\python.exe" "C:\\Path\\To\\btt_postprocess.py";
    or with the frozen .exe:
        "C:\\Path\\To\\btt_postprocess.exe";

Behavior notes:
- If the gcode has no thumbnail block (slicer setting disabled), the script
  skips the thumbnail step gracefully and still does the M73 conversion.
- Honors the SLIC3R_PP_OUTPUT_NAME environment variable: writes a sidecar
  .output_name file so the final filename gets a "_btt" suffix, matching
  the original BIQU script's behavior.
"""

from __future__ import annotations

import base64
import io
import os
import re
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("!!! Pillow is required. Run: pip install Pillow", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Thumbnail conversion (PNG base64 -> RGB565 hex blocks for BTT TFT)
# ---------------------------------------------------------------------------

# Sizes the BTT TFT firmware looks for in the gcode header, in order.
THUMBNAIL_SIZES: list[tuple[int, int]] = [
    (70, 70),
    (95, 80),
    (95, 95),
    (160, 140),
]

# RGB565 values that are visually black-ish but not exactly zero. The original
# BIQU script clamps these to pure black to avoid a faint speckle pattern on
# the TFT background. We preserve the same noise filter for compatibility.
NEAR_BLACK_RGB565 = {"0020", "0841", "0861"}


def rgb_to_rgb565_hex(r: int, g: int, b: int) -> str:
    """Pack an RGB888 triple into a 4-char big-endian RGB565 hex string."""
    pixel = (r << 16) | (g << 8) | b
    val = (
        ((pixel & 0x00F80000) >> 8)   # R: top 5 bits -> bits 11-15
        | ((pixel & 0x0000FC00) >> 5) # G: top 6 bits -> bits 5-10
        | ((pixel & 0x000000F8) >> 3) # B: top 5 bits -> bits 0-4
    )
    hex_val = f"{val:04x}"
    # Stomp near-black noise to true black, like the original script.
    return "0000" if hex_val in NEAR_BLACK_RGB565 else hex_val


def render_thumbnail_block(img: Image.Image, width: int, height: int) -> str:
    """
    Resize the source image to (width, height) and emit one BTT thumbnail
    block: a header line with size + one line per row of RGB565 hex pixels.
    """
    resized = img.resize((width, height), Image.LANCZOS).convert("RGB")
    pixels = resized.load()

    lines: list[str] = []
    # Header: ";WWWWHHHH" where each value is 4-char zero-padded hex.
    lines.append(f";{width:04x}{height:04x}\r\n")

    for y in range(height):
        row_chars = [";"]
        for x in range(width):
            r, g, b = pixels[x, y]
            row_chars.append(rgb_to_rgb565_hex(r, g, b))
        row_chars.append("\r\n")
        lines.append("".join(row_chars))

    return "".join(lines)


def extract_png_from_gcode(gcode_text: str) -> bytes | None:
    """
    Pull out the base64-encoded PNG between '; thumbnail begin' and
    '; thumbnail end' markers in slicer-emitted gcode. Returns the raw PNG
    bytes, or None if no thumbnail is present.
    """
    inside = False
    b64_chunks: list[str] = []

    for line in gcode_text.splitlines():
        if line.startswith("; thumbnail begin"):
            inside = True
            continue
        if line.startswith("; thumbnail end"):
            break
        if not inside:
            continue
        # Lines look like "; <base64 chars>"; strip the leading "; ".
        if line.startswith("; "):
            b64_chunks.append(line[2:].strip())
        else:
            b64_chunks.append(line.strip())

    if not b64_chunks:
        return None

    try:
        return base64.b64decode("".join(b64_chunks))
    except (ValueError, base64.binascii.Error) as exc:
        print(f"[btt_postprocess] thumbnail base64 decode failed: {exc}",
              file=sys.stderr)
        return None


def build_thumbnail_header(gcode_text: str) -> str:
    """
    Build the multi-size BTT thumbnail block to prepend to the gcode.
    Returns "" if there's no source thumbnail to work from.
    """
    png_bytes = extract_png_from_gcode(gcode_text)
    if png_bytes is None:
        print("[btt_postprocess] no thumbnail found in gcode; "
              "skipping thumbnail conversion.")
        return ""

    try:
        img = Image.open(io.BytesIO(png_bytes))
        img.load()  # force decode now so we surface errors here
    except Exception as exc:
        print(f"[btt_postprocess] failed to open thumbnail PNG: {exc}",
              file=sys.stderr)
        return ""

    parts: list[str] = []
    for w, h in THUMBNAIL_SIZES:
        parts.append(render_thumbnail_block(img, w, h))
    parts.append("; bigtree thumbnail end\r\n\r\n")
    return "".join(parts)


# ---------------------------------------------------------------------------
# M73 -> M118 action:notification injection
# ---------------------------------------------------------------------------

# Match an M73 line that has at least a P=percent token, optionally R=minutes.
M73_RE = re.compile(
    r"^\s*M73\b"
    r".*?P\s*(?P<p>\d+)"
    r"(?:.*?R\s*(?P<r>\d+))?",
    re.IGNORECASE,
)


def format_time_left(minutes: int) -> str:
    """Format remaining minutes as XXhYYmZZs (TFT firmware expected format)."""
    hours, mins = divmod(minutes, 60)
    return f"{hours:02d}h{mins:02d}m00s"


def build_m73_notifications(percent: int, minutes: int | None) -> list[str]:
    """Build the M118 lines to inject after an M73."""
    out = []
    if minutes is not None:
        out.append(
            f"M118 P0 A1 action:notification Time Left "
            f"{format_time_left(minutes)}\r\n"
        )
    out.append(
        f"M118 P0 A1 action:notification Data Left {percent}/100\r\n"
    )
    return out


def inject_m73_notifications(gcode_text: str) -> tuple[str, int]:
    """
    Walk the gcode line by line; after each real M73 line, append M118
    notifications. Returns (new_text, count_of_m73_lines_processed).
    """
    output: list[str] = []
    m73_count = 0

    # splitlines(keepends=True) preserves \r\n endings as-is.
    for line in gcode_text.splitlines(keepends=True):
        output.append(line)

        stripped = line.lstrip()
        if not stripped or stripped.startswith(";"):
            continue

        match = M73_RE.match(line)
        if not match:
            continue

        percent = int(match.group("p"))
        minutes = int(match.group("r")) if match.group("r") is not None else None
        output.extend(build_m73_notifications(percent, minutes))
        m73_count += 1

    return "".join(output), m73_count


# ---------------------------------------------------------------------------
# Serial-friendliness fixes for hosts that proxy the print line
# ---------------------------------------------------------------------------

_M115_RE = re.compile(r"^\s*M115\b", re.IGNORECASE)

# Match an extrusion move: G0/G1/G2/G3 with an E parameter. Once we hit one of
# these we're past the warmup region and into the actual print.
_EXTRUSION_RE = re.compile(r"^\s*G[0-3]\b(?=.*\bE-?\d)", re.IGNORECASE)

# M104/M109 with an S<temp> argument. The (?!\.\d) guard skips M104.1 etc.,
# which are filament-change variants with different semantics.
_M104_TEMP_RE = re.compile(
    r"^\s*M104(?!\.\d)\b.*?\bS\s*(?P<s>-?\d+)", re.IGNORECASE
)
# M109 accepts either S (wait while heating) or R (wait either direction);
# both count as "the printer will wait here", so we treat them equivalently.
_M109_WAIT_RE = re.compile(
    r"^\s*M109(?!\.\d)\b.*?\b[SR]\s*(?P<s>-?\d+)", re.IGNORECASE
)


def strip_m115_queries(text: str) -> tuple[str, int]:
    """Remove M115 firmware-info queries. Returns (new_text, removed_count)."""
    out: list[str] = []
    removed = 0
    for line in text.splitlines(keepends=True):
        if _M115_RE.match(line):
            removed += 1
            continue
        out.append(line)
    return "".join(out), removed


def upgrade_final_warmup_m104_to_m109(text: str) -> tuple[str, int]:
    """
    Walk the file until the first extrusion move. Within that warmup window,
    track the most recent M104 S>0 that isn't followed by an M109 wait. If
    one remains at the end of the window, rewrite it to M109 so the printer
    waits for the nozzle before motion begins.

    Returns (new_text, 1) if a line was upgraded, otherwise (text, 0).
    """
    lines = text.splitlines(keepends=True)
    pending_m104: int | None = None

    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if not stripped or stripped.startswith(";"):
            continue
        if _EXTRUSION_RE.match(line):
            break

        m109 = _M109_WAIT_RE.match(line)
        if m109 and int(m109.group("s")) > 0:
            # Printer will already wait here -- nothing earlier needs fixing.
            pending_m104 = None
            continue

        m104 = _M104_TEMP_RE.match(line)
        if m104 and int(m104.group("s")) > 0:
            pending_m104 = i

    if pending_m104 is None:
        return text, 0

    lines[pending_m104] = re.sub(
        r"\bM104\b", "M109", lines[pending_m104], count=1, flags=re.IGNORECASE,
    )
    return "".join(lines), 1


# ---------------------------------------------------------------------------
# Output filename hint (matches BIQU script behavior)
# ---------------------------------------------------------------------------

def write_output_name_hint(gcode_path: Path) -> None:
    """
    Some slicers (PrusaSlicer/Orca) honor a "<gcode>.output_name" sidecar
    file to rename the post-processed file. We use it to add a "_btt"
    suffix, matching the original BIQU script.
    """
    env_name = os.getenv("SLIC3R_PP_OUTPUT_NAME")
    if not env_name:
        return  # not running under a slicer that sets this; that's fine

    base, ext = os.path.splitext(env_name)
    final_name = f"{base}_btt{ext}"
    sidecar = gcode_path.with_name(gcode_path.name + ".output_name")
    try:
        sidecar.write_text(final_name, encoding="utf-8")
    except OSError as exc:
        print(f"[btt_postprocess] could not write output_name sidecar: {exc}",
              file=sys.stderr)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def process_gcode(path: Path) -> None:
    """Run both transformations on the file, in place."""
    # Read raw to preserve line endings as much as possible. The slicer
    # writes UTF-8; replacement on errors keeps us robust to odd bytes.
    text = path.read_text(encoding="utf-8", errors="replace")

    thumbnail_header = build_thumbnail_header(text)
    new_text, m73_count = inject_m73_notifications(text)
    new_text, m115_stripped = strip_m115_queries(new_text)
    new_text, m104_upgraded = upgrade_final_warmup_m104_to_m109(new_text)
    final_text = thumbnail_header + new_text

    path.write_text(final_text, encoding="utf-8")
    write_output_name_hint(path)

    has_thumb = "yes" if thumbnail_header else "no"
    print(f"[btt_postprocess] {path.name}: "
          f"thumbnail={has_thumb}, M73 lines processed={m73_count}, "
          f"M115 stripped={m115_stripped}, "
          f"M104->M109 warmup fix={m104_upgraded}")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Usage: btt_postprocess <gcode_file>", file=sys.stderr)
        return 1

    target = Path(argv[1])
    if not target.is_file():
        print(f"File not found: {target}", file=sys.stderr)
        return 1

    try:
        process_gcode(target)
    except Exception as exc:
        # Never crash the slicer's pipeline silently -- log and exit nonzero.
        print(f"[btt_postprocess] ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


def cli() -> None:
    """Console script entry point for pip-installed use."""
    sys.exit(main(sys.argv))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
