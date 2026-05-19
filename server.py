import logging
import os
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from agent import get_agent_metrics, process_text_turn, spotify, stt, tts
from tools.deviceTool import get_device_metrics
from tools.knowledgeTool import get_knowledge_metrics
from tools.newsTool import get_news_metrics
from tools.systemTool import get_live_core_system_data


log = logging.getLogger("JarvisAPI")
STARTUP_GREETING = "Hello sir. All systems are online and functioning within normal parameters."
api_metrics = defaultdict(int)
api_latency_ms = {
    "http_last_latency_ms": 0.0,
    "http_avg_latency_ms": 0.0,
    "websocket_last_turn_latency_ms": 0.0,
    "websocket_avg_turn_latency_ms": 0.0,
}


def inc_metric(name: str, value: int = 1) -> None:
    api_metrics[name] += value


def observe_latency(metric_key: str, avg_key: str, count_key: str, elapsed_ms: float) -> None:
    api_latency_ms[metric_key] = round(elapsed_ms, 2)
    count = api_metrics.get(count_key, 0)
    current_avg = api_latency_ms.get(avg_key, 0.0)
    if count <= 0:
        api_latency_ms[avg_key] = round(elapsed_ms, 2)
        return
    api_latency_ms[avg_key] = round(((current_avg * (count - 1)) + elapsed_ms) / count, 2)


def get_api_metrics() -> dict[str, Any]:
    snapshot = dict(api_metrics)
    snapshot.update(api_latency_ms)
    return snapshot


def get_electron_log_path() -> Path:
    configured = os.getenv("JARVIS_ELECTRON_LOG_PATH")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / "Library" / "Logs" / "MyJarvis" / "electron.log"


def read_log_tail(path: Path, lines: int) -> list[str]:
    if lines <= 0:
        return []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        return [line.rstrip("\n") for line in deque(fh, maxlen=lines)]


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    speak: bool = False


class ChatResponse(BaseModel):
    reply: str
    spoken: bool = False


def get_cors_origins() -> list[str]:
    configured = os.getenv("JARVIS_CORS_ORIGINS")
    if configured:
        return [origin.strip() for origin in configured.split(",") if origin.strip()]

    return [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "null",
    ]


