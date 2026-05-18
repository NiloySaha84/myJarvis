# MyJarvis

MyJarvis is a local AI desktop assistant built to feel closer to a real operating-system companion than a traditional chatbot. It listens, speaks, reasons through tasks, searches personal knowledge, controls parts of my Mac, and executes actions through tools.

The core of the project is not the UI or the voice stack alone — it is the **agent architecture** inside `agent.py`. That is where natural language becomes decisions, tool execution, multi-step reasoning, and spoken responses.

## Live Demo: https://niloy-saha84-github-io.vercel.app/myJarvis.mp4

---

# Core Architecture

At the center of MyJarvis is a **LangGraph agent loop** powered by **OpenAI (`gpt-4o-mini`)**.

The model is connected to a controlled set of tools and runs inside a reasoning loop that allows it to:

- decide when tools are needed
- execute one or multiple tools
- read tool outputs
- continue reasoning
- produce a final spoken or typed response

Instead of a single LLM call, MyJarvis behaves like a persistent decision-making system.

## Agent Execution Loop

```text
START → agent (LLM) → should_continue?
                          ├─ tool_calls? → tools → agent
                          └─ no tools   → END
```

### Flow

1. A user message enters the graph through `AgentState.messages`
2. `model_call()` invokes the LLM with:
  - system instructions
  - conversation history
  - available tools
3. The graph checks whether the model requested any tool calls
4. If tools are requested:
  - `ToolNode` executes them
  - results are appended as `ToolMessage`
5. The graph loops back into the LLM so it can reason over tool output
6. The cycle repeats until the model returns a normal response without pending tools
7. `extract_final_text()` retrieves the final assistant reply for the UI or TTS

This architecture allows **multi-step execution chains** inside a single turn.

For example, Jarvis can:

```text
query knowledge base
    → retrieve saved workflow
        → open apps
        → start music
        → organize windows
        → respond verbally
```

---

# Voice-First System Design

MyJarvis is designed primarily as a **voice assistant**, not a text chatbot.

The system prompt heavily shapes behavior:

- replies stay short and conversational
- responses are optimized for speech
- the model must use tools for real-world actions
- the assistant cannot pretend an action succeeded without a tool result
- saved workflows must be retrieved from the knowledge base before execution

This keeps interactions natural while maintaining reliable tool behavior.

---

# Retrieval-Augmented Knowledge Base (RAG)

One of the most important parts of the project is the local knowledge system in `tools/knowledgeTool.py`.

The assistant can search through personal files and use retrieved information as executable context.

## Knowledge Pipeline

Files inside `knowledge-base/` are:

1. loaded
2. chunked
3. embedded
4. stored in a local **Chroma vector database**

Retrieval combines multiple ranking methods:

- semantic vector similarity
- BM25 keyword retrieval
- optional FlashRank reranking

The reranking stage improves retrieval quality by reordering candidate chunks based on relevance instead of relying only on embedding distance.

This produces significantly better results for:

- saved workflows
- setup instructions
- study notes
- project documentation
- personal routines

## Executable Workflows

The knowledge base is not treated as passive memory.

The system prompt instructs the agent to:

1. search the knowledge base first
2. retrieve instructions/workflows
3. execute them step-by-step using tools

This allows MyJarvis to create complete environments automatically.

For example:

- “Start study mode”
- “Set up my work environment”
- “Open my AI research setup”

If the steps exist in the knowledge base, Jarvis can:

- open applications
- launch browsers/tabs
- organize files
- start Spotify playlists
- configure workflows
- continue executing actions sequentially

The result feels much closer to a real assistant than a Q&A chatbot.

---

# Streaming Voice Pipeline

The assistant operates through a fully streaming speech pipeline.

## Speech-to-Text (STT)

`stt.py` streams microphone audio to **Deepgram** in real time.

Pipeline:

```text
Microphone → Deepgram STT → final transcript
```

Final transcripts are sent into the LangGraph agent asynchronously.

## Text-to-Speech (TTS)

`tts.py` streams generated speech back through **Deepgram TTS**:

