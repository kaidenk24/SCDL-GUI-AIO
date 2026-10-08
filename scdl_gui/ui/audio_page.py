"""Audio page: MP3 quality, volume levelling and which SoundCloud source to use."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QButtonGroup, QCheckBox, QPushButton, QSlider, QSpinBox

from scdl_gui.ui.state import AppState
from scdl_gui.ui.widgets import Card, OptionList, Page, hbox, label

QUALITY_OPTIONS = [
    ("V0", "Best (VBR V0, ~245 kbps) - recommended", "Top LAME quality, about 6.5 MB per 3-minute song."),
    ("320", "320 kbps constant", "Largest MP3 setting, about 7.2 MB per song. Sounds the same as V0 to almost everyone."),
    ("256", "256 kbps constant", "About 5.8 MB per song."),
    ("V2", "Smaller (VBR V2, ~190 kbps)", "Still very good, about 4.3 MB per song."),
    ("192", "192 kbps constant", "Smallest files here, about 4.3 MB per song."),
]
LOUDNESS_PRESETS = [
    (-16.0, "Quiet", "-16 LUFS: lots of headroom, like Apple Music"),
    (-14.0, "Standard", "-14 LUFS: Spotify / YouTube level"),
    (-11.0, "Loud", "-11 LUFS: louder, some quiet tracks get peak limiting"),
    (-9.0, "Club", "-9 LUFS: as loud as club masters, more limiting"),
]
SLIDER_MIN, SLIDER_MAX = -20.0, -6.0


class AudioPage(Page):
    def __init__(self, state: AppState) -> None:
        super().__init__("Audio", "How the MP3s sound and how big they are.")
        self._state = state

        quality = Card(
            "MP3 quality", "SoundCloud's best stream (256k AAC with Go+, or the original upload) is converted to:"
        )
        self.quality = OptionList(QUALITY_OPTIONS)
        self.quality.changed.connect(lambda q: state.update(quality=q))
        quality.body.addWidget(self.quality)
        self.body.addWidget(quality)
        self.body.addWidget(self._build_loudness())

        source = Card("Source")
        self.originals = QCheckBox("Use the artist's original upload when they allow downloads")
        self.originals.setToolTip("Often a WAV or 320k file - the best possible source. Uses one extra request per track.")
        self.originals.toggled.connect(lambda on: state.update(use_originals=on))
        self.previews = QCheckBox("Skip 30-second Go+ previews (recommended)")
        self.previews.setToolTip(
            "Without a Go+ login some tracks only offer a 30s clip. Skipping marks them failed instead."
        )
        self.previews.toggled.connect(lambda on: state.update(skip_previews=on))
        source.body.addWidget(self.originals)
        source.body.addWidget(self.previews)
        self.max_tracks = QSpinBox()
        self.max_tracks.setRange(0, 100000)
        self.max_tracks.setSpecialValueText("All")
        self.max_tracks.setFixedWidth(90)
        self.max_tracks.setToolTip("0 / All = every track. Likes and uploads are newest first, so 50 = your latest 50.")
        self.max_tracks.valueChanged.connect(lambda n: state.update(max_tracks=n))
        source.body.addLayout(hbox(label("Only download the first"), self.max_tracks, label("tracks of each link"), None))
        source.body.addWidget(label("Handy for likes: they're newest first, so 50 means your latest 50 likes.", "Hint"))
        self.body.addWidget(source)
        self.finish()

        state.settings_changed.connect(lambda _s: self._load())
        self._load()

    def _build_loudness(self) -> Card:
        card = Card(
            "Even out volume",
            "Measures every song and turns it up or down so they all play at the same loudness. "
            "It's a plain volume change done during the MP3 encode, so there's no extra quality loss.",
        )
        self.normalize = QCheckBox("Make all songs the same loudness")
        self.normalize.toggled.connect(lambda on: self._state.update(normalize=on))
        card.body.addWidget(self.normalize)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(int(SLIDER_MIN * 2), int(SLIDER_MAX * 2))  # half-LUFS steps
        self.slider.setPageStep(2)
        self.slider.valueChanged.connect(lambda v: self._state.update(target_lufs=v / 2))
        self.slider_value = label("", "CardTitle")
        self.slider_value.setMinimumWidth(90)
        card.body.addLayout(hbox(label("Quieter", "Hint"), self.slider, label("Louder", "Hint"), self.slider_value))

        self.preset_group = QButtonGroup(self)
        buttons = []
        for value, name, hint in LOUDNESS_PRESETS:
            button = QPushButton(name)
            button.setObjectName("Preset")
            button.setCheckable(True)
            button.setToolTip(hint)
            button.clicked.connect(lambda _=False, v=value: self._state.update(target_lufs=v))
            self.preset_group.addButton(button)
            buttons.append(button)
        self.preset_buttons = dict(zip([p[0] for p in LOUDNESS_PRESETS], buttons, strict=True))
        card.body.addLayout(hbox(*buttons, None))
        self.loudness_hint = label("", "Hint", wrap=True)
        card.body.addWidget(self.loudness_hint)
        return card

    def _load(self) -> None:
        s = self._state.settings
        self.quality.set_value(s.quality)
        checks = ((self.normalize, s.normalize), (self.originals, s.use_originals), (self.previews, s.skip_previews))
        for widget, value in checks:
            widget.blockSignals(True)
            widget.setChecked(value)
            widget.blockSignals(False)
        for widget, value in ((self.slider, int(round(s.target_lufs * 2))), (self.max_tracks, s.max_tracks)):
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)
        self.slider_value.setText(f"{s.target_lufs:g} LUFS")
        self.preset_group.setExclusive(False)
        for value, button in self.preset_buttons.items():
            button.setChecked(value == s.target_lufs)
        self.preset_group.setExclusive(True)
        for widget in (self.slider, *self.preset_buttons.values()):
            widget.setEnabled(s.normalize)
        match = next((hint for value, _n, hint in LOUDNESS_PRESETS if value == s.target_lufs), None)
        self.loudness_hint.setText(
            f"{match or f'{s.target_lufs:g} LUFS: custom level'}. "
            "Most dance tracks are mastered around -6 to -9 LUFS, so lower targets play quieter overall."
            if s.normalize else "Off: every song keeps the loudness it was uploaded with."
        )
