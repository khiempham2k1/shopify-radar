"""Get a YouTube video's words: subtitles first, Groq Whisper when there are none.

The audio path follows Agent Reach's transcribe.py (download with yt-dlp,
re-encode to mono 16 kHz, cut into 10-minute chunks), but asks Groq for
`verbose_json` so every segment keeps its timestamp.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

log = logging.getLogger(__name__)

GROQ_ENDPOINT = "https://api.groq.com/openai/v1/audio/transcriptions"


class TranscriptError(RuntimeError):
    pass


@dataclass
class Transcript:
    via: str
    segments: list[dict[str, Any]] = field(default_factory=list)
    language: str = ""
    duration_s: int = 0
    audio_seconds: int = 0
    model: str = ""

    @property
    def text(self) -> str:
        return " ".join(s["text"] for s in self.segments).strip()


# ── subtitles ───────────────────────────────────────────────────────

_TS = r"(\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{3}"


def _seconds(ts: str) -> float:
    parts = ts.replace(",", ".").split(":")
    parts = [float(p) for p in parts]
    while len(parts) < 3:
        parts.insert(0, 0.0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def parse_vtt(text: str) -> list[dict[str, Any]]:
    """Parse WebVTT into segments. Removes inline tags and the rolling
    duplicates YouTube auto-captions produce (each cue repeats the previous line)."""
    segments: list[dict[str, Any]] = []
    previous_lines: list[str] = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        lines = [line for line in block.strip().split("\n") if line.strip()]
        timing_index = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing_index is None:
            continue
        match = re.match(rf"\s*({_TS})\s*-->\s*({_TS})", lines[timing_index])
        if not match:
            continue
        start, end = _seconds(match.group(1)), _seconds(match.group(3))
        cue_lines = []
        for raw in lines[timing_index + 1 :]:
            clean = re.sub(r"<[^>]+>", "", raw)
            clean = re.sub(r"\s+", " ", clean.replace("&nbsp;", " ").replace("&amp;", "&")).strip()
            if clean and clean not in previous_lines and clean not in cue_lines:
                cue_lines.append(clean)
        current = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", raw)).strip() for raw in lines[timing_index + 1 :]]
        previous_lines = [c for c in current if c]
        if not cue_lines:
            continue
        segment_text = " ".join(cue_lines)
        if segments and segments[-1]["text"] == segment_text:
            segments[-1]["end"] = end
            continue
        segments.append({"start": round(start, 2), "end": round(end, 2), "text": segment_text})
    return segments


def fetch_subtitles(url: str, work_dir: Path, langs: list[str]) -> Transcript | None:
    """Manual subtitles first, then YouTube's automatic captions. None when neither exists."""
    import yt_dlp

    work_dir.mkdir(parents=True, exist_ok=True)
    duration = 0
    for automatic in (False, True):
        for old in work_dir.glob("*.vtt"):
            old.unlink()
        options = {
            "quiet": True,
            "no_warnings": True, "js_runtimes": {"deno": {}, "node": {}},
            "skip_download": True,
            "writesubtitles": not automatic,
            "writeautomaticsub": automatic,
            "subtitleslangs": langs,
            "subtitlesformat": "vtt",
            "outtmpl": str(work_dir / "%(id)s.%(ext)s"),
        }
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=True) or {}
        except yt_dlp.utils.DownloadError as exc:
            raise TranscriptError(f"yt-dlp không lấy được phụ đề: {exc}") from exc
        duration = int(info.get("duration") or duration)
        files = sorted(work_dir.glob("*.vtt"), key=lambda p: _lang_rank(p, langs))
        for path in files:
            segments = parse_vtt(path.read_text(encoding="utf-8", errors="ignore"))
            if segments:
                lang = path.suffixes[-2].lstrip(".") if len(path.suffixes) >= 2 else ""
                return Transcript(via="subtitle", segments=segments, language=lang, duration_s=duration, model="youtube-captions")
    return None


def _lang_rank(path: Path, langs: list[str]) -> int:
    lang = path.suffixes[-2].lstrip(".") if len(path.suffixes) >= 2 else ""
    return langs.index(lang) if lang in langs else len(langs)


