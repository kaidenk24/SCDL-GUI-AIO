"""Account & tags page: logins borrowed from your browser, YouTube matching, and MP3 tags/artwork."""

from __future__ import annotations

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QCheckBox, QComboBox, QLineEdit, QPushButton

from scdl_gui import potoken
from scdl_gui.engine import firefox_profiles, has_pot_plugin
from scdl_gui.settings import BROWSERS, Settings
from scdl_gui.ui.album_card import AlbumCard
from scdl_gui.ui.state import AppState
from scdl_gui.ui.widgets import Card, OptionList, Page, StatusPill, hbox, label

PO_TOKEN_GUIDE = "https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide"
BROWSER_NAMES = {
    "firefox": "Firefox (recommended)", "librewolf": "LibreWolf", "chrome": "Google Chrome", "edge": "Microsoft Edge",
    "brave": "Brave", "opera": "Opera", "vivaldi": "Vivaldi", "chromium": "Chromium",
}
STATE_STYLES = {"yes": "ok", "no": "warn", "off": "busy", "checking": "busy"}


def browser_name(key: str) -> str:
    return BROWSER_NAMES.get(key, key).replace(" (recommended)", "")


class AccountPage(Page):
    check_login_requested = Signal()

    def __init__(self, state: AppState) -> None:
        super().__init__("Account & tags", "Your logins, finding DRM-protected tracks on YouTube, and what gets written into each MP3.")
        self._state = state
        self.body.addWidget(self._build_login())
        self.body.addWidget(self._build_youtube())
        self.body.addWidget(self._build_tags())
        self.body.addWidget(AlbumCard(state))
        self.finish()
        state.settings_changed.connect(lambda _s: self._load())
        self._load()

    # ---- cards
    def _build_login(self) -> Card:
        card = Card(
            "SoundCloud login",
            "The app borrows your SoundCloud login from your web browser - no password is ever entered here. "
            "With a Go+ account you get full tracks in 256k quality.",
        )
        self.browser = QComboBox()
        for key in BROWSERS:
            self.browser.addItem(BROWSER_NAMES[key], key)
        self.browser.activated.connect(lambda _i: self._state.update(cookie_browser=self.browser.currentData()))
        self.pill = StatusPill()
        self.use_login = QCheckBox("Use my SoundCloud login")
        self.use_login.toggled.connect(lambda on: self._state.update(use_login=on))
        self.profile = QComboBox()
        self.profile.setMinimumWidth(240)
        self.profile.activated.connect(lambda _i: self._state.update(firefox_profile=self.profile.currentData() or ""))
        self.profile_label = label("Firefox profile:")
        check = QPushButton("Check again")
        check.clicked.connect(self.check_login_requested.emit)
        card.body.addLayout(hbox(label("Borrow logins from:"), self.browser, None, self.pill))
        card.body.addWidget(self.use_login)
        card.body.addLayout(hbox(self.profile_label, self.profile, check, None))
        self.login_hint = label("", "Hint", wrap=True)
        card.body.addWidget(self.login_hint)
        return card

    def _build_youtube(self) -> Card:
        card = Card(
            "YouTube (for DRM-protected tracks)",
            "Some label releases on SoundCloud are DRM-protected and can't be downloaded. The app can find the "
            "same song on YouTube and show you the matches - nothing is downloaded until you confirm it on the "
            "YouTube matches page.",
        )
        self.youtube_fallback = QCheckBox("Find DRM-protected tracks on YouTube for me to confirm")
        self.youtube_fallback.toggled.connect(lambda on: self._state.update(youtube_fallback=on))
        self.youtube_login = QCheckBox("Use my YouTube login (same browser as above)")
        self.youtube_login.setToolTip("Signed-in requests are blocked less often; YouTube Music Premium unlocks 256k audio.")
        self.youtube_login.toggled.connect(lambda on: self._state.update(youtube_login=on))
        self.youtube_pill = StatusPill()
        card.body.addWidget(self.youtube_fallback)
        card.body.addLayout(hbox(self.youtube_login, None, self.youtube_pill))

        self.po_token = QLineEdit()
        self.po_token.setPlaceholderText("Optional - paste a YouTube Music (GVS) PO token")
        self.po_token.setEchoMode(QLineEdit.EchoMode.PasswordEchoOnEdit)
        self.po_token.editingFinished.connect(lambda: self._state.update(youtube_po_token=self.po_token.text().strip()))
        guide = QPushButton("How to get one")
        guide.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(PO_TOKEN_GUIDE)))
        card.body.addLayout(hbox(label("PO token:"), self.po_token, guide))
        self.po_hint = label("", "Hint", wrap=True)
        card.body.addWidget(self.po_hint)
        card.body.addWidget(label("YouTube needs Node.js, and Premium audio needs PO tokens - both on Setup & updates.", "Hint"))
        return card

    def _build_tags(self) -> Card:
        card = Card("Tags & artwork", "Title, artist, date and the SoundCloud link are always saved.")
        self.art = OptionList([
            (True, "Full-size cover art", "The original artwork, often 1000-3000 px."),
            (False, "Small cover art (500 x 500)", "Smaller files; some car stereos prefer it."),
        ])
        self.art.changed.connect(lambda full: self._state.update(full_art=full))
        card.body.addWidget(self.art)
        self.artist_from_title = QCheckBox('Take the artist from titles like "Artist - Song" (instead of the uploader)')
        self.artist_from_title.toggled.connect(lambda on: self._state.update(artist_from_title=on))
        self.description = QCheckBox("Also save each track's description as a .txt file")
        self.description.toggled.connect(lambda on: self._state.update(save_description=on))
        for box in (self.artist_from_title, self.description):
            card.body.addWidget(box)
        return card

    # ---- login status
    def set_login_state(self, state: str, detail: str = "") -> None:
        browser = browser_name(self._state.settings.cookie_browser)
        text = {"yes": f"Logged in via {browser}", "no": "Not logged in", "off": "Login turned off",
                "checking": "Checking..."}.get(state, f"Couldn't read {browser}")
        self.pill.set_state(STATE_STYLES.get(state, "error"), text)
        hints = {
            "yes": "Downloads use your account. Logged out or switched accounts? Press Check again.",
            "no": f"Open soundcloud.com in {browser}, sign in, then press Check again. Without a login, Go+ tracks are skipped.",
            "off": "Downloads run without an account; Go+ tracks are skipped.",
            "error": (f"Is {browser} installed? Chrome, Edge and other Chromium browsers encrypt their cookies - "
                      f"close the browser and try again, or use Firefox. {detail}").strip(),
            "checking": "",
        }
        self.login_hint.setText(hints.get(state, detail))

    def set_youtube_state(self, state: str) -> None:
        text = {"yes": "Logged in to YouTube", "no": "Not logged in", "off": "Login off",
                "checking": "Checking..."}.get(state, "Couldn't read the browser")
        self.youtube_pill.set_state(STATE_STYLES.get(state, "error"), text)

    # ---- settings -> widgets
    def _load(self) -> None:
        s: Settings = self._state.settings
        for box, value in (
            (self.use_login, s.use_login),
            (self.artist_from_title, s.artist_from_title), (self.description, s.save_description),
            (self.youtube_fallback, s.youtube_fallback), (self.youtube_login, s.youtube_login),
        ):
            box.blockSignals(True)
            box.setChecked(value)
            box.blockSignals(False)
        self.browser.setCurrentIndex(max(self.browser.findData(s.cookie_browser), 0))
        is_firefox = s.cookie_browser == "firefox"
        self.profile_label.setVisible(is_firefox)
        self.profile.setVisible(is_firefox)
        if is_firefox:
            self.profile.clear()
            self.profile.addItem("Most recently used (automatic)", "")
            for name, path in firefox_profiles():
                self.profile.addItem(name, path)
            self.profile.setCurrentIndex(max(self.profile.findData(s.firefox_profile), 0))
            self.profile.setEnabled(s.use_login or s.youtube_login)
        for widget in (self.youtube_login, self.po_token):
            widget.setEnabled(s.youtube_fallback)
        if self.po_token.text() != s.youtube_po_token:
            self.po_token.setText(s.youtube_po_token)
        if s.auto_po_token and potoken.installed():
            self.po_hint.setText("Automatic PO tokens are set up (Setup & updates), so there's no need to paste one. "
                                 "With YouTube Music Premium, matches download at 256k+.")
        elif has_pot_plugin():
            self.po_hint.setText("A PO-token plugin is installed, so tokens are fetched automatically.")
        elif s.youtube_po_token:
            self.po_hint.setText("Using your PO token with the YouTube Music client. Tokens expire - if downloads start "
                                 "failing, paste a fresh one or clear the box.")
        else:
            self.po_hint.setText("Without a PO token YouTube gives ~130-140 kbps audio. With YouTube Music Premium, set up "
                                 "automatic PO tokens on the Setup & updates page (or paste one here) for 256k+ audio.")
        self.art.set_value(s.full_art)
