# Cove 共影 · 阶段一 MVP

一起看视频时，AI 只依据"播放点之前的字幕"陪聊，而不是把整段视频丢给聊天模型。
本目录实现的是《Cove Media Companion System Building Guide》里的 **阶段一：字幕型共影**：

1. 粘贴视频链接 → 后台用 `yt-dlp` 抓平台字幕（不下载视频本体）。
2. 字幕统一转成 `transcript.json` / `transcript.txt`，缓存在 `data/videos/<video_id>/`。
3. 前端用 iframe 播放，字幕区展示当前时间点附近的字幕。
4. 用户"问这一幕"时，后端只取播放点之前一段时间窗口内的字幕作为隐藏上下文
   (`model_content`)，交给聊天模型；用户看到的仍是自己打的原话。

## 运行

```bash
pip install -r backend/requirements.txt
cp .env.example .env   # 可选：填 ANTHROPIC_API_KEY 才会调用真实模型
uvicorn backend.main:app --reload
```

（`backend/` 用相对导入组织成一个包，所以要在仓库根目录用 `backend.main:app` 启动，
不要 `cd backend` 后再跑 `uvicorn main:app`。）

打开 http://127.0.0.1:8000/reading.html，粘贴一个有字幕的 YouTube 链接即可。

未配置 `ANTHROPIC_API_KEY` 时，`/api/chat` 会返回一个本地回退提示（说明隐藏上下文已经
生成、长度多少），方便先确认导入 → 字幕 → 隐藏上下文这条链路是通的，再接真实模型。

## 目录结构

```
backend/
  main.py            # FastAPI 入口
  db.py              # videos 表（sqlite）
  video_companion.py # 抓字幕、解析 VTT、时间窗口取证据、组装隐藏上下文
  routes/video.py     # 共影 API
  routes/chat.py       # 主聊天代理（可见消息 + 隐藏上下文）
frontend/
  reading.html        # 共影页面
data/videos/<id>/      # 每个视频的字幕缓存（不提交到仓库）
```

## 核心接口

| 功能 | 接口 |
|---|---|
| 视频列表 | `GET /api/videos` |
| 从链接导入 | `POST /api/videos/from-url` |
| 附近字幕窗口 | `GET /api/videos/{id}/transcript-window?t=123` |
| 问这一幕（生成隐藏上下文） | `POST /api/videos/{id}/watch-message` |
| WebVTT 字幕 | `GET /api/videos/{id}/captions.vtt` |
| 主聊天代理 | `POST /api/chat` |

## 阶段一没做的事（按指南属于后续阶段）

- 本地视频上传、外挂/内封字幕、`<video>` Range 播放、移动端代理播放。
- 无字幕时的 Whisper 转写回退（目前无字幕会标记为 `ready_partial` 并给出原因）。
- 当前片段感官层（ffmpeg 截片段 + 视觉模型）、整片摘要、陪看停顿点、Markdown 笔记沉淀。
- 直播陪看（依赖 macOS 的 `screencapture` / `AppleScript` / BlackHole，本环境为 Linux 无法运行）。

想往后推进时，可以按指南的"最小可复刻版本"顺序继续加阶段二～五。

## 分享前检查清单

不要把真实 `.env`、`data/cove.db`、`data/videos/` 下的字幕缓存提交到仓库或分享出去，
`.gitignore` 已经排除了这些路径。
