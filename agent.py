import os
import re
import time
import threading
import logging
from typing import Annotated, Optional, Sequence, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from spotipy.cache_handler import CacheFileHandler

from stt import RealTimeSTT
from tts import RealTimeTTS
from audioManager import AudioManager
from tools.spotifyTool import SpotifyTool
from tools.deviceTool import (
    close_app,
    create_file,
    create_folder,
    open_app,
    open_browser,
    open_file,
    open_folder,
    rename_folder_file,
    copy_folder,
    copy_file,
)
from tools.knowledgeTool import rebuild_knowledge_index, query_knowledge_base

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("Agent")

# openai
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MODEL = "gpt-4o-mini"

# spotify
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
scopes = (
    "streaming, playlist-read-private, playlist-modify-private, user-top-read, "
    "user-read-recently-played, user-library-modify, user-library-read, "
    "user-read-currently-playing, app-remote-control"
)
redirect_uri = os.getenv("REDIRECT_URI")
cache_handler = CacheFileHandler(cache_path="cache")

# stt
STT_API_KEY = os.getenv("DpGram_API_KEY")
STT_MODEL = "flux-general-en"
STT_SAMPLE_RATE = 16000
STT_CHANNELS = 1
SILENCE_TIMEOUT = 120
SILENCE_THRESHOLD = 0.02
HEALTH_CHECK_INTERVAL = 5

# tts
TTS_API_KEY = os.getenv("DpGram_API_KEY") or os.getenv("DEEPGRAM_API_KEY")
TTS_MODEL = "aura-2-apollo-en"
TTS_SAMPLE_RATE = 48000
TTS_CHANNELS = 1


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]


spotify = SpotifyTool(
    SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, redirect_uri, scopes, cache_handler
)
stt = RealTimeSTT(STT_API_KEY, STT_MODEL, STT_SAMPLE_RATE, STT_CHANNELS)
tts = RealTimeTTS(TTS_API_KEY, TTS_MODEL, TTS_SAMPLE_RATE, TTS_CHANNELS)

@tool
def get_user_playlists():
    """List my Spotify playlists."""
    return spotify.get_user_playlists()


@tool
def play_next():
    """Skip to next track."""
    return spotify.play_next_song()

@tool
def pause_current_song():
    """Pause playback."""
    return spotify.pause_song()

@tool
def resume_current_song():
    """Resume playback."""
    return spotify.resume_song()

@tool
def play_previous():
    """Go to previous track."""
    return spotify.play_previous_song()

@tool
def play_song(song_name: str):
    """Play a song by name."""
    return spotify.play_this_song(song_name)

@tool
def play_playlist(playlist_name: str):
    """Play a playlist by name."""
    return spotify.play_this_playlist(playlist_name)

@tool
def add_song_to_queue(song_name: str):
    """Queue a song."""
    return spotify.add_in_queue(song_name)

@tool 
def remove_song_from_queue(song_name: str):
    """Remove a song from the queue (if supported)."""
    return spotify.remove_from_queue(song_name)

@tool
def create_new_file(file_name: str):
    """Create a file. Use full path."""
    return create_file(file_name)


@tool
def create_new_folder(folder_name: str):
    """Create a folder. Use full path."""
    return create_folder(folder_name)


@tool
def open_new_file(file_path: str, app: str):
    """Open a file in an app."""
    return open_file(file_path, app)


@tool
def open_new_folder(folder_path: str, app: str):
    """Open a folder in an app."""
    return open_folder(folder_path, app)


@tool
def open_new_app(app_name: str):
    """Open an app."""
    return open_app(app_name)


@tool
def close_new_app(app_name: str):
    """Quit an app."""
    return close_app(app_name)


@tool
def open_new_browser(browser_name: str):
    """Open a browser."""
    return open_browser(browser_name)

@tool
def rename_this_folder_file(folder_path: str, new_name: str):
    """Rename a file or folder."""
    return rename_folder_file(folder_path, new_name)

@tool
def copy_this_folder(folder_path: str, new_path: str):
    """Copy a folder."""
    return copy_folder(folder_path, new_path)

@tool
def copy_this_file(file_path: str, new_path: str):
    """Copy a file."""
    return copy_file(file_path, new_path)

@tool
def query_uploaded_knowledge(need: str):
    """Search my notes/docs in knowledge-base."""
    return query_knowledge_base(need)


