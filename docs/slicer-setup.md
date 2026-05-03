# Slicer Setup Walkthrough

This guide covers the printer profile settings needed for
`btt_postprocess` to do its job, for both Orca Slicer and PrusaSlicer.

The script post-processes the gcode file after slicing. For it to have
anything to work with, the slicer must emit:

1. A PNG thumbnail block in the gcode header
2. `M73 P<percent> R<minutes>` progress lines throughout the print

Both are off by default in a fresh printer profile.

---

## Orca Slicer

### Enable thumbnails

1. Open **Printer Settings** (the printer icon in the top toolbar).
2. Go to **Machine G-code**.
3. Find **G-code thumbnails** and add at least one size. Any size works — the
   script resizes to the four BTT-required sizes automatically. A reasonable
   value: `300x300`.

*[Screenshot placeholder: Orca Machine G-code tab with thumbnails field highlighted]*

### Enable M73 progress lines

1. Still in **Printer Settings**, go to **Basic Information**.
2. Click **Advanced** to expand the section.
3. Find **Disable set remaining print time** and make sure it is **unchecked**.

*[Screenshot placeholder: Orca Basic Information → Advanced with the checkbox unchecked]*

### Machine G-code entries

In **Printer Settings → Machine G-code**, add or verify the following.
These are what make the TFT switch into the printing screen and out of it.

**Start G-code** — add at the end, before any temperature wait commands:
```gcode
M118 P0 A1 action:print_start
```

**End G-code** — add at the end:
```gcode
M118 P0 A1 action:print_end
```

**Pause G-code** — replace the contents with (or prepend):
```gcode
M0
```

**Layer change G-code** — add:
```gcode
M118 P0 A1 action:notification Layer Left [layer_num]/[total_layer_count]
```

### Post-processing script

In **Print Settings → Others → Post-processing scripts**, add one of:

With the `.exe`:
```
"C:\Tools\btt_postprocess.exe";
```

With Python directly:
```
"C:\Python314\python.exe" "C:\path\to\src\btt_postprocess.py";
```

The semicolon at the end is required by Orca.

*[Screenshot placeholder: Orca post-processing field with the exe path entered]*

---

## PrusaSlicer

PrusaSlicer uses the same `SLIC3R_PP_OUTPUT_NAME` protocol as Orca, so the
script works identically.

### Enable thumbnails

1. Open **Printer Settings**.
2. Go to the **General** tab.
3. Find **G-code thumbnails** and enter one or more sizes, e.g. `300x300`.

### Enable M73 progress lines

M73 is emitted by default in PrusaSlicer. If progress updates aren't appearing,
check **Print Settings → Output options** and make sure **Verbose G-code** is
not enabled (it can interfere with some parsers, though not with this script).

### Machine G-code entries

In **Printer Settings → Custom G-code**, add:

**Start G-code** — add at the end:
```gcode
M118 P0 A1 action:print_start
```

**End G-code** — add at the end:
```gcode
M118 P0 A1 action:print_end
```

**Pause G-code**:
```gcode
M0
```

**After layer change G-code**:
```gcode
M118 P0 A1 action:notification Layer Left {layer_num}/[total_layer_count]
```

Note: PrusaSlicer uses `{layer_num}` (curly braces) where Orca uses
`[layer_num]` (square brackets).

### Post-processing script

In **Print Settings → Output options → Post-processing scripts**, add:

```
"C:\Tools\btt_postprocess.exe"
```

PrusaSlicer does not require a trailing semicolon.

---

## Verifying it works

After slicing with the script configured, open the `.gcode` file in a text
editor (or search with grep/findstr) and look for:

```
M118 P0 A1 action:print_start
```
near the top, and lines like:

```
M118 P0 A1 action:notification Time Left 01h23m00s
M118 P0 A1 action:notification Data Left 12/100
```
throughout the file.

Also check near the very top for lines starting with `;0046` or similar —
those are the RGB565 thumbnail blocks.

If the script is running, the slicer's log window (Orca: **Output** tab after
slicing) should show:

```
[btt_postprocess] myfile.gcode: thumbnail=yes, M73 lines processed=47
```
