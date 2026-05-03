# BTT TFT Post-processor

[![CI](https://github.com/persano/btt-tft-postprocess/actions/workflows/build-release.yml/badge.svg)](https://github.com/persano/btt-tft-postprocess/actions/workflows/build-release.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

If you print via a closed-source remote host — Mintion Beagle camera, ESP3D,
Pronterface, or anything else that isn't OctoPrint-with-the-BTT-plugin — your
BTT TFT touchscreen probably sits on its idle menu for the entire print. No
thumbnail, no time remaining, no progress bar. This script fixes that by
injecting the host-action commands directly into the sliced gcode file. The
TFT picks them up off the serial wire regardless of which host is streaming,
so you get the full printing screen without touching the host at all.

*[Screenshots placeholder — TFT idle screen vs. printing screen with thumbnail
and progress bar. Add to `docs/screenshots/` and link here.]*

---

## Does this apply to you?

- Your printer has a BTT TFT touchscreen running
  [BIGTREETECH TouchScreenFirmware](https://github.com/bigtreetech/BIGTREETECH-TouchScreenFirmware)
- Your printer runs Marlin firmware
- You slice with Orca Slicer or PrusaSlicer
- You print via a remote host that isn't OctoPrint (or OctoPrint without the
  BTT plugin)
- The TFT shows its idle screen during prints instead of the printing screen

If most of those are true, this is for you.

> If you use OctoPrint, the
> [BTT TFT Touchscreen Support plugin](https://plugins.octoprint.org/plugins/btt_tft_touchscreen/)
> is the cleaner solution — it sends the commands live without modifying gcode
> files.

---

## Install — 30 seconds, no Python required

1. Download `btt_postprocess.exe` from the
   [Releases page](../../releases/latest).
2. Save it somewhere permanent, e.g. `C:\Tools\btt_postprocess.exe`.
3. In Orca Slicer: **Print Settings → Others → Post-processing scripts**, add:

   ```
   "C:\Tools\btt_postprocess.exe";
   ```

Re-slice any file. Orca shows a log after slicing — you should see a line like:

```
[btt_postprocess] myfile.gcode: thumbnail=yes, M73 lines processed=47
```

> **Windows Defender warning**: PyInstaller binaries sometimes trigger a
> SmartScreen warning on first run. This is a known false positive — the
> executable has no network code, no telemetry, and no update mechanism.
> Source is in this repo if you want to verify.

---

## Install — Python script

If you'd rather run the source directly:

1. Install Python 3.10+ (tick "Add to PATH" during setup).
2. `pip install Pillow`
3. In Orca: **Print Settings → Others → Post-processing scripts**:

   Windows:
   ```
   "C:\Python314\python.exe" "C:\path\to\src\btt_postprocess.py";
   ```

   macOS / Linux:
   ```
   /usr/bin/env python3 "/path/to/src/btt_postprocess.py";
   ```

Or install as a CLI tool:

```
pip install .
btt-postprocess /path/to/file.gcode
```

---

## What it does to your gcode

Two transformations in one pass over the file:

**Thumbnail conversion.** The slicer embeds a PNG thumbnail in a comment
block. This script resizes it to the four sizes BTT firmware expects
(70×70, 95×80, 95×95, 160×140), converts each to RGB565 hex, and prepends
the result to the file. Without this step, the TFT can't show a print preview.

**Progress notifications.** After every `M73 P<percent> R<minutes>` line the
slicer emits, the script injects:

```
M118 P0 A1 action:notification Time Left HHhMMm00s
M118 P0 A1 action:notification Data Left <percent>/100
```

These drive the time-left countdown and progress bar on the TFT. Original
gcode lines are preserved — the script only adds content.

---

## Slicer setup checklist

The script needs the slicer to emit certain things. Check both:

| Setting | Location in Orca | Required value |
|---|---|---|
| G-code thumbnails | Printer Settings → Machine G-code | enabled (any size) |
| Disable set remaining print time | Printer Settings → Basic Info → Advanced | **unchecked** |

Also add these to your printer profile's Machine G-code if they aren't there:

```gcode
; Start G-code
M118 P0 A1 action:print_start

; End G-code
M118 P0 A1 action:print_end

; Pause G-code
M0

; Layer change G-code
M118 P0 A1 action:notification Layer Left [layer_num]/[total_layer_count]
```

See [docs/slicer-setup.md](docs/slicer-setup.md) for a step-by-step walkthrough
with screenshots for both Orca Slicer and PrusaSlicer.

---

## Known limitations

**App-initiated pause/resume/cancel.** If your host (e.g. Mintion Beagle)
doesn't send standard `M25`/`M24`/`M524` commands, the TFT's hardware buttons
and your app's pause button won't be linked. The Beagle uses its own park
sequence, so this is a Beagle firmware limitation — not something this script
can bridge.

**999-layer display cap.** Most BTT TFT firmware versions display at most 999
in the layer counter. Prints with more layers clip at 999 in the display but
print normally.

**`_btt` suffix on output file.** If your slicer sets `SLIC3R_PP_OUTPUT_NAME`
(Orca and PrusaSlicer both do), the post-processed file gets a `_btt` suffix.
This is intentional, matching the original BIQU script's behavior. If you
re-run the script on an already-processed file you'll get `_btt_btt` — re-slice
instead of running manually on existing files.

---

## Troubleshooting

**No thumbnail on the TFT.** Check the slicer log for `thumbnail=yes/no`. If
`no`, make sure G-code thumbnails are enabled in Printer Settings → Machine
G-code. Any thumbnail size works; the script resizes it.

**Progress bar / time left never update.** Open the sliced gcode in a text
editor and search for `M73`. If there are no hits, the slicer isn't emitting
them — uncheck "Disable set remaining print time" in Printer Settings → Basic
Information → Advanced.

**Slicer reports post-processing failed.** Run the script manually to see the
full error:

```
btt_postprocess.exe C:\path\to\file.gcode
```

or with Python:

```
python src\btt_postprocess.py C:\path\to\file.gcode
```

---

## Building the .exe yourself

```
pip install pyinstaller Pillow
build_exe.bat
```

Output: `dist\btt_postprocess.exe` (~15 MB, no Python required to run).

---

## Credits

The thumbnail conversion approach reimplements the logic from BIQU/BIGTREETECH's
`biqu_convert_p24.py`, part of the
[BIGTREETECH-TouchScreenFirmware](https://github.com/bigtreetech/BIGTREETECH-TouchScreenFirmware)
project. This script uses Pillow instead of PyQt5, which produces a smaller
executable and removes the Qt dependency.

---

## License

MIT — see [LICENSE](LICENSE).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Issues

[Open an issue](../../issues) for bugs or feature requests.
