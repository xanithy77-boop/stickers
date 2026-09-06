"""共影核心逻辑：抓字幕、生成统一 transcript、按时间窗口取证据、组装隐藏上下文。

阶段一（字幕型共影）范围：
  - 从链接导入视频，只抓字幕，不下载视频本体。
  - "问这一幕" 只使用播放点之前的字幕窗口，遵守防剧透规则。
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "videos"

# "问这一幕" 时向前回溯的秒数窗口，只取播放点之前的内容，避免剧透。
RECENT_WINDOW_SECONDS = 180
# transcript-window 接口默认的前后窗口（用于字幕区展示，允许看到当前行）。
NEARBY_WINDOW_SECONDS = 20


@dataclass
class SubtitleCue:
    start: float
    end: float
    text: str


def new_video_id() -> str:
    return uuid.uuid4().hex[:12]


def video_dir(video_id: str) -> Path:
    d = DATA_DIR / video_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def is_http_url(url: str) -> bool:
    return bool(re.match(r"^https?://", url.strip(), re.IGNORECASE))


# ---------------------------------------------------------------------------
# 字幕抓取（yt-dlp）
# ---------------------------------------------------------------------------

def fetch_title_and_subtitles(url: str, out_dir: Path) -> tuple[str, Optional[Path]]:
    """使用 yt-dlp 只抓标题和字幕，不下载视频本体。

    字幕优先级：外挂字幕不适用于在线导入场景，这里按
    平台官方字幕 > 平台自动字幕 的顺序，并优先中文。
    返回 (title, 选中的字幕文件路径 or None)。
    """
    import yt_dlp

    outtmpl = str(out_dir / "platform_subtitle.%(ext)s")
    ydl_opts = {
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitlesformat": "vtt",
        "subtitleslangs": ["zh-Hans", "zh-Hant", "zh", "en", "en-US", "en-orig"],
        "outtmpl": outtmpl,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        title = info.get("title") or url
        ydl.process_video_result(info, download=True)

    candidates = sorted(out_dir.glob("platform_subtitle*.vtt"))
    if not candidates:
        return title, None

    def priority(path: Path) -> int:
        name = path.name.lower()
        for i, lang in enumerate(["zh-hans", "zh-hant", ".zh.", "zh_", "en"]):
            if lang in name:
                return i
        return 99

    candidates.sort(key=priority)
    return title, candidates[0]


# ---------------------------------------------------------------------------
# VTT 解析与统一 transcript
# ---------------------------------------------------------------------------

_TIME_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[.,](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[.,](\d{3})"
)


def _to_seconds(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def parse_vtt(path: Path) -> list[SubtitleCue]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    cues: list[SubtitleCue] = []
    i = 0
    while i < len(lines):
        match = _TIME_RE.search(lines[i])
        if match:
            start = _to_seconds(*match.groups()[0:4])
            end = _to_seconds(*match.groups()[4:8])
            i += 1
            text_lines = []
            while i < len(lines) and lines[i].strip():
                cleaned = re.sub(r"<[^>]+>", "", lines[i]).strip()
                if cleaned:
                    text_lines.append(cleaned)
                i += 1
            content = " ".join(text_lines).strip()
            if content and (not cues or cues[-1].text != content):
                cues.append(SubtitleCue(start=start, end=end, text=content))
        else:
            i += 1
    return cues


def save_transcript(video_id: str, cues: list[SubtitleCue]) -> Path:
    d = video_dir(video_id)
    json_path = d / "transcript.json"
    json_path.write_text(
        json.dumps([asdict(c) for c in cues], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    txt_path = d / "transcript.txt"
    lines = [f"[{c.start:.1f} --> {c.end:.1f}] {c.text}" for c in cues]
    txt_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path


def load_transcript(video_id: str) -> list[SubtitleCue]:
    json_path = video_dir(video_id) / "transcript.json"
    if not json_path.exists():
        return []
    raw = json.loads(json_path.read_text(encoding="utf-8"))
    return [SubtitleCue(**item) for item in raw]


# ---------------------------------------------------------------------------
# 时间窗口取证据
# ---------------------------------------------------------------------------

def transcript_window(
    cues: list[SubtitleCue], timestamp: float, before: float = NEARBY_WINDOW_SECONDS,
    after: float = NEARBY_WINDOW_SECONDS,
) -> list[SubtitleCue]:
    """给字幕区展示用：当前时间点附近的字幕（允许看到当前行）。"""
    return [c for c in cues if c.end >= timestamp - before and c.start <= timestamp + after]


def preceding_window(
    cues: list[SubtitleCue], timestamp: float, window_seconds: float = RECENT_WINDOW_SECONDS
) -> list[SubtitleCue]:
    """给"问这一幕"用：只取播放点之前的内容，防止剧透。"""
    return [c for c in cues if c.start <= timestamp and c.start >= timestamp - window_seconds]


def build_watch_message(
    *, title: str, timestamp: float, question: str, cues: list[SubtitleCue],
) -> str:
    """组装隐藏 model_content：视频标题、当前时间点、字幕窗口、防剧透规则。"""
    recent = preceding_window(cues, timestamp)
    if recent:
        subtitle_block = "\n".join(f"[{c.start:.1f}s] {c.text}" for c in recent)
    else:
        subtitle_block = "(此刻附近没有可用字幕证据)"

    return (
        "【共影 · 问这一幕】\n"
        f"视频标题：{title}\n"
        f"当前播放时间：{timestamp:.1f} 秒\n"
        f"播放点之前的字幕（最近 {RECENT_WINDOW_SECONDS} 秒内）：\n"
        f"{subtitle_block}\n"
        "\n"
        "规则：\n"
        "1. 只能依据上面播放点之前的字幕回答，不能推测或剧透播放点之后的剧情。\n"
        "2. 如果字幕证据不足以回答，请直接说明当前证据不够，不要编造画面或台词。\n"
        "3. 回复保持自然陪聊语气，不要提及你在读取『隐藏上下文』这件事。\n"
        "\n"
        f"用户问：{question}"
    )
