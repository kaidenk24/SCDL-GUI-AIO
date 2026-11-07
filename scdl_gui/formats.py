"""Output audio formats: what the Audio page offers and how the worker makes each one. No Qt in here."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AudioFormat:
    key: str
    label: str
    hint: str
    ext: str  # "" = whatever the source is (no conversion)
    extract_codec: str  # yt-dlp FFmpegExtractAudio preferredcodec
    source_codec: str = ""  # prefer sources already in this codec: no re-encode when levelling is off
    lossless: bool = False

    @property
    def converts(self) -> bool:
        return bool(self.ext)


FORMATS = (
    AudioFormat("mp3", "MP3", "Plays everywhere: every phone, car, iTunes and old MP3 player.", "mp3", "mp3"),
    AudioFormat("m4a", "AAC (.m4a)", "Same quality as MP3 in smaller files; plays in iTunes, phones and most cars. "
                "SoundCloud's best stream is AAC, so it's kept as it is when volume levelling is off.",
                "m4a", "m4a", source_codec="mp4a"),
    AudioFormat("opus", "Opus", "Best sound for the size, but iTunes and many cars can't play it. "
                "YouTube's own audio is Opus, so it's kept as it is when volume levelling is off.",
                "opus", "opus", source_codec="opus"),
    AudioFormat("flac", "FLAC (lossless)", "Keeps every bit of the source - only better than the others for "
                "lossless original uploads; for streamed audio it's just ~4x bigger files.", "flac", "flac",
                lossless=True),
    AudioFormat("wav", "WAV (uncompressed)", "Like FLAC but twice as big and with weaker tag support. For DJ "
                "software that needs WAV.", "wav", "wav", lossless=True),
    AudioFormat("original", "Best available - no conversion", "Saves exactly what SoundCloud or YouTube sends "
                "(usually AAC .m4a or Opus), so nothing is lost to re-encoding. Volume levelling isn't "
                "possible without converting.", "", "best"),
)
BY_KEY = {f.key: f for f in FORMATS}
DEFAULT_FORMAT = "mp3"

MP3_QUALITIES = ("V0", "320", "256", "V2", "192")
AAC_BITRATES = (320, 256, 192, 128)
OPUS_BITRATES = (256, 192, 160, 128, 96)
OPUS_SAMPLE_RATE = "48000"  # the only full-band rate libopus takes


def audio_format(key: str) -> AudioFormat:
    return BY_KEY.get(key, BY_KEY[DEFAULT_FORMAT])


def encoder_args(fmt: AudioFormat, mp3_quality: str, bitrate: int) -> list[str]:
    """FFmpeg arguments that encode to `fmt` (for the loudness-levelling encode)."""
    if fmt.key == "mp3":
        quality = mp3_quality.upper()
        return ["-c:a", "libmp3lame", *(["-q:a", quality[1:]] if quality.startswith("V") else ["-b:a", f"{quality}k"])]
    if fmt.key == "m4a":
        return ["-c:a", "aac", "-b:a", f"{bitrate}k"]
    if fmt.key == "opus":
        return ["-c:a", "libopus", "-b:a", f"{bitrate}k"]
    if fmt.key == "flac":
        return ["-c:a", "flac", "-sample_fmt", "s16"]
    if fmt.key == "wav":
        return ["-c:a", "pcm_s16le"]
    raise ValueError(f"{fmt.key} isn't converted")


def extract_quality(fmt: AudioFormat, mp3_quality: str, bitrate: int) -> str | None:
    """FFmpegExtractAudio's preferredquality (no levelling): VBR level 0-9, or kbps."""
    if fmt.key == "mp3":
        quality = mp3_quality.upper()
        return quality[1:] if quality.startswith("V") else quality
    if fmt.key in ("m4a", "opus"):
        return str(bitrate)
    return None


def source_format(fmt: AudioFormat, levelling: bool) -> str:
    """yt-dlp format selection: the best audio, but when the result won't be re-encoded anyway, the best
    stream already in the target codec - e.g. YouTube's AAC for .m4a - so it's only repackaged."""
    if fmt.source_codec and not levelling:
        return f"bestaudio[acodec^={fmt.source_codec}]/bestaudio/best"
    return "bestaudio/best"