def video_duration(url: str) -> int:
    import yt_dlp

    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "js_runtimes": {"deno": {}, "node": {}}, "skip_download": True}) as ydl:
        info = ydl.extract_info(url, download=False) or {}
    return int(info.get("duration") or 0)


# ── Groq Whisper ────────────────────────────────────────────────────


def _run(cmd: list[str], timeout: int = 900) -> None:
    if not shutil.which(cmd[0]):
        raise TranscriptError(f"Chưa cài {cmd[0]}")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    if proc.returncode != 0:
        raise TranscriptError(f"{cmd[0]} lỗi: {proc.stderr[-400:]}")


def download_audio(url: str, work_dir: Path) -> Path:
    import yt_dlp

    work_dir.mkdir(parents=True, exist_ok=True)
    options = {
        "quiet": True,
        "no_warnings": True, "js_runtimes": {"deno": {}, "node": {}},
        "format": "bestaudio/best",
        "outtmpl": str(work_dir / "source.%(ext)s"),
        "max_filesize": 512 * 1024 * 1024,
    }
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as exc:
        raise TranscriptError(f"yt-dlp không tải được audio: {exc}") from exc
    files = [p for p in work_dir.glob("source.*") if p.suffix not in (".part", ".ytdl")]
    if not files:
        raise TranscriptError("Không tìm thấy file audio sau khi tải")
    return files[0]


def compress_and_chunk(source: Path, work_dir: Path, chunk_seconds: int, max_seconds: int) -> list[Path]:
    compressed = work_dir / "audio.m4a"
    _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(source), "-t", str(max_seconds), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "32k", str(compressed)])
    _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(compressed), "-f", "segment", "-segment_time", str(chunk_seconds), "-c", "copy", str(work_dir / "chunk_%03d.m4a")])
    chunks = sorted(work_dir.glob("chunk_*.m4a"))
    if not chunks:
        raise TranscriptError("ffmpeg không tạo được đoạn audio nào")
    return chunks


def groq_transcribe_chunk(path: Path, api_key: str, model: str, prompt: str, timeout: int = 300) -> dict[str, Any]:
    with path.open("rb") as fh:
        response = requests.post(
            GROQ_ENDPOINT,
            headers={"Authorization": f"Bearer {api_key}"},
            files={"file": (path.name, fh, "audio/m4a")},
            data={"model": model, "response_format": "verbose_json", "temperature": "0", "prompt": prompt[:800]},
            timeout=timeout,
        )
    if response.status_code != 200:
        raise TranscriptError(f"Groq trả về HTTP {response.status_code}: {response.text[:300]}")
    return response.json()


def transcribe_with_groq(
    url: str,
    work_dir: Path,
    api_key: str,
    model: str,
    terms: str,
    chunk_seconds: int = 600,
    max_seconds: int = 3600,
) -> Transcript:
    if not api_key:
        raise TranscriptError("Chưa cấu hình GROQ_API_KEY")
    source = download_audio(url, work_dir)
    chunks = compress_and_chunk(source, work_dir, chunk_seconds, max_seconds)
    segments: list[dict[str, Any]] = []
    offset = 0.0
    language = ""
    for chunk in chunks:
        data = groq_transcribe_chunk(chunk, api_key, model, terms)
        language = language or data.get("language", "")
        for seg in data.get("segments") or []:
            text = (seg.get("text") or "").strip()
            if text:
                segments.append({"start": round(offset + float(seg.get("start", 0)), 2), "end": round(offset + float(seg.get("end", 0)), 2), "text": text})
        if not data.get("segments") and data.get("text"):
            segments.append({"start": round(offset, 2), "end": round(offset + chunk_seconds, 2), "text": data["text"].strip()})
        offset += float(data.get("duration") or chunk_seconds)
    return Transcript(via="groq", segments=segments, language=language, duration_s=int(offset), audio_seconds=int(offset), model=model)


def cleanup(work_dir: Path) -> None:
    shutil.rmtree(work_dir, ignore_errors=True)