app = FastAPI(
    title="MyJarvis Local API",
    description="Local-only API for connecting MyJarvis to a frontend.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def say_startup_greeting() -> None:
    inc_metric("startup_greeting_attempts")
    try:
        tts.start()
        tts.say(STARTUP_GREETING, wait=True, wait_timeout=30.0)
        inc_metric("startup_greeting_success")
    except Exception as exc:
        inc_metric("startup_greeting_failures")
        log.exception("Startup greeting failed: %s", exc)


@app.on_event("startup")
def start_backend_greeting() -> None:
    threading.Thread(
        target=say_startup_greeting,
        name="JarvisStartupGreeting",
        daemon=True,
    ).start()


def get_voice_status() -> dict[str, Any]:
    return {
        "stt": stt.get_health(),
        "stt_muted": stt.is_muted,
        "tts": tts.get_health(),
        "tts_connected": tts.connection is not None,  # kept for frontend compatibility
    }


def start_voice_runtime() -> dict[str, Any]:
    inc_metric("voice_runtime_start_calls")
    tts.start()
    stt.start()
    return get_voice_status()


def stop_voice_runtime() -> dict[str, Any]:
    inc_metric("voice_runtime_stop_calls")
    stt.stop()
    tts.stop()
    return get_voice_status()


def toggle_voice_mute() -> dict[str, Any]:
    inc_metric("voice_runtime_toggle_mute_calls")
    if stt.is_muted:
        stt.unmute()
        inc_metric("voice_runtime_unmute_success")
    else:
        stt.mute()
        inc_metric("voice_runtime_mute_success")
    return get_voice_status()


def speak_reply(reply: str) -> None:
    inc_metric("speak_reply_calls")
    if not reply.strip():
        inc_metric("speak_reply_empty")
        return

    if tts.connection is None:
        tts.start()

    was_muted = stt.is_muted
    if not was_muted:
        stt.mute()

    try:
        tts.say(reply, wait=True, wait_timeout=30.0)
    finally:
        if not was_muted:
            stt.unmute()


@app.get("/")
def root() -> dict[str, str]:
    return {
        "name": "MyJarvis Local API",
        "docs": "/docs",
        "chat": "POST /chat",
        "websocket": "ws://127.0.0.1:8000/ws",
    }


@app.get("/health")
def health() -> dict[str, Any]:
    inc_metric("health_requests")
    return {
        "ok": True,
        "api": get_api_metrics(),
        "voice": get_voice_status(),
        "system": get_live_core_system_data(),
    }


@app.get("/metrics")
def metrics() -> dict[str, Any]:
    inc_metric("metrics_requests")
    return {
        "ok": True,
        "api": get_api_metrics(),
        "agent": get_agent_metrics(),
        "stt": stt.get_health(),
        "tts": tts.get_health(),
        "knowledge": get_knowledge_metrics(),
        "spotify": spotify.get_metrics(),
        "device": get_device_metrics(),
        "news": get_news_metrics(),
        "system": get_live_core_system_data(),
    }


@app.get("/logs/electron")
def electron_logs(lines: int = 80) -> dict[str, Any]:
    inc_metric("electron_log_requests")
    safe_lines = max(1, min(lines, 500))
    log_path = get_electron_log_path()
    if not log_path.exists():
        return {
            "ok": True,
            "exists": False,
            "path": str(log_path),
            "lines": [],
        }
    try:
        tail = read_log_tail(log_path, safe_lines)
    except Exception as exc:
        inc_metric("electron_log_errors")
        raise HTTPException(status_code=500, detail=f"Failed to read Electron log: {exc}") from exc

    return {
        "ok": True,
        "exists": True,
        "path": str(log_path),
        "lines": tail,
    }


@app.get("/system/live")
def system_live() -> dict[str, Any]:
    inc_metric("system_live_requests")
    return {
        "ok": True,
        "system": get_live_core_system_data(),
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    request_started = time.monotonic()
    inc_metric("chat_requests_total")
    message = request.message.strip()
    if not message:
        inc_metric("chat_requests_bad_request")
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    try:
        reply = await run_in_threadpool(process_text_turn, message, False)
        if request.speak:
            await run_in_threadpool(speak_reply, reply)
        inc_metric("chat_requests_success")
    except RuntimeError as exc:
        inc_metric("chat_requests_conflict")
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        inc_metric("chat_requests_error")
        log.exception("Chat request failed: %s", exc)
        raise HTTPException(status_code=500, detail="Jarvis failed to respond.") from exc
    finally:
        observe_latency(
            "http_last_latency_ms",
            "http_avg_latency_ms",
            "chat_requests_total",
            (time.monotonic() - request_started) * 1000,
        )

    return ChatResponse(reply=reply, spoken=request.speak)


@app.post("/voice/start")
async def start_voice() -> dict[str, Any]:
    inc_metric("voice_start_requests")
    try:
        voice = await run_in_threadpool(start_voice_runtime)
    except Exception as exc:
        log.exception("Failed to start voice runtime: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to start voice runtime.") from exc

    return {"ok": True, "voice": voice}


@app.post("/voice/stop")
async def stop_voice() -> dict[str, Any]:
    inc_metric("voice_stop_requests")
    try:
        voice = await run_in_threadpool(stop_voice_runtime)
    except Exception as exc:
        log.exception("Failed to stop voice runtime: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to stop voice runtime.") from exc

    return {"ok": True, "voice": voice}


@app.post("/voice/toggle-mute")
async def toggle_voice_mute_endpoint() -> dict[str, Any]:
    inc_metric("voice_toggle_mute_requests")
    try:
        voice = await run_in_threadpool(toggle_voice_mute)
    except Exception as exc:
        log.exception("Failed to toggle voice mute: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to toggle voice mute.") from exc

    return {"ok": True, "voice": voice}


@app.websocket("/ws")
async def websocket_chat(websocket: WebSocket) -> None:
    inc_metric("websocket_connections_opened")
    await websocket.accept()

    try:
        while True:
            payload = await websocket.receive_json()
            inc_metric("websocket_messages_received")
            message = str(payload.get("message", "")).strip()

            if not message:
                await websocket.send_json(
                    {"type": "error", "detail": "Message cannot be empty."}
                )
                continue

            await websocket.send_json({"type": "status", "status": "thinking"})

            try:
                ws_turn_started = time.monotonic()
                reply = await run_in_threadpool(process_text_turn, message, False)
                if bool(payload.get("speak", False)):
                    await run_in_threadpool(speak_reply, reply)
                inc_metric("websocket_turn_success")
                observe_latency(
                    "websocket_last_turn_latency_ms",
                    "websocket_avg_turn_latency_ms",
                    "websocket_turn_success",
                    (time.monotonic() - ws_turn_started) * 1000,
                )
            except RuntimeError as exc:
                inc_metric("websocket_turn_conflict")
                await websocket.send_json({"type": "error", "detail": str(exc)})
                continue
            except Exception as exc:
                inc_metric("websocket_turn_error")
                log.exception("WebSocket chat failed: %s", exc)
                await websocket.send_json(
                    {"type": "error", "detail": "Jarvis failed to respond."}
                )
                continue

            await websocket.send_json(
                {"type": "reply", "reply": reply, "spoken": bool(payload.get("speak", False))}
            )
            inc_metric("websocket_replies_sent")
    except WebSocketDisconnect:
        inc_metric("websocket_disconnects")
        log.info("Frontend WebSocket disconnected.")
