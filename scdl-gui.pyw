"""Start SoundCloud Downloader from source (double-click; runs without a console window).

Easiest: use run.bat, which installs everything this needs on first launch.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _show_setup_hint(error: Exception) -> None:
    message = (
        f"SoundCloud Downloader can't start: {error}\n\n"
        "Start it with run.bat (in the same folder) - it installs everything it needs.\n"
        "Or download the ready-made app from https://github.com/kaidenk24/scdl-gui/releases"
    )
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "SoundCloud Downloader", 0x10)
    except (ImportError, AttributeError, OSError):
        print(message, file=sys.stderr)


if __name__ == "__main__":
    if sys.version_info < (3, 10):
        _show_setup_hint(RuntimeError(f"Python 3.10 or newer is needed (this is {sys.version.split()[0]})"))
        sys.exit(1)
    import importlib.util

    is_worker = sys.argv[1:2] == ["--worker"]
    if not is_worker and importlib.util.find_spec("PySide6") is None:
        _show_setup_hint(ImportError("the PySide6 package isn't installed"))
        sys.exit(1)
    from scdl_gui.main import main

    sys.exit(main(sys.argv[1:]))
