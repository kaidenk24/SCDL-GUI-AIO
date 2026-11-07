# Changelog

## 1.2.0

- **YouTube links**: paste YouTube or YouTube Music videos, playlists and channels into the queue, or follow
  YouTube playlists and channels on the Playlists page. Same folders, file names, archive, levelling and tags as
  SoundCloud links; YouTube's best stream (256k with Premium + PO tokens). If your YouTube login can't be read,
  it downloads without it instead of failing.
- **Output formats** (Audio page): MP3, AAC (.m4a), Opus, FLAC, WAV, or *Best available - no conversion*, with
  bitrate choices for AAC and Opus. Volume levelling encodes straight to the chosen format.
- No needless re-encoding: with levelling off, a stream already in the chosen format (SoundCloud's AAC for .m4a,
  YouTube's AAC/Opus) is only repackaged - faster, and no quality lost.
- YouTube matches for DRM-protected tracks are saved in the chosen format, tagged the same way.
- *Apply to songs already in my library* (Album tag) now handles M4A, FLAC, Opus and WAV as well as MP3.

## 1.1.3

- YouTube matches: select several tracks (Ctrl/Shift-click, Ctrl+A or *Select all*) and *Remove* them
  from the list (also the Delete key or right-click). Like skipping, automatic checks of followed playlists
  don't add removed tracks back; downloading the playlist yourself does.

## 1.1.2

- Fix tracks failing with `'__real_download'` when the MP3 was already in the folder but not in the
  download archive (e.g. the first check of a followed playlist into a folder you'd downloaded before).
  Such tracks were also re-encoded on every check; now they're left untouched, counted as already had,
  and added to the archive so later checks skip them straight away.

## 1.1.1

- YouTube matches are found about 8x faster (a batch of 3 tracks: 95 s -> 11 s; the first result in
  5 s instead of 29 s). The YouTube Music search fetched ~350 results to use 3; searching no longer
  reads your browser login or makes PO tokens (only downloads need them); both searches and the
  per-result lookups now run at the same time.
- *Search again*, and a track you select that's still waiting to be searched, no longer wait behind
  the other tracks being searched. An older search's results can't replace a newer one's.

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