```text
LLM reply → Deepgram TTS → speaker output
```

Speech playback is streamed incrementally for low latency.

---

# Voice Interaction Engineering

Building a reliable voice assistant required solving several real-world interaction problems.

## Echo Prevention

Without safeguards, the assistant would hear its own voice and recursively respond to itself.

MyJarvis includes:

- microphone muting during TTS playback
- post-speech hold timing
- transcript filtering
- recent-response similarity checks

Short transcripts matching Jarvis’s own reply are automatically ignored.

---

# Concurrency and Turn Safety

Voice and UI requests share the same underlying agent.

To prevent overlapping executions:

- a global `turn_lock` ensures only one active agent turn exists
- simultaneous requests are skipped or rejected
- conversation history is shared across turns

This avoids:

- conflicting tool execution
- overlapping TTS playback
- race conditions in the graph loop

## Locking model (pessimistic, not optimistic)

MyJarvis uses **pessimistic** concurrency control: shared resources are guarded *before* work runs, not retried after a conflict is detected.

This is **not** optimistic locking (read → work without a lock → commit only if nothing changed → retry on conflict).

| Layer | Mechanism | Role |
|-------|-----------|------|
| **Agent** (`agent.py`) | `turn_lock` (`threading.Lock`) | Only one LLM/tool turn at a time; voice turns skip if busy, text `/chat` can reject with `409` |
| **Agent** | `history_lock`, `last_reply_lock` | Safe updates to conversation history and echo-filter state |
| **TTS** (`tts.py`) | `send_lock` | One Deepgram TTS sender at a time |
| **TTS** | `Speaker.lock`, `flush_lock`, `metrics_lock` | Safe speaker startup, flush counting, and metrics |
| **STT** (`stt.py`) | `mute_event`, `stop_event` | Cooperative gating: mic audio is dropped while muted or stopped (not a version/retry model) |

STT does not use optimistic locking either; it uses **event-based synchronization** so the mic callback never sends audio while Jarvis is speaking or the stream is shutting down.

---

# Desktop Architecture

## Frontend

The desktop interface is built with:

- React
- Vite
- Electron

The UI communicates with the local backend through FastAPI endpoints such as:

```text
/chat
/voice/start
/voice/stop
/voice/toggle-mute
```

The frontend provides:

- live conversation display
- runtime status
- voice controls
- activity logging
- backend metrics visibility via `/metrics`

---

# Local Backend

`server.py` acts as the bridge between:

- the UI
- the voice runtime
- the LangGraph agent

The backend stays fully local because the assistant depends on:

- microphone access
- speakers
- Spotify authentication
- macOS automation
- local file access

The backend now also exposes an operational metrics snapshot endpoint:

```text
/metrics
```

This is useful when debugging latency spikes, tool failures, or voice-runtime issues.

---

# Monitoring and Metrics

I've included lightweight in-process monitoring across the runtime. Metrics are designed for local debugging and performance visibility, not for external telemetry systems.

## Metrics Endpoint

`GET /metrics` returns a full snapshot:

- `api` - FastAPI request counters and HTTP/WebSocket latency
- `agent` - turn counters, tool-call counters, lock contention, and LLM timing
- `stt` - Deepgram STT health plus stream/message counters
- `tts` - Deepgram TTS health plus speak/flush/audio counters
- `knowledge` - index rebuild/query counters and retrieval latencies
- `spotify` - per-tool call/success/error counts
- `device` - local desktop/file tool call/success/error counts
- `news` - News API call/error/article counters

## What is monitored

### API (`server.py`)

- `chat_requests_total`, `chat_requests_success`, `chat_requests_error`, `chat_requests_conflict`
- `voice_start_requests`, `voice_stop_requests`, `voice_toggle_mute_requests`
- `websocket_messages_received`, `websocket_turn_success`, `websocket_turn_error`
- `http_last_latency_ms`, `http_avg_latency_ms`
- `websocket_last_turn_latency_ms`, `websocket_avg_turn_latency_ms`

### Agent Loop (`agent.py`)

