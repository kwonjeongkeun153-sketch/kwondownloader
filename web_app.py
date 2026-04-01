from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote

from flask import Flask, jsonify, render_template, request, send_file


BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = BASE_DIR / "web_downloads"
PREVIEW_DIR = DOWNLOAD_DIR / "_frame_previews"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
PREVIEW_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__, template_folder=str(BASE_DIR / "templates"))

AUDIO_FORMATS = [
    {
        "value": "mp3",
        "label": "MP3",
        "note": "Portable and widely supported.",
    },
    {
        "value": "wav",
        "label": "WAV",
        "note": "Large uncompressed audio for editing.",
    },
    {
        "value": "m4a",
        "label": "M4A",
        "note": "Compact AAC container with good compatibility.",
    },
    {
        "value": "flac",
        "label": "FLAC",
        "note": "Lossless archive quality.",
    },
    {
        "value": "opus",
        "label": "OPUS",
        "note": "Efficient modern streaming codec.",
    },
    {
        "value": "aac",
        "label": "AAC",
        "note": "Good mobile and Apple device support.",
    },
]

AUDIO_QUALITIES = [
    {"value": "64", "label": "64 kbps"},
    {"value": "96", "label": "96 kbps"},
    {"value": "128", "label": "128 kbps"},
    {"value": "192", "label": "192 kbps"},
    {"value": "256", "label": "256 kbps"},
    {"value": "320", "label": "320 kbps"},
    {"value": "0", "label": "Best available"},
]

VIDEO_CONTAINERS = [
    {
        "value": "mp4",
        "label": "MP4",
        "note": "Best default for compatibility.",
    },
    {
        "value": "mkv",
        "label": "MKV",
        "note": "Flexible container for mixed sources.",
    },
    {
        "value": "webm",
        "label": "WEBM",
        "note": "Good for VP9 and browser-centric workflows.",
    },
]

VIDEO_QUALITIES = [
    {"value": "360", "label": "360p"},
    {"value": "480", "label": "480p"},
    {"value": "720", "label": "720p HD"},
    {"value": "1080", "label": "1080p Full HD"},
    {"value": "1440", "label": "1440p 2K"},
    {"value": "2160", "label": "2160p 4K"},
    {"value": "best", "label": "Best available"},
]

VIDEO_FPS = [
    {"value": "24", "label": "24 fps"},
    {"value": "30", "label": "30 fps"},
    {"value": "60", "label": "60 fps"},
    {"value": "best", "label": "Best available"},
]

DEFAULT_AUDIO_FORMAT = "mp3"
DEFAULT_AUDIO_QUALITY = "320"
DEFAULT_VIDEO_CONTAINER = "mp4"
DEFAULT_VIDEO_QUALITY = "1080"
DEFAULT_VIDEO_FPS = "60"

AUDIO_FORMAT_VALUES = {item["value"] for item in AUDIO_FORMATS}
AUDIO_QUALITY_VALUES = {item["value"] for item in AUDIO_QUALITIES}
VIDEO_CONTAINER_VALUES = {item["value"] for item in VIDEO_CONTAINERS}
VIDEO_QUALITY_VALUES = {item["value"] for item in VIDEO_QUALITIES}
VIDEO_FPS_VALUES = {item["value"] for item in VIDEO_FPS}


def _find_binary(executable_name: str) -> Path | None:
    candidates = [
        BASE_DIR / "bin" / executable_name,
        BASE_DIR / "third_party" / "ffmpeg" / "bin" / executable_name,
    ]
    candidates.extend(BASE_DIR.glob(f"*/third_party/ffmpeg/bin/{executable_name}"))
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()

    system_path = shutil.which(executable_name)
    if system_path:
        return Path(system_path).resolve()
    return None


FFMPEG_PATH = _find_binary("ffmpeg.exe" if sys.platform.startswith("win") else "ffmpeg")
FFMPEG_DIR = str(FFMPEG_PATH.parent) if FFMPEG_PATH else None


@contextmanager
def _hidden_console_processes():
    if sys.platform != "win32":
        yield
        return

    original_popen = subprocess.Popen
    create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    startf_use_showwindow = getattr(subprocess, "STARTF_USESHOWWINDOW", 0x00000001)
    sw_hide = getattr(subprocess, "SW_HIDE", 0)

    def patched_popen(*args: Any, **kwargs: Any) -> Any:
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | create_no_window

        startupinfo = kwargs.get("startupinfo")
        if startupinfo is None:
            startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= startf_use_showwindow
        startupinfo.wShowWindow = sw_hide
        kwargs["startupinfo"] = startupinfo

        return original_popen(*args, **kwargs)

    subprocess.Popen = patched_popen  # type: ignore[assignment]
    try:
        yield
    finally:
        subprocess.Popen = original_popen  # type: ignore[assignment]


