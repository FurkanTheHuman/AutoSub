# AutoSub

A lightweight PyQt6 + VLC media player that automatically downloads subtitles for your videos. Drop a video in, and it fetches matching subtitles from OpenSubtitles (by file hash or cleaned title). If nothing is found online, it falls back to local Whisper transcription.

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

## Usage

1. **Add videos** — drag files into the window or click "Add Videos"
2. Subtitles download automatically for each added video in the selected language
3. **Switch language** — change the dropdown to load a different subtitle track (if already downloaded) or click "Download Subs" to fetch it
4. **Fullscreen** — press `F`; press `Esc` to exit

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
