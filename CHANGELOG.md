# Changelog

## 1.1.0

- New **Playlists** page: follow playlists, likes or profiles, each with its own folder. The app checks them
  every 1-24 hours (your choice) and downloads tracks added since the last check. Checks wait while you're
  downloading something yourself, and while the library drive isn't connected. A check that fails (e.g.
  no internet after waking from sleep) is tried again after 15 minutes.
- The app can keep checking from the notification area when the window is closed, and start with Windows.
  Opening it again brings the running window forward instead of saying it's already open.
- Right-click links in the queue -> *Follow* to keep them up to date.
- YouTube matches: the list no longer jumps when a track's status changes, and the match you picked stays
  selected. Tracks you skip aren't asked about again by automatic checks.
- Works on any screen size: pages scroll instead of squashing, side panels move underneath on narrow
  windows, button rows wrap, the sidebar shows icons only below 1100 px, settings pages don't stretch across
  wide screens, and the window opens at a size that fits the screen (and back on screen if a monitor was
  removed).

## 1.0.3

- New Album tag setting (Account & tags): song title (new default), playlist name, or none. With the
  playlist name, iTunes showed one cover for every song in a playlist; with the song title each track
  shows its own cover. Existing settings keep their previous behaviour.
- 'Apply to MP3s already in my library' rewrites the Album tag of files you already have (tags only).
- Fix 'No album tag': yt-dlp's own playlist album/album-artist values were still written.

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
