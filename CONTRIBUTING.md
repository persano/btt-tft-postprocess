# Contributing

This is a small hobby utility. Contributions are welcome but the bar is
intentionally low — the goal is a script that works reliably for the people
who need it, not a general-purpose framework.

## What's in scope

- Bug fixes
- Support for additional slicer thumbnail formats (if the slicer also uses
  Orca/PrusaSlicer's `; thumbnail begin` format, it probably already works)
- Documentation improvements
- Test coverage improvements

## What's out of scope (for now)

- GUI
- Config files / user-settable options
- Cura support (Cura's post-processing mechanism is different; it would need
  a separate plugin, not a tweak here)
- Telemetry, update checks, network features of any kind

## Getting started

```
git clone https://github.com/YOUR_USERNAME/btt-tft-postprocess
cd btt-tft-postprocess
pip install -e ".[dev]"   # installs Pillow + pytest
pytest
```

## Running tests

```
pytest
```

Tests live in `tests/`. They cover the pure-logic functions; no hardware or
slicer needed.

## Submitting changes

1. Fork the repo and create a branch.
2. Make your change and add or update tests if relevant.
3. Run `pytest` and confirm it passes.
4. Open a pull request with a short description of what changed and why.