def _subprocess_run_kwargs() -> dict[str, Any]:
    if sys.platform != "win32":
        return {}

    create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    startf_use_showwindow = getattr(subprocess, "STARTF_USESHOWWINDOW", 0x00000001)
    sw_hide = getattr(subprocess, "SW_HIDE", 0)

    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= startf_use_showwindow
    startupinfo.wShowWindow = sw_hide
    return {
        "creationflags": create_no_window,
        "startupinfo": startupinfo,
    }


def _normalize_urls(raw_urls: Any) -> list[str]:
    if not isinstance(raw_urls, list):
        return []

    cleaned: list[str] = []
    seen: set[str] = set()
    for item in raw_urls:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        cleaned.append(value)
    return cleaned


def _snapshot_downloads() -> set[str]:
    return {
        str(path.resolve())
        for path in DOWNLOAD_DIR.iterdir()
        if path.is_file()
    }


def _pick_info_entry(info: Any) -> dict[str, Any]:
    if isinstance(info, dict) and info.get("_type") == "playlist":
        entries = info.get("entries") or []
        for entry in entries:
            if isinstance(entry, dict):
                return entry
    return info if isinstance(info, dict) else {}


def _extract_thumbnail(info: dict[str, Any]) -> str | None:
    thumb = info.get("thumbnail")
    if isinstance(thumb, str) and thumb:
        return thumb

    thumbnails = info.get("thumbnails") or []
    for item in reversed(thumbnails):
        if not isinstance(item, dict):
            continue
        value = item.get("url")
        if isinstance(value, str) and value:
            return value
    return None


