# AutoSub

A lightweight PyQt6 + VLC media player that automatically downloads subtitles for your videos. Drop a video in, and it fetches matching subtitles from OpenSubtitles (by file hash or cleaned title). If nothing is found online, it falls back to local Whisper transcription. It now also supports a simple "Watch Together" mode for syncing playback with someone on a different network.

## Features

- **VLC playback** with pastel pink PyQt6 UI
- **Drag-and-drop** — drop videos to auto-play and auto-download subtitles
- **OpenSubtitles REST API** — hash-based search first (exact file match), then cleaned-title text search
- **Whisper fallback** — local transcription via `large-v3` when no online subtitles exist
- **Language switching** — dropdown to pick language (English/Turkish); switching loads already-downloaded subtitles instantly
- **Parallel downloads** — up to 2 concurrent subtitle downloads with visible queue
- **Playlist** — checkable items, select-all toggle, double-click to play, auto-advance
- **Fullscreen** — press `F` for edge-to-edge video, `Esc` to exit
- **Keyboard shortcuts** — Space: play/pause, Arrows: seek ±5s, F: fullscreen, Esc: exit fullscreen
- **Watch Together sync** — connect both players to the same room and mirror `load/play/pause/seek/stop`

## Requirements

- macOS (tested on Apple Silicon), Linux, or Windows
- Python 3.10+
- VLC installed (arm64 VLC on Apple Silicon)
- ffmpeg on PATH (needed for Whisper fallback)

## Setup

```bash
uv sync
```

## Run

```bash
cp .env.example .env   # fill in your credentials
source .env && uv run python main.py
```

## Watch Together Server

For internet-wide sync, run the tiny relay server on a machine that both sides can reach:

```bash
python3 watch_sync_server.py
```

By default it listens on `http://0.0.0.0:8765`.

If you want to use it outside your home network, deploy it to a public VPS, Render, Fly.io, Railway, or another host and enter that public URL into the app's "Server" field.

## Usage

1. **Add videos** — drag files into the window or click "Add Videos"
2. Subtitles download automatically for each added video in the selected language
3. **Switch language** — change the dropdown to load a different subtitle track (if already downloaded) or click "Download Subs" to fetch it
4. **Fullscreen** — press `F`; press `Esc` to exit
5. **Watch Together**:
   - run `watch_sync_server.py` somewhere both people can reach
   - enter the same server URL and room code on both machines
   - each person adds the same local video file
   - pressing play/pause/seek on one side updates the other side

## Do We Need a Server?

Yes, if you are not on the same network and want this to work reliably over the internet, you need some publicly reachable coordination point.

This project's server is intentionally small: it does not stream the movie and it does not transfer subtitle files. It only relays room membership and playback events.

That means:

- you do **not** need a heavy media streaming backend for this feature
- you **do** need a tiny relay server so both apps can find the same room
- both sides still need access to the same movie file locally

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPENSUBTITLES_API_KEY` | Yes | Your OpenSubtitles API key |
| `OPENSUBTITLES_USERNAME` | Yes | OpenSubtitles username |
| `OPENSUBTITLES_PASSWORD` | Yes | OpenSubtitles password |

Copy `.env.example` to `.env` and fill in your credentials.

## Dependencies

- PyQt6
- python-vlc
- openai-whisper
- requests

## Troubleshooting

- **VLC arch mismatch on Apple Silicon** — install arm64 VLC
- **Missing ffmpeg** — `brew install ffmpeg`
- **Quota exhausted** — OpenSubtitles free tier has a daily download limit; the status bar shows when it resets
- **Watch sync not working over the internet** — make sure your sync server is publicly reachable and both players use the same room code
