# Changelog

## Unreleased

Beagle-compatibility fixes:

- Strip `M115` firmware-info queries from the file. Their multi-line response
  can race with `M105` temperature polls on hosts that proxy the serial line
  (Mintion Beagle, some ESP3D variants) and overflow the host's RX buffer
  during print startup.
- Upgrade the final pre-print `M104 S>0` to `M109` when the slicer's
  auto-generated header forgot to wait for the nozzle. Works around
  OrcaSlicer issues #2334 / #4337 where the print starts moving before the
  hotend has reached temperature. Skips `M104 S0` cool-downs, `M104.1`
  filament-change variants, and any `M104` that already has a following
  `M109` wait or appears after the first extrusion move.
- Inject `M155 S30` before the first executable command to throttle
  Marlin's automatic temperature auto-reports from 5s (default) to 30s.
  Cuts serial traffic ~6x and is the other half of the Beagle
  buffer-overflow story. Skipped if the user already has an `M155` in
  the warmup region.

Size reduction:

- Strip the slicer's base64 PNG thumbnail block(s) after extracting the
  bitmap for the BTT TFT. Removes 50-200 KB of dead-weight base64.
- Strip slicer "feature" comments that no firmware consumer reads:
  `;TYPE:`, `;WIDTH:`, `;HEIGHT:`, `;Z:`, wipe markers, object IDs, and
  Orca's HEADER/THUMBNAIL/EXECUTABLE block delimiters. Preserves
  `LAYER_CHANGE` / `LAYER_COUNT` which BTT TFT firmware does read.
- Strip the trailing `; comment` portion of G/M command lines
  (`G1 X10 ; whatever` -> `G1 X10`). Leaves standalone comments and
  M117/M118 display messages alone.
- Drop blank lines.

Idempotency:

- Strip any pre-existing BTT thumbnail block at the top of the file
  before prepending a fresh one. Re-running the script on its own
  output no longer doubles the thumbnail.
- Skip `M118 action:notification` injection if a notification already
  follows the `M73` line. Re-running no longer stacks duplicate
  notification pairs.

## v0.1.0 — 2025-05-03

Initial public release.

- Thumbnail conversion: reads the slicer's PNG thumbnail, resizes to the four
  sizes BTT TFT firmware expects (70×70, 95×80, 95×95, 160×140), converts to
  RGB565 hex, prepends to gcode. Uses Pillow instead of PyQt5.
- Progress notifications: after every `M73 P<pct> R<min>` line, injects
  `M118 P0 A1 action:notification` lines for time-left countdown and progress
  bar on the TFT.
- `_btt` output filename suffix via `SLIC3R_PP_OUTPUT_NAME` sidecar, matching
  original BIQU script behavior.
- Windows `.exe` build via PyInstaller (`build_exe.bat`).
- Tested on Artillery Genius Pro, stock BTT TFT firmware, Orca Slicer,
  Mintion Beagle camera.
