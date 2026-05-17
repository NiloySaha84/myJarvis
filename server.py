import logging
import os
import threading
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from agent import process_text_turn, stt, tts


log = logging.getLogger("JarvisAPI")
STARTUP_GREETING = "Hello Niloy, What's the plan today"


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
    try:
        tts.start()
        tts.say(STARTUP_GREETING, wait=True, wait_timeout=30.0)
    except Exception as exc:
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
        "tts_connected": tts.connection is not None,
    }


def start_voice_runtime() -> dict[str, Any]:
    tts.start()
    stt.start()
    return get_voice_status()


def stop_voice_runtime() -> dict[str, Any]:
    stt.stop()
    tts.stop()
    return get_voice_status()


def toggle_voice_mute() -> dict[str, Any]:
    if stt.is_muted:
        stt.unmute()
    else:
        stt.mute()
    return get_voice_status()


def speak_reply(reply: str) -> None:
    if not reply.strip():
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
    return {
        "ok": True,
        "voice": get_voice_status(),
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    message = request.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    try:
        reply = await run_in_threadpool(process_text_turn, message, False)
        if request.speak:
            await run_in_threadpool(speak_reply, reply)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        log.exception("Chat request failed: %s", exc)
        raise HTTPException(status_code=500, detail="Jarvis failed to respond.") from exc

    return ChatResponse(reply=reply, spoken=request.speak)


@app.post("/voice/start")
async def start_voice() -> dict[str, Any]:
    try:
        voice = await run_in_threadpool(start_voice_runtime)
    except Exception as exc:
        log.exception("Failed to start voice runtime: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to start voice runtime.") from exc

    return {"ok": True, "voice": voice}


@app.post("/voice/stop")
async def stop_voice() -> dict[str, Any]:
    try:
        voice = await run_in_threadpool(stop_voice_runtime)
    except Exception as exc:
        log.exception("Failed to stop voice runtime: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to stop voice runtime.") from exc

    return {"ok": True, "voice": voice}


@app.post("/voice/toggle-mute")
async def toggle_voice_mute_endpoint() -> dict[str, Any]:
    try:
        voice = await run_in_threadpool(toggle_voice_mute)
    except Exception as exc:
        log.exception("Failed to toggle voice mute: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to toggle voice mute.") from exc

    return {"ok": True, "voice": voice}


@app.websocket("/ws")
async def websocket_chat(websocket: WebSocket) -> None:
    await websocket.accept()

    try:
        while True:
            payload = await websocket.receive_json()
            message = str(payload.get("message", "")).strip()

            if not message:
                await websocket.send_json(
                    {"type": "error", "detail": "Message cannot be empty."}
                )
                continue

            await websocket.send_json({"type": "status", "status": "thinking"})

            try:
                reply = await run_in_threadpool(process_text_turn, message, False)
                if bool(payload.get("speak", False)):
                    await run_in_threadpool(speak_reply, reply)
            except RuntimeError as exc:
                await websocket.send_json({"type": "error", "detail": str(exc)})
                continue
            except Exception as exc:
                log.exception("WebSocket chat failed: %s", exc)
                await websocket.send_json(
                    {"type": "error", "detail": "Jarvis failed to respond."}
                )
                continue

            await websocket.send_json(
                {"type": "reply", "reply": reply, "spoken": bool(payload.get("speak", False))}
            )
    except WebSocketDisconnect:
        log.info("Frontend WebSocket disconnected.")
