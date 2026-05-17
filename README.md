# MyJarvis

MyJarvis is my local AI desktop assistant. I wanted to build something that feels closer to a real personal assistant than a normal chatbot: I can talk to it, it can talk back, it can control parts of my Mac, search through my own files, and use tools like Spotify.

The main idea is simple: keep the assistant local to my laptop, but still give it useful agent abilities. The UI is a desktop app, the backend runs on my machine, and the agent can decide when it needs to call a tool instead of just replying with text.

## What It Can Do

Right now MyJarvis can:

- listen through the microphone and respond with voice
- answer typed messages from the desktop UI
- control Spotify playback, playlists, queue, pause/resume, and song search
- open apps, browsers, files, and folders on my Mac
- create, rename, and copy files/folders
- search my local knowledge base made of PDFs, text files, and markdown files
- follow saved study/work setup steps from the knowledge base
- rebuild its knowledge index when I add new files
- run as a local FastAPI backend or as a packaged Mac desktop app

There are more smaller tools inside the project too, but the interesting part is how they are connected to the agent. I can ask for something in normal language, and the model decides whether it should answer directly or call one of the tools. If I save a workflow in the knowledge base, like "study mode" or "work mode", Jarvis can read those steps and then open the right apps, create the needed folders/files, and set up the environment for me.

## Why I Built It

I wanted this project to be more than another chat UI around an API. A lot of assistant projects stop at "send prompt, get answer." MyJarvis is different because it connects speech, tool calling, local automation, and personal documents into one system.

It is also useful for me personally. I can use it as a voice assistant for music, local files, notes, study documents, and quick Mac actions.

## Architecture

The project has four main parts:

### 1. Desktop Frontend

The frontend is built with React and Vite, then wrapped with Electron so it can run like a normal Mac app.

The UI talks to the local backend through HTTP endpoints like:

- `/chat`
- `/health`
- `/voice/start`
- `/voice/stop`
- `/voice/toggle-mute`

The frontend also shows runtime status, activity logs, voice mode state, and whether the backend is online. Pressing the space bar in voice mode toggles mic mute/unmute.

### 2. Local FastAPI Backend

`server.py` is the bridge between the desktop app and the assistant runtime. It exposes the API used by the frontend and starts/stops the voice system.

I kept this backend local-only because the project needs access to my microphone, speakers, Spotify auth, and macOS automation. Moving it fully to the cloud would make the most interesting parts harder or impossible without a local helper.

### 3. LangGraph Agent

`agent.py` is the core assistant. It uses LangGraph to create a loop like this:

1. user message comes in
2. model decides whether to answer or call a tool
3. tool runs if needed
4. tool result goes back to the model
5. final response is returned or spoken

This is the part that makes it feel like an agent instead of just a chatbot. The assistant has access to tools for Spotify, device actions, and local knowledge search, so it can actually do things.

### 4. Voice Pipeline

The voice system has two parts:

- `stt.py` streams microphone audio to Deepgram for speech-to-text
- `tts.py` streams Deepgram text-to-speech audio back to the local speaker

The assistant also has echo handling so it does not keep hearing itself after it speaks. When Jarvis talks, the mic gets muted for a short time, then turns back on.

## Local Knowledge Base

The knowledge system lives in `tools/knowledgeTool.py`. It reads files from `knowledge-base/`, splits them into chunks, builds a Chroma vector index, and combines vector search with BM25 search.

It can use local hash embeddings, Hugging Face embeddings, or OpenAI embeddings depending on the environment. I also added reranking with FlashRank when available.

This is not only for Q&A. I can also put instructions in there for how I want a study session, coding session, or work session to start. For example, a file can say which apps to open, which folders to create, which notes to pull up, or what order to follow. When I ask Jarvis to start that mode, it searches the knowledge base first, finds the saved steps, and then uses its local tools to actually do them.

That makes the knowledge base feel more like memory plus automation. It is not just storing facts; it can store routines that Jarvis can follow on my Mac.

## Tech Stack

Main tools used:

- Python
- FastAPI
- LangGraph / LangChain
- OpenAI
- Deepgram STT/TTS
- Chroma
- BM25 + FlashRank
- Spotipy
- React
- Vite
- Electron
- macOS automation through `open` and `osascript`

## Running It

### Backend only

From the project root:

```bash
uv run uvicorn server:app --host 127.0.0.1 --port 8000
```

### Frontend in browser

```bash
cd frontend
npm run dev
```

Then open:

```text
http://127.0.0.1:5173
```

### Electron desktop app

```bash
cd frontend
npm run app
```

### Build the clickable Mac app

```bash
cd frontend
npm run package:mac
```

The app will be created at:

```text
frontend/release/mac-arm64/MyJarvis.app
```

## Environment Variables

The project expects a `.env` file with keys for the services I use.

Common ones:

```text
OPENAI_API_KEY=
DpGram_API_KEY=
DEEPGRAM_API_KEY=
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
REDIRECT_URI=
```

## Project Structure

```text
MyJarvis/
  agent.py                  # main LangGraph agent
  server.py                 # local FastAPI backend
  stt.py                    # streaming speech-to-text
  tts.py                    # streaming text-to-speech
  audioManager.py           # macOS volume helper
  tools/
    spotifyTool.py          # Spotify actions
    deviceTool.py           # local Mac/file actions
    knowledgeTool.py        # local document search
  knowledge-base/           # my local notes/docs
  frontend/
    src/                    # React UI
    electron/               # Electron app wrapper
```

## Current Status

This project is still in progress, but the main system is already working:

- desktop UI is working
- local backend is working
- voice mode is working
- Spotify tools are working
- local device tools are working
- knowledge-base search is working
- Mac app packaging is working

Things I still want to improve:

- better app icon and packaged app polish
- more reliable startup flow
- more structured results in the UI
- tests for the backend tools
- more desktop actions

## What I Learned

This project taught me a lot about building an actual agent system instead of just using an LLM API. The hardest parts were not only the model calls, but the real-time pieces around it: streaming audio, avoiding mic feedback, running local tools safely, keeping the desktop app connected to the backend, and making all of it feel usable.

MyJarvis is basically my attempt at building a personal AI assistant that is actually useful on my own machine.
