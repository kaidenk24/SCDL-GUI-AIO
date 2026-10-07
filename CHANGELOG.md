# Changelog

## 1.0.2

- Fix in-app updates: after "Update now" the app closed but didn't reopen, and a blank console window
  (`find`) stayed open. The downloaded version now installs itself directly - no script, no console -
  waits for the old version to close, copies itself in (retrying briefly locked files) and restarts.
- Remove leftover update downloads (~60 MB each) on startup.
- Updating from 1.0.0/1.0.1 still uses their old updater: if the blank window appears, close it and
  download 1.0.2 from the Releases page once.

## 1.0.1

- Fix DRM-protected tracks failing with "'charmap' codec can't encode character" instead of going to
  YouTube matches, when the folder or track name had characters like `⧸` (packaged app only).
- Fix garbled track names in the Activity log of the packaged app (e.g. `SATØS`, `⧸`, or a track
  shown as "uff0a"). Downloaded files were always named correctly; only the display was affected.

## 1.0.0

First public release.

- Download SoundCloud playlists, albums, likes, profiles, stations, tracks and share links as tagged MP3s.
- Folder layouts and file names from tokens, with a live preview; custom folders per link (drag and drop).
- MP3 quality choice, EBU R128 loudness levelling, original uploads, Go+ via your browser login.
- Shared or per-link download archives so tracks are never downloaded twice.
- DRM-protected tracks: YouTube matches you confirm before anything is downloaded.
- One-click automatic PO tokens (bgutil-ytdlp-pot-provider, downloaded on demand) so YouTube Music Premium
  accounts get 256k AAC / 282k Opus; the generator updates itself daily.
- Rate-limit friendly: fewer API requests per track, pacing, and automatic waiting on HTTP 429.
- Update checks and in-place updates; one-click FFmpeg/Node.js installs; Start menu/desktop shortcuts.
