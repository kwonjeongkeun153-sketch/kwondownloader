# Web Downloader

`yt-dlp` + local `ffmpeg` based web UI for YouTube downloads.

## Run

```powershell
cd C:\Users\kwonj\Pictures\kwon_downloader
py -3.12 -m venv .venv_web
.\.venv_web\Scripts\python -m pip install -r web_requirements.txt
.\.venv_web\Scripts\python web_app.py
```

Open:

- PC: `http://127.0.0.1:8000`
- Same Wi-Fi phone/tablet: `http://<PC_IP>:8000`

## Features

- Multi URL resolve with title, channel, duration, thumbnail, and detected format info
- Audio download options:
  - `mp3`, `wav`, `m4a`, `flac`, `opus`, `aac`
  - bitrate presets from `64 kbps` to `320 kbps`, plus `Best available`
- Video download options:
  - containers: `mp4`, `mkv`, `webm`
  - max quality: `360p` to `2160p`, plus `Best available`
  - FPS preference: `24`, `30`, `60`, or `Best available`
- Frame extraction preview:
  - enter a time like `15`, `01:20`, or `00:01:20`
  - click the camera button on a resolved card
  - preview image is generated through `ffmpeg`
- Downloaded files are saved to:
  - `C:\Users\kwonj\Pictures\kwon_downloader\web_downloads`

## Notes

- Local `bin\ffmpeg.exe` is used automatically when found.
- Frame previews are stored under:
  - `C:\Users\kwonj\Pictures\kwon_downloader\web_downloads\_frame_previews`
- If a source does not provide the exact requested quality/FPS, the closest available stream is selected.