def _format_duration(seconds: Any) -> str:
    try:
        total_seconds = int(float(seconds))
    except (TypeError, ValueError):
        return "--:--"

    hours, remainder = divmod(max(total_seconds, 0), 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _seconds_to_timestamp(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _default_frame_seconds(duration_seconds: int | float | None) -> float:
    try:
        duration = float(duration_seconds or 0)
    except (TypeError, ValueError):
        return 15.0

    if duration <= 0:
        return 15.0
    if duration <= 20:
        return max(1.0, duration / 2.0)
    return min(max(duration * 0.18, 6.0), 45.0)


def _parse_timestamp(value: Any, fallback_seconds: float) -> float:
    text = str(value or "").strip()
    if not text:
        return fallback_seconds

    if text.isdigit():
        return max(0.0, float(text))

    parts = text.split(":")
    if not 1 <= len(parts) <= 3:
        raise ValueError("Timestamp must be seconds or HH:MM:SS.")

    try:
        numbers = [float(part) for part in parts]
    except ValueError as exc:
        raise ValueError("Timestamp contains non-numeric parts.") from exc

    if len(numbers) == 1:
        return max(0.0, numbers[0])
    if len(numbers) == 2:
        minutes, seconds = numbers
        return max(0.0, minutes * 60 + seconds)

    hours, minutes, seconds = numbers
    return max(0.0, hours * 3600 + minutes * 60 + seconds)


def _summarize_formats(info: dict[str, Any]) -> dict[str, Any]:
    heights: set[int] = set()
    fps_values: set[int] = set()
    audio_exts: set[str] = set()
    video_exts: set[str] = set()

    for item in info.get("formats") or []:
        if not isinstance(item, dict):
            continue

        ext = str(item.get("ext") or "").lower()
        if item.get("vcodec") not in (None, "none"):
            if isinstance(item.get("height"), int):
                heights.add(int(item["height"]))
            if isinstance(item.get("fps"), (int, float)):
                fps_values.add(int(item["fps"]))
            if ext:
                video_exts.add(ext)

        if item.get("acodec") not in (None, "none") and ext:
            audio_exts.add(ext)

    return {
        "video_qualities": [f"{value}p" for value in sorted(heights)],
        "fps": sorted(fps_values),
        "video_exts": sorted(video_exts),
        "audio_exts": sorted(audio_exts),
    }


def _build_audio_selector(audio_format: str) -> str:
    if audio_format in {"aac", "m4a"}:
        return "bestaudio[ext=m4a]/bestaudio/best"
    if audio_format == "opus":
        return "bestaudio[acodec^=opus]/bestaudio/best"
    return "bestaudio/best"


def _build_audio_quality(audio_format: str, audio_quality: str) -> str:
    if audio_format in {"wav", "flac"}:
        return "0"
    return audio_quality


def _build_video_selector(container: str, quality: str, fps: str) -> str:
    filters = ""
    if quality != "best":
        filters += f"[height<={quality}]"
    if fps != "best":
        filters += f"[fps<={fps}]"

    if container == "mp4":
        return (
            f"bv*[ext=mp4]{filters}+ba[ext=m4a]/"
            f"b[ext=mp4]{filters}/"
            f"bv*{filters}+ba/b"
        )
    if container == "webm":
        return (
            f"bv*[ext=webm]{filters}+ba[ext=webm]/"
            f"b[ext=webm]{filters}/"
            f"bv*{filters}+ba/b"
        )
    return f"bv*{filters}+ba/b"


def _make_download_options(
    *,
    mode: str,
    audio_format: str,
    audio_quality: str,
    video_container: str,
    video_quality: str,
    video_fps: str,
) -> dict[str, Any]:
    outtmpl = str(DOWNLOAD_DIR / "%(title).180s [%(id)s].%(ext)s")
    options: dict[str, Any] = {
        "outtmpl": outtmpl,
        "noplaylist": True,
        "forceipv4": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }
    if FFMPEG_DIR:
        options["ffmpeg_location"] = FFMPEG_DIR

    if mode == "audio":
        options["format"] = _build_audio_selector(audio_format)
        if not FFMPEG_DIR:
            raise RuntimeError("ffmpeg was not found, so audio conversion is unavailable.")
        options["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": audio_format,
                "preferredquality": _build_audio_quality(audio_format, audio_quality),
            }
        ]
    else:
        options["format"] = _build_video_selector(video_container, video_quality, video_fps)
        if video_container in {"mp4", "mkv", "webm"}:
            options["merge_output_format"] = video_container

    return options


def _download_one(
    *,
    url: str,
    mode: str,
    audio_format: str,
    audio_quality: str,
    video_container: str,
    video_quality: str,
    video_fps: str,
) -> tuple[list[str], str | None]:
    import yt_dlp

    before = _snapshot_downloads()
    try:
        options = _make_download_options(
            mode=mode,
            audio_format=audio_format,
            audio_quality=audio_quality,
            video_container=video_container,
            video_quality=video_quality,
            video_fps=video_fps,
        )
    except RuntimeError as exc:
        return [], str(exc)

    try:
        with _hidden_console_processes():
            with yt_dlp.YoutubeDL(options) as ydl:
                ydl.download([url])
    except Exception as exc:  # noqa: BLE001
        return [], str(exc)

    after = _snapshot_downloads()
    return sorted(after - before), None


def _resolve_url_info(urls: list[str]) -> dict[str, Any]:
    import yt_dlp

    items: list[dict[str, Any]] = []
    errors: list[str] = []

    with _hidden_console_processes():
        for url in urls:
            options = {
                "quiet": True,
                "no_warnings": True,
                "noprogress": True,
                "skip_download": True,
                "noplaylist": True,
                "forceipv4": True,
            }
            try:
                with yt_dlp.YoutubeDL(options) as ydl:
                    info = ydl.extract_info(url, download=False)
                current = _pick_info_entry(info)
                duration_seconds = int(current.get("duration") or 0)
                summary = _summarize_formats(current)
                items.append(
                    {
                        "url": url,
                        "video_id": str(current.get("id") or ""),
                        "title": str(current.get("title") or url),
                        "channel": str(current.get("channel") or current.get("uploader") or ""),
                        "thumbnail": _extract_thumbnail(current),
                        "duration_seconds": duration_seconds,
                        "duration_text": _format_duration(duration_seconds),
                        "default_frame_time": _seconds_to_timestamp(
                            _default_frame_seconds(duration_seconds)
                        ),
                        "format_summary": summary,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{url}: {exc}")
                items.append(
                    {
                        "url": url,
                        "title": url,
                        "thumbnail": None,
                        "channel": "",
                        "duration_seconds": 0,
                        "duration_text": "--:--",
                        "default_frame_time": "00:15",
                        "format_summary": {
                            "video_qualities": [],
                            "fps": [],
                            "video_exts": [],
                            "audio_exts": [],
                        },
                        "error": str(exc),
                    }
                )

    return {"items": items, "errors": errors}


def _build_ffmpeg_headers(headers: dict[str, Any]) -> str:
    lines: list[str] = []
    for key, value in headers.items():
        key_text = str(key or "").strip()
        value_text = str(value or "").strip()
        if not key_text or not value_text:
            continue
        lines.append(f"{key_text}: {value_text}")
    if not lines:
        return ""
    return "\r\n".join(lines) + "\r\n"


def _pick_frame_candidate(info: dict[str, Any]) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for item in info.get("formats") or []:
        if not isinstance(item, dict):
            continue
        if item.get("vcodec") in (None, "none"):
            continue
        if not item.get("url"):
            continue
        candidates.append(item)

    if not candidates:
        return None

    def key(item: dict[str, Any]) -> tuple[int, int, int, int, int]:
        protocol = str(item.get("protocol") or "")
        ext = str(item.get("ext") or "").lower()
        protocol_score = 2 if protocol in {"https", "http"} else 1 if "m3u8" in protocol else 0
        ext_score = {"mp4": 3, "m4v": 2, "webm": 1}.get(ext, 0)
        return (
            int(item.get("height") or 0),
            int(item.get("fps") or 0),
            int(item.get("tbr") or 0),
            ext_score,
            protocol_score,
        )

    return sorted(candidates, key=key, reverse=True)[0]


def _extract_frame_preview(url: str, timestamp_value: Any) -> tuple[dict[str, Any] | None, str | None]:
    import yt_dlp

    if not FFMPEG_PATH:
        return None, "ffmpeg was not found, so frame extraction is unavailable."

    options = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "skip_download": True,
        "noplaylist": True,
        "forceipv4": True,
    }

    with _hidden_console_processes():
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as exc:  # noqa: BLE001
            return None, str(exc)

    current = _pick_info_entry(info)
    duration_seconds = int(current.get("duration") or 0)
    fallback_seconds = _default_frame_seconds(duration_seconds)
    try:
        target_seconds = _parse_timestamp(timestamp_value, fallback_seconds)
    except ValueError as exc:
        return None, str(exc)

    if duration_seconds > 0:
        target_seconds = min(target_seconds, max(duration_seconds - 1, 0))

    candidate = _pick_frame_candidate(current)
    if not candidate:
        return None, "No video stream was available for frame extraction."

    video_id = str(current.get("id") or hashlib.sha1(url.encode("utf-8")).hexdigest()[:16])
    preview_name = f"{video_id}_{int(target_seconds * 1000):08d}.jpg"
    preview_path = PREVIEW_DIR / preview_name

    if not preview_path.exists():
        headers = _build_ffmpeg_headers(current.get("http_headers") or {})
        command = [
            str(FFMPEG_PATH),
            "-hide_banner",
            "-loglevel",
            "error",
        ]
        if headers:
            command.extend(["-headers", headers])
        command.extend(
            [
                "-ss",
                f"{target_seconds:.3f}",
                "-i",
                str(candidate["url"]),
                "-frames:v",
                "1",
                "-q:v",
                "2",
                "-y",
                str(preview_path),
            ]
        )

        try:
            subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                **_subprocess_run_kwargs(),
            )
        except subprocess.CalledProcessError as exc:
            details = exc.stderr.strip() or exc.stdout.strip() or "ffmpeg failed"
            return None, details

    return (
        {
            "preview_id": preview_name,
            "preview_url": f"/api/preview-file?id={quote(preview_name)}",
            "title": str(current.get("title") or url),
            "timestamp": _seconds_to_timestamp(target_seconds),
        },
        None,
    )


def _safe_child_path(root: Path, child_name: str) -> Path | None:
    target = (root / child_name).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return None
    if not target.is_file():
        return None
    return target


@app.get("/")
def index():
    return render_template("web_downloader.html")


@app.get("/api/options")
def api_options():
    return jsonify(
        {
            "ok": True,
            "audio_formats": AUDIO_FORMATS,
            "audio_qualities": AUDIO_QUALITIES,
            "video_containers": VIDEO_CONTAINERS,
            "video_qualities": VIDEO_QUALITIES,
            "video_fps": VIDEO_FPS,
            "defaults": {
                "mode": "audio",
                "audio_format": DEFAULT_AUDIO_FORMAT,
                "audio_quality": DEFAULT_AUDIO_QUALITY,
                "video_container": DEFAULT_VIDEO_CONTAINER,
                "video_quality": DEFAULT_VIDEO_QUALITY,
                "video_fps": DEFAULT_VIDEO_FPS,
            },
        }
    )


@app.post("/api/resolve")
def api_resolve():
    payload = request.get_json(silent=True) or {}
    urls = _normalize_urls(payload.get("urls") or [])
    if not urls:
        return jsonify({"ok": False, "message": "No URLs provided."}), 400

    result = _resolve_url_info(urls)
    return jsonify({"ok": True, **result})


@app.post("/api/frame-preview")
def api_frame_preview():
    payload = request.get_json(silent=True) or {}
    url = str(payload.get("url") or "").strip()
    timestamp = payload.get("timestamp")

    if not url:
        return jsonify({"ok": False, "message": "No URL provided."}), 400

    preview, error = _extract_frame_preview(url, timestamp)
    if error:
        return jsonify({"ok": False, "message": error}), 400

    return jsonify({"ok": True, **preview})


@app.post("/api/download")
def api_download():
    payload = request.get_json(silent=True) or {}
    urls = _normalize_urls(payload.get("urls") or [])
    mode = str(payload.get("mode") or "audio").lower()
    audio_format = str(payload.get("audio_format") or DEFAULT_AUDIO_FORMAT).lower()
    audio_quality = str(payload.get("audio_quality") or DEFAULT_AUDIO_QUALITY)
    video_container = str(payload.get("video_container") or DEFAULT_VIDEO_CONTAINER).lower()
    video_quality = str(payload.get("video_quality") or DEFAULT_VIDEO_QUALITY).lower()
    video_fps = str(payload.get("video_fps") or DEFAULT_VIDEO_FPS).lower()

    if not urls:
        return jsonify({"ok": False, "message": "No URLs provided."}), 400
    if mode not in {"audio", "video"}:
        return jsonify({"ok": False, "message": "Invalid mode."}), 400
    if audio_format not in AUDIO_FORMAT_VALUES:
        return jsonify({"ok": False, "message": "Invalid audio format."}), 400
    if audio_quality not in AUDIO_QUALITY_VALUES:
        return jsonify({"ok": False, "message": "Invalid audio quality."}), 400
    if video_container not in VIDEO_CONTAINER_VALUES:
        return jsonify({"ok": False, "message": "Invalid video container."}), 400
    if video_quality not in VIDEO_QUALITY_VALUES:
        return jsonify({"ok": False, "message": "Invalid video quality."}), 400
    if video_fps not in VIDEO_FPS_VALUES:
        return jsonify({"ok": False, "message": "Invalid video FPS preference."}), 400

    files: list[dict[str, str]] = []
    errors: list[str] = []

    for url in urls:
        downloaded, error = _download_one(
            url=url,
            mode=mode,
            audio_format=audio_format,
            audio_quality=audio_quality,
            video_container=video_container,
            video_quality=video_quality,
            video_fps=video_fps,
        )
        if error:
            errors.append(f"{url}: {error}")
            continue

        for item in downloaded:
            path = Path(item).resolve()
            file_id = path.relative_to(DOWNLOAD_DIR.resolve()).as_posix()
            files.append(
                {
                    "name": path.name,
                    "id": file_id,
                    "url": f"/api/file?id={quote(file_id)}",
                }
            )

    return jsonify(
        {
            "ok": True,
            "mode": mode,
            "count": len(files),
            "files": files,
            "errors": errors,
            "ffmpeg_found": bool(FFMPEG_DIR),
            "selected_options": {
                "audio_format": audio_format,
                "audio_quality": audio_quality,
                "video_container": video_container,
                "video_quality": video_quality,
                "video_fps": video_fps,
            },
        }
    )


@app.get("/api/file")
def api_file():
    file_id = request.args.get("id", "")
    target = _safe_child_path(DOWNLOAD_DIR, file_id)
    if not target:
        return jsonify({"ok": False, "message": "File not found."}), 404
    return send_file(target, as_attachment=True, download_name=target.name)


@app.get("/api/preview-file")
def api_preview_file():
    preview_id = request.args.get("id", "")
    target = _safe_child_path(PREVIEW_DIR, preview_id)
    if not target:
        return jsonify({"ok": False, "message": "Preview not found."}), 404
    return send_file(target, mimetype="image/jpeg")


@app.get("/api/health")
def api_health():
    return jsonify(
        {
            "ok": True,
            "download_dir": str(DOWNLOAD_DIR),
            "preview_dir": str(PREVIEW_DIR),
            "ffmpeg_dir": FFMPEG_DIR,
            "python": sys.version,
        }
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=False)
