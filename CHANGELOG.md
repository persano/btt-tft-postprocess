# Changelog

## Unreleased

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
