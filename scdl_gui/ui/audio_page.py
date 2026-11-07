"""Audio page: output format and quality, volume levelling and which SoundCloud source to use."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QButtonGroup, QCheckBox, QPushButton, QSlider, QSpinBox

from scdl_gui.formats import FORMATS, audio_format
from scdl_gui.ui.state import AppState
from scdl_gui.ui.widgets import Card, OptionList, Page, hbox, label

QUALITY_OPTIONS = [
    ("V0", "Best (VBR V0, ~245 kbps) - recommended", "Top LAME quality, about 6.5 MB per 3-minute song."),
    ("320", "320 kbps constant", "Largest MP3 setting, about 7.2 MB per song. Sounds the same as V0 to almost everyone."),
    ("256", "256 kbps constant", "About 5.8 MB per song."),
    ("V2", "Smaller (VBR V2, ~190 kbps)", "Still very good, about 4.3 MB per song."),
    ("192", "192 kbps constant", "Smallest files here, about 4.3 MB per song."),
]
AAC_OPTIONS = [
    (256, "256 kbps - recommended", "Same as SoundCloud Go+ and YouTube Premium streams, about 5.8 MB per 3-minute song."),
    (320, "320 kbps", "About 7.2 MB per song. No audible difference from 256 for almost everyone."),
    (192, "192 kbps", "About 4.3 MB per song."),
    (128, "128 kbps", "About 2.9 MB per song - fine for a phone with little space."),
]
OPUS_OPTIONS = [
    (160, "160 kbps - recommended", "Sounds the same as the source to almost everyone, about 3.6 MB per 3-minute song."),
    (256, "256 kbps", "About 5.8 MB per song."),
    (192, "192 kbps", "About 4.3 MB per song."),
    (128, "128 kbps", "About 2.9 MB per song - YouTube's own Opus is about this."),
    (96, "96 kbps", "About 2.2 MB per song, still good."),
]
QUALITY_TITLES = {"mp3": "MP3 quality", "m4a": "AAC quality", "opus": "Opus quality"}
LOUDNESS_PRESETS = [
    (-16.0, "Quiet", "-16 LUFS: lots of headroom, like Apple Music"),
    (-14.0, "Standard", "-14 LUFS: Spotify / YouTube level"),
    (-11.0, "Loud", "-11 LUFS: louder, some quiet tracks get peak limiting"),
    (-9.0, "Club", "-9 LUFS: as loud as club masters, more limiting"),
]
SLIDER_MIN, SLIDER_MAX = -20.0, -6.0


class AudioPage(Page):
    def __init__(self, state: AppState) -> None:
        super().__init__("Audio", "The file type, how it sounds and how big the files are.")
        self._state = state

        kind = Card(
            "Format",
            "Every song comes from the best stream there is: SoundCloud's (256k AAC with Go+, or the artist's "
            "original upload) or YouTube's (up to 256k with Premium). It's then saved as:",
        )
        self.format = OptionList([(f.key, f.label, f.hint) for f in FORMATS])
        self.format.changed.connect(lambda key: state.update(audio_format=key))
        kind.body.addWidget(self.format)
        self.body.addWidget(kind)
        self.body.addWidget(self._build_quality())
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

    def _build_quality(self) -> Card:
        self.quality_card = Card("Quality")
        self.quality = OptionList(QUALITY_OPTIONS)
        self.quality.changed.connect(lambda q: self._state.update(quality=q))
        self.aac = OptionList(AAC_OPTIONS)
        self.aac.changed.connect(lambda kbps: self._state.update(aac_bitrate=kbps))
        self.opus = OptionList(OPUS_OPTIONS)
        self.opus.changed.connect(lambda kbps: self._state.update(opus_bitrate=kbps))
        self._quality_lists = {"mp3": self.quality, "m4a": self.aac, "opus": self.opus}
        for options in self._quality_lists.values():
            self.quality_card.body.addWidget(options)
        self.copy_note = label("", "Hint", wrap=True)
        self.quality_card.body.addWidget(self.copy_note)
        return self.quality_card

    def _show_quality(self, key: str) -> None:
        """Only the chosen format's choices; lossless and "no conversion" have none, so no card."""
        for fmt, options in self._quality_lists.items():
            options.setVisible(fmt == key)
        self.quality_card.setVisible(key in self._quality_lists)
        self.quality_card.title.setText(QUALITY_TITLES.get(key, "Quality"))
        codec = {"m4a": "AAC", "opus": "Opus"}.get(key)
        self.copy_note.setVisible(codec is not None)
        if codec:
            self.copy_note.setText(
                f"Used when the audio has to be converted - always with volume levelling on. With it off, a stream "
                f"that's already {codec} is kept exactly as it is: no re-encode, nothing lost."
            )

    def _build_loudness(self) -> Card:
        card = Card(
            "Even out volume",
            "Measures every song and turns it up or down so they all play at the same loudness. "
            "It's a plain volume change done while the file is encoded, so there's no extra quality loss.",
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
        fmt = audio_format(s.audio_format)
        self.format.set_value(fmt.key)
        self.quality.set_value(s.quality)
        self.aac.set_value(s.aac_bitrate)
        self.opus.set_value(s.opus_bitrate)
        self._show_quality(fmt.key)
        self.normalize.setEnabled(fmt.converts)
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
        levelling = s.normalize and fmt.converts
        for widget in (self.slider, *self.preset_buttons.values()):
            widget.setEnabled(levelling)
        match = next((hint for value, _n, hint in LOUDNESS_PRESETS if value == s.target_lufs), None)
        self.loudness_hint.setText(
            f"{match or f'{s.target_lufs:g} LUFS: custom level'}. "
            "Most dance tracks are mastered around -6 to -9 LUFS, so lower targets play quieter overall."
            if levelling else "Off: every song keeps the loudness it was uploaded with."
        )
        if not fmt.converts:
            self.loudness_hint.setText("Not with 'no conversion': changing the volume means re-encoding the audio.")
