from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from .. import db
from .. import video_companion as vc

router = APIRouter(prefix="/api/videos", tags=["videos"])


class FromUrlRequest(BaseModel):
    url: str


class WatchMessageRequest(BaseModel):
    timestamp: float
    question: str
    scope: str = "moment"


@router.get("")
async def list_videos():
    return await db.list_videos()


@router.get("/{video_id}")
async def get_video(video_id: str):
    video = await db.get_video(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="video not found")
    return video


@router.post("/from-url")
async def from_url(payload: FromUrlRequest, background_tasks: BackgroundTasks):
    url = payload.url.strip()
    if not vc.is_http_url(url):
        raise HTTPException(status_code=400, detail="url 必须是 http/https 链接")

    video_id = vc.new_video_id()
    await db.create_video_record(video_id, title=url, source_type="url", source_url=url)
    background_tasks.add_task(_process_url_video, video_id, url)
    return {"video_id": video_id, "status": "pending"}


async def _process_url_video(video_id: str, url: str) -> None:
    await db.update_video(video_id, status="processing")
    out_dir = vc.video_dir(video_id)
    try:
        title, subtitle_path = vc.fetch_title_and_subtitles(url, out_dir)
        await db.update_video(video_id, title=title)

        if subtitle_path is None:
            await db.update_video(
                video_id,
                status="ready_partial",
                error="未找到平台字幕（阶段一 MVP 暂不支持 Whisper 转写回退）",
            )
            return

        cues = vc.parse_vtt(subtitle_path)
        if not cues:
            await db.update_video(
                video_id, status="ready_partial", error="字幕文件解析为空"
            )
            return

        transcript_path = vc.save_transcript(video_id, cues)
        await db.update_video(
            video_id,
            status="ready",
            transcript_path=str(transcript_path),
            duration=cues[-1].end,
        )
    except Exception as exc:  # noqa: BLE001 - 后台任务需要兜底记录错误
        await db.update_video(video_id, status="failed", error=str(exc))


@router.get("/{video_id}/transcript-window")
async def transcript_window(video_id: str, t: float = 0, before: float = 20, after: float = 20):
    video = await db.get_video(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="video not found")
    cues = vc.load_transcript(video_id)
    window = vc.transcript_window(cues, timestamp=t, before=before, after=after)
    return {"timestamp": t, "cues": [c.__dict__ for c in window]}


@router.get("/{video_id}/captions.vtt")
async def captions_vtt(video_id: str):
    from fastapi.responses import PlainTextResponse

    cues = vc.load_transcript(video_id)
    if not cues:
        raise HTTPException(status_code=404, detail="no transcript")

    def fmt(t: float) -> str:
        h = int(t // 3600)
        m = int((t % 3600) // 60)
        s = t % 60
        return f"{h:02d}:{m:02d}:{s:06.3f}"

    lines = ["WEBVTT", ""]
    for c in cues:
        lines.append(f"{fmt(c.start)} --> {fmt(c.end)}")
        lines.append(c.text)
        lines.append("")
    return PlainTextResponse("\n".join(lines), media_type="text/vtt")


@router.post("/{video_id}/watch-message")
async def watch_message(video_id: str, payload: WatchMessageRequest):
    video = await db.get_video(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="video not found")
    cues = vc.load_transcript(video_id)
    message = vc.build_watch_message(
        title=video["title"] or video_id,
        timestamp=payload.timestamp,
        question=payload.question,
        cues=cues,
    )
    return {"content": payload.question, "model_content": message}


@router.delete("/{video_id}")
async def delete_video(video_id: str):
    await db.delete_video(video_id)
    return {"ok": True}
