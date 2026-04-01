# Kwon YouTube Web Downloader

Browser-based YouTube downloader built with `Flask`, `yt-dlp`, and local `ffmpeg`.

## What It Does

- Resolve one or many YouTube URLs with thumbnail, channel, duration, and detected stream info
- Download audio in:
  - `mp3`
  - `wav`
  - `m4a`
  - `flac`
  - `opus`
  - `aac`
- Choose audio quality presets from `64 kbps` to `320 kbps` plus `Best available`
- Download video in:
  - `mp4`
  - `mkv`
  - `webm`
- Choose max video quality from `360p` to `2160p` plus `Best available`
- Choose FPS preference: `24`, `30`, `60`, or `Best available`
- Extract a frame preview from a selected timestamp using the camera button in each analyzed card

## Run Locally

```powershell
cd C:\Users\kwonj\Pictures\kwon_downloader
py -3.12 -m venv .venv_web
.\.venv_web\Scripts\python -m pip install -r web_requirements.txt
.\.venv_web\Scripts\python web_app.py
```

Then open:

- `http://127.0.0.1:8000`

## Notes

- The app looks for local `ffmpeg` under `bin\ffmpeg.exe` by default.
- Downloaded files are stored in `web_downloads`.
- Frame previews are stored in `web_downloads\_frame_previews`.

## Key Files

- `web_app.py`
- `templates/web_downloader.html`
- `run_web.ps1`
- `web_requirements.txt`
