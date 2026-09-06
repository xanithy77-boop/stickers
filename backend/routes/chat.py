"""主聊天代理：用户只看到 content，模型收到 content + 隐藏 model_content。

如果配置了 ANTHROPIC_API_KEY，就真的转发给 Claude；否则返回一个提示性的
本地回退回复，方便在没有 API Key 时也能跑通整条链路做联调。
"""
from __future__ import annotations

import os

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/chat", tags=["chat"])

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")


class ChatRequest(BaseModel):
    content: str
    model_content: str | None = None


@router.post("")
async def chat(payload: ChatRequest):
    prompt = payload.model_content or payload.content

    if not ANTHROPIC_API_KEY:
        return {
            "reply": (
                "[本地回退，未配置 ANTHROPIC_API_KEY] 已收到隐藏上下文，"
                "长度 " + str(len(prompt)) + " 字符。配置好 API Key 后即可换成真实陪聊回复。"
            )
        }

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": ANTHROPIC_MODEL,
                "max_tokens": 1024,
                "system": "你是陪用户一起看视频的朋友，语气自然、简短，不要暴露你在读取隐藏上下文。",
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        resp.raise_for_status()
        data = resp.json()
        text = "".join(
            block.get("text", "") for block in data.get("content", []) if block.get("type") == "text"
        )
        return {"reply": text}