@tool
def rebuild_uploaded_knowledge_db():
    """Rebuild the knowledge index after I add files."""
    return rebuild_knowledge_index()


tools = [
    get_user_playlists,
    play_next,
    pause_current_song,
    resume_current_song,
    play_previous,
    play_song,
    play_playlist,
    add_song_to_queue,
    remove_song_from_queue,
    create_new_file,
    create_new_folder,
    open_new_file,
    open_new_folder,
    open_new_app,
    close_new_app,
    open_new_browser,
    rename_this_folder_file,
    copy_this_folder,
    copy_this_file,
    query_uploaded_knowledge,
    rebuild_uploaded_knowledge_db,
]
model = ChatOpenAI(model=MODEL, temperature=0).bind_tools(tools)

SYSTEM_PROMPT = (
    "You are Jarvis, a concise voice-first assistant. "
    "Your replies are spoken out loud, so keep them short, natural, and "
    "conversational — one or two sentences whenever possible, no markdown, "
    "no lists, no code blocks. Confirm completed actions briefly."
    "Speak in a natural, conversational tone. Use a friendly, engaging voice like you are a human."
    "For any action that requires external execution, you must call the tool (if appropriate tool is available). Do not claim completion unless the tool result is present."
    "When a user asks anything that may depend on remembered instructions, personal rules, workflows, or notes saved in the knowledge base, call query_uploaded_knowledge first and then answer based on its output."
    "If the retrieved knowledge describes a sequence of actions, follow that sequence and call the required tools in order."
)


def model_call(state: AgentState) -> AgentState:
    response = model.invoke([SystemMessage(content=SYSTEM_PROMPT)] + list(state["messages"]))
    return {"messages": [response]}


def should_continue(state: AgentState):
    last_message = state["messages"][-1]
    if not getattr(last_message, "tool_calls", None):
        return "end"
    return "continue"


builder = StateGraph(AgentState)
builder.add_node("agent", model_call)
builder.add_node("tools", ToolNode(tools))
builder.add_edge(START, "agent")
builder.add_conditional_edges(
    "agent",
    should_continue,
    {"continue": "tools", "end": END},
)
builder.add_edge("tools", "agent")

app = builder.compile()


def extract_final_text(state: dict) -> str:
    """Last plain-text reply from the graph state."""
    if not state:
        return ""
    messages = state.get("messages", []) if isinstance(state, dict) else []
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None):
            content = msg.content
            if isinstance(content, str) and content.strip():
                return content.strip()
            # openai sometimes returns [{type,text}, ...]
            if isinstance(content, list):
                pieces = [
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                ]
                joined = " ".join(p for p in pieces if p).strip()
                if joined:
                    return joined
    return ""


history = []

# TRACE_TOOL_CALLS=0 to hide tool logs
TRACE_TOOL_CALLS = os.getenv("TRACE_TOOL_CALLS", "1") not in ("0", "false", "False", "")
TOOL_RESULT_LOG_LIMIT = 800  # trim long tool output in logs


def format_tool_args(args) -> str:
    if not args:
        return ""
    if isinstance(args, dict):
        try:
            return ", ".join(f"{k}={v!r}" for k, v in args.items())
        except Exception:
            return repr(args)
    return repr(args)


def stringify_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, dict):
                parts.append(p.get("text") or p.get("content") or repr(p))
            else:
                parts.append(str(p))
        return " ".join(parts)
    return repr(content)


def log_new_messages(messages, seen_ids: set) -> None:
    """Log tool calls/results once per message."""
    for msg in messages or []:
        mid = getattr(msg, "id", None)
        key = mid if mid is not None else id(msg)
        if key in seen_ids:
            continue
        seen_ids.add(key)

        if isinstance(msg, AIMessage):
            tool_calls = getattr(msg, "tool_calls", None) or []
            for tc in tool_calls:
                name = tc.get("name", "?") if isinstance(tc, dict) else getattr(tc, "name", "?")
                args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
                log.info("→ tool call: %s(%s)", name, format_tool_args(args))
        elif isinstance(msg, ToolMessage):
            name = getattr(msg, "name", None) or "?"
            content = stringify_content(msg.content)
            if len(content) > TOOL_RESULT_LOG_LIMIT:
                content = content[:TOOL_RESULT_LOG_LIMIT] + "...(truncated)"
            log.info("← tool result [%s]: %s", name, content)


def call_llm(text: str) -> str:
    history.append(("user", text))
    input_data = {"messages": history}

    final_state = None
    seen_ids: set = set()
    for chunk in app.stream(input_data, stream_mode="values"):
        final_state = chunk
        if TRACE_TOOL_CALLS and isinstance(chunk, dict):
            log_new_messages(chunk.get("messages", []), seen_ids)

    reply = extract_final_text(final_state)
    history.append(("assistant", reply))
    return reply


# only one agent turn at a time
turn_lock = threading.Lock()


def process_text_turn(text: str, block: bool = False) -> str:
    """Text turn for the web UI (no mic)."""
    cleaned = (text or "").strip()
    if not cleaned:
        return ""

    if not turn_lock.acquire(blocking=block):
        raise RuntimeError("Another Jarvis turn is already in progress.")

    try:
        log.info("User said: %s", cleaned)
        reply = call_llm(cleaned)
        log.info("Jarvis: %s", reply)
        return reply
    finally:
        turn_lock.release()

# extra mute after TTS so room echo doesn't trigger STT
POST_SPEECH_MUTE_HOLD = 0.4

# remember last reply to ignore mic picking up jarvis
last_reply: str = ""
last_reply_time: float = 0.0
last_reply_lock = threading.Lock()
ECHO_WINDOW_SECONDS = 6.0
ECHO_MAX_TOKENS = 5

TOKEN_RE = re.compile(r"[a-z0-9']+")


def tokenize(text: str) -> list:
    return TOKEN_RE.findall(text.lower())


def looks_like_echo(transcript: str) -> bool:
    """True if transcript is probably jarvis bleeding into the mic."""
    with last_reply_lock:
        reply = last_reply
        reply_time = last_reply_time

    if not reply:
        return False
    if time.monotonic() - reply_time > ECHO_WINDOW_SECONDS:
        return False

    user_tokens = tokenize(transcript)
    if not user_tokens or len(user_tokens) > ECHO_MAX_TOKENS:
        return False

    reply_tokens = set(tokenize(reply))
    return all(tok in reply_tokens for tok in user_tokens)


def process_turn(text: str) -> None:
    global last_reply, last_reply_time

    if not turn_lock.acquire(blocking=False):
        log.info("Skipping new turn — previous turn still in progress.")
        return
    try:
        log.info("User said: %s", text)
        try:
            reply = call_llm(text)
        except Exception as e:
            log.exception("LLM call failed: %s", e)
            reply = "Sorry, something went wrong handling that."

        if not reply:
            log.info("LLM produced no spoken reply.")
            return

        log.info("Jarvis: %s", reply)

        with last_reply_lock:
            last_reply = reply
            last_reply_time = time.monotonic()

        # mute mic while jarvis talks so we don't loop
        stt.mute()
        try:
            tts.say(reply, wait=True, wait_timeout=30.0)
        except Exception as e:
            log.exception("TTS playback failed: %s", e)
        finally:
            time.sleep(POST_SPEECH_MUTE_HOLD)
            with last_reply_lock:
                last_reply_time = time.monotonic()
            stt.unmute()
    finally:
        turn_lock.release()


def handle_final(text: str) -> None:
    """STT finished a phrase — don't block here."""
    if not text or not text.strip():
        return
    if stt.is_muted:
        log.debug("Dropping transcript received while muted: %s", text)
        return

    cleaned = text.strip()
    if looks_like_echo(cleaned):
        log.info("Dropping suspected echo of Jarvis's reply: %s", cleaned)
        return

    threading.Thread(
        target=process_turn,
        args=(cleaned,),
        name="JarvisTurn",
        daemon=True,
    ).start()


stt.on_final = handle_final


if __name__ == "__main__":
    try:
        tts.start()
        tts.say("Hello Niloy, What's the plan today", wait=True, wait_timeout=30.0)
        stt.start()
        log.info("Jarvis is listening. Press Ctrl-C to stop.")
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        log.info("Shutting down...")
    finally:
        try:
            stt.stop()
            log.info("Health snapshot: %s", stt.get_health())
        except Exception:
            log.exception("Error stopping STT")
        try:
            tts.stop()
        except Exception:
            log.exception("Error stopping TTS")