- LLM flow: `llm_requests_started`, `llm_requests_completed`, `llm_empty_replies`
- Tool flow: `tool_calls_requested`, `tool_results_received`
- Turn flow: text/voice turn counts, failures, busy-lock skips
- Timing: `llm_last_latency_ms`, `llm_avg_latency_ms`, `turn_last_latency_ms`, `turn_avg_latency_ms`
- Safety counters: muted transcript drops, echo drops, TTS mute/unmute transitions

### Voice Runtime (`stt.py`, `tts.py`)

- STT already tracks connection lifecycle, transcripts, audio chunks, mic warnings, and errors in `stt.get_health()`
- TTS now tracks connection lifecycle, say requests, flush events, audio chunks, and wait timeouts in `tts.get_health()`

### Knowledge + Tooling

- `knowledgeTool.py`: index builds/rebuild triggers, retriever mode (with/without reranker), query counts, and build/query latency
- `spotifyTool.py`: per-method call/success/error/no-device/validation counters
- `deviceTool.py`: per-method call/success/error/validation counters
- `newsTool.py`: call/success/error/article counters

## How to use it quickly

Run backend:

```bash
uv run uvicorn server:app --host 127.0.0.1 --port 8000
```

Then inspect metrics:

```bash
curl http://127.0.0.1:8000/metrics
```

You can also compare `/health` (runtime readiness) and `/metrics` (runtime behavior) during debugging.

---

# Tool-Using Agent

The agent has access to tools for capabilities such as:

- Spotify control
- macOS automation
- file and folder operations
- browser/app launching
- local knowledge retrieval
- workflow execution

Tools are implemented as LangChain `@tool` functions and executed through LangGraph’s `ToolNode`.

The important part is not the tools themselves, but the agent’s ability to reason about:

- when to use them
- in what order
- how to continue after receiving results

---

# End-to-End Voice Flow

```text
Mic
 → Deepgram STT
 → transcript
 → LangGraph agent loop
 → tool execution
 → final response
 → Deepgram TTS
 → speaker
```

---

# Tech Stack

## Backend / AI

- Python
- FastAPI
- LangGraph
- LangChain
- OpenAI
- ChromaDB
- BM25 retrieval
- FlashRank reranking

## Voice

- Deepgram STT
- Deepgram TTS

## Desktop

- React
- Vite
- Electron

## Integrations

- Spotipy
- macOS automation (`open`, `osascript`)

---

# Running the Project

## Backend

```bash
uv run uvicorn server:app --host 127.0.0.1 --port 8000
```

## Frontend

```bash
cd frontend
npm run dev
```

Open:

```text
http://127.0.0.1:5173
```

## Electron Desktop App

```bash
cd frontend
npm run app
```

## Package macOS App

```bash
cd frontend
npm run package:mac
```

Output:

```text
frontend/release/mac-arm64/MyJarvis.app
```

---

# Environment Variables

Create a `.env` file:

```text
OPENAI_API_KEY=
DEEPGRAM_API_KEY=
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
REDIRECT_URI=
```

---

# Project Structure

```text
MyJarvis/
  agent.py
  server.py
  stt.py
  tts.py
  audioManager.py

  tools/
    spotifyTool.py
    deviceTool.py
    knowledgeTool.py

  knowledge-base/

  frontend/
    src/
    electron/
```

---

# Current Status

## Working

- LangGraph agent loop
- multi-step tool execution
- streaming STT/TTS voice pipeline
- local RAG knowledge base
- reranking retrieval pipeline
- desktop UI + Electron app
- Spotify and macOS integrations
- workflow execution from retrieved knowledge

## In Progress

- packaged app polish
- richer structured frontend outputs
- startup reliability improvements
- expanded desktop automation
- automated testing for tools and agent turns

---

# What This Project Explores

The most interesting challenge was not connecting APIs — it was building a system where:

- retrieval
- reasoning
- tool execution
- concurrency
- voice interaction
- and memory-like workflows

all work together inside one continuous agent loop.

MyJarvis is an attempt to build a local assistant that can actually operate as part of a real desktop workflow instead of only generating text.