# Contributing

Thanks for helping! Bug reports with a log (see the issue template) are the most useful thing you can send.

## Getting started

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python -m unittest discover -s tests
.venv\Scripts\python scdl-gui.pyw
```

## Guidelines

- Keep non-UI logic out of `scdl_gui/ui/` and cover it with tests in `tests/`.
- The download worker (`worker.py`, `youtube.py`) runs in its own process and talks to the app through
  `@@NAME {json}` lines - see `parsing.py`.
- Don't put real people's names, links or file paths in tests, screenshots or examples.
- Check `tools/build.ps1` still builds if you add dependencies (the Windows app is built with PyInstaller).

By contributing you agree that your contributions are licensed under GPL-2.0-or-later.
