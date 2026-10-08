"""Renders the app's pages to PNGs with made-up demo data (for the README and for checking the UI).

Usage: python tools/screenshots.py OUTPUT_DIR [WIDTHxHEIGHT]   (default 1280x820)
Uses a throwaway settings folder, so your real settings and queue are never touched.
Tip: set QT_QPA_PLATFORM=offscreen and QT_QPA_FONTDIR=C:\\Windows\\Fonts to render without a window.
"""

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from scdl_gui import matches as matches_mod  # noqa: E402
from scdl_gui import settings as settings_mod  # noqa: E402

_scratch = Path(tempfile.mkdtemp(prefix="scdl-gui-shots-"))
settings_mod.data_dir = lambda: _scratch
matches_mod.data_dir = lambda: _scratch

import scdl_gui.ui.setup_page as setup_page  # noqa: E402
from scdl_gui.matches import REVIEW, MatchItem, save_matches  # noqa: E402

# Don't show this machine's real tool paths (they contain the Windows user name).
setup_page.find_ffmpeg = lambda _settings: "C:\\Program Files\\FFmpeg\\bin\\ffmpeg.exe"
setup_page.find_js_runtime = lambda: "C:\\Program Files\\nodejs\\node.exe"
from scdl_gui.settings import Job, Settings, save_queue  # noqa: E402
from scdl_gui.ui.main_window import NAV, MainWindow  # noqa: E402
from scdl_gui.ui.state import AppState  # noqa: E402
from scdl_gui.ui.theme import apply_theme  # noqa: E402
from scdl_gui.watches import Watch, save_watches  # noqa: E402

DEMO_QUEUE = [
    Job("https://soundcloud.com/djexample/sets/summer-house", None, True, "Summer House", "Playlist", "Done - 42 new, 1 to match on YouTube"),
    Job("https://soundcloud.com/djexample/sets/gym-mix", "Gym\\{playlist}", True, "Gym Mix", "Playlist", "Queued"),
    Job("https://soundcloud.com/djexample/likes", None, True, "djexample (Likes)", "Likes", "Queued"),
    Job("https://soundcloud.com/djexample/sets/wedding-party", "Wedding", True, "Wedding Party", "Playlist", "Queued"),
    Job("https://soundcloud.com/nightowl/night-drive", "", False, "Night Drive  (nightowl)", "Track", "Done - 1 new"),
]
_NOW = time.time()
DEMO_WATCHES = [
    Watch("https://soundcloud.com/djexample/sets/summer-house", None, "Summer House", "Playlist", True,
          _NOW - 40 * 60, "2 new tracks", _NOW - 40 * 60, 14),
    Watch("https://soundcloud.com/djexample/sets/gym-mix", "Gym\\{playlist}", "Gym Mix", "Playlist", True,
          _NOW - 40 * 60, "Up to date", 0.0, 3),
    Watch("https://soundcloud.com/djexample/likes", "Likes", "djexample (Likes)", "Likes", True,
          _NOW - 2 * 3600, "1 new track, 1 to match on YouTube", _NOW - 2 * 3600, 37),
    Watch("https://soundcloud.com/djexample/sets/wedding-party", "Wedding", "Wedding Party", "Playlist", False,
          _NOW - 3 * 86400, "Up to date", 0.0, 0),
]
DEMO_MATCH = MatchItem(
    track={
        "sc_id": "1", "title": "Neon Skyline", "uploader": "Aurora Vale", "artist": "Aurora Vale", "duration": 187,
        "playlist": "Summer House", "playlist_index": 12, "isrc": "XX0000000001",
        "target": "C:\\Users\\you\\Music\\SoundCloud\\Summer House\\Neon Skyline", "sc_url": "https://soundcloud.com",
    },
    status=REVIEW, query="Aurora Vale Neon Skyline",
    candidates=[
        {"id": "a", "url": "https://www.youtube.com", "title": "Neon Skyline", "channel": "Aurora Vale - Topic", "duration": 187, "source": "YouTube", "score": 100},
        {"id": "b", "url": "https://www.youtube.com", "title": "Aurora Vale - Neon Skyline (Official Audio)", "channel": "Skyline Records", "duration": 188, "source": "YouTube", "score": 96},
        {"id": "c", "url": "https://music.youtube.com", "title": "Neon Skyline", "channel": "Somebody Else", "duration": 201, "source": "YouTube Music", "score": 52},
        {"id": "d", "url": "https://www.youtube.com", "title": "Neon Skyline (Extended Mix)", "channel": "Aurora Vale - Topic", "duration": 262, "source": "YouTube", "score": 21},
    ],
)


def main(out_dir: str, size: str = "1280x820") -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    save_queue(DEMO_QUEUE)
    save_matches([DEMO_MATCH])
    save_watches(DEMO_WATCHES)
    app = QApplication(sys.argv)
    apply_theme(app)
    library = str(Path.home() / "Music" / "SoundCloud").replace(str(Path.home()), "C:\\Users\\you")
    settings = Settings(library=library, folders=("Gym", "Wedding", "Likes", "E:\\Car"), offered_shortcuts=True, check_updates=False)
    window = MainWindow(AppState(settings))
    width, height = (int(n) for n in size.lower().split("x"))
    window.setMinimumSize(0, 0)
    window.resize(width, height)
    window.show()
    for level, text in (
        ("info", "> Summer House"), ("ok", "  + Golden Hour"), ("skip", "  = already have: Night Drive"),
        ("warn", "  ~ auroravale/neon-skyline - DRM-protected on SoundCloud - looking for it on YouTube"),
        ("info", "  Done - 42 new, 1 to match on YouTube"),
    ):
        window.activity_page.add(level, text)

    def capture(index: int = 0) -> None:
        if index >= window.pages.count():
            app.quit()
            return
        window.nav.setCurrentRow(index)
        name = NAV[index][0].lower().replace(" & ", "-").replace(" ", "-")
        QTimer.singleShot(400, lambda: (window.grab().save(str(out / f"{name}.png")), capture(index + 1)))

    QTimer.singleShot(1500, capture)
    app.exec()


if __name__ == "__main__":
    main(*sys.argv[1:3])
