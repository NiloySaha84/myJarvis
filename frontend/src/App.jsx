import { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  Bot,
  BrainCircuit,
  CheckCircle2,
  Clock3,
  Cpu,
  Database,
  Loader2,
  Mic,
  MicOff,
  Power,
  RefreshCw,
  Send,
  Server,
  Settings2,
  ShieldCheck,
  TerminalSquare,
  Volume2,
  Wifi,
  WifiOff,
  XCircle,
} from "lucide-react";

const API_BASE_URL = import.meta.env.VITE_JARVIS_API_URL ?? "http://127.0.0.1:8000";
const MAX_ACTIVITY_ITEMS = 10;
const SYSTEM_POLL_INTERVAL_MS = 1000;
const ELECTRON_LOG_POLL_INTERVAL_MS = 2000;

const initialMessages = [
  {
    id: crypto.randomUUID(),
    role: "assistant",
    text: "Jarvis is ready. Send a command or start voice mode.",
    time: "now",
  },
];

const initialActivity = [
  {
    id: crypto.randomUUID(),
    title: "Frontend loaded",
    detail: `Waiting for ${API_BASE_URL}`,
    status: "ready",
    time: "now",
  },
];

function getTimestamp() {
  return new Intl.DateTimeFormat([], {
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date());
}

async function requestJson(path, options) {
  const response = await fetch(`${API_BASE_URL}${path}`, options);
  const payload = await response.json().catch(() => null);

  if (!response.ok) {
    throw new Error(payload?.detail ?? `Request failed with ${response.status}`);
  }

  return payload;
}

function createActivity(title, detail, status = "ready") {
  return {
    id: crypto.randomUUID(),
    title,
    detail,
    status,
    time: getTimestamp(),
  };
}

function formatRate(bytesPerSecond) {
  if (!Number.isFinite(bytesPerSecond) || bytesPerSecond < 0) return "n/a";
  if (bytesPerSecond < 1024) return `${Math.round(bytesPerSecond)} B/s`;
  if (bytesPerSecond < 1024 * 1024) return `${(bytesPerSecond / 1024).toFixed(1)} KB/s`;
  return `${(bytesPerSecond / (1024 * 1024)).toFixed(2)} MB/s`;
}

function formatUptime(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "n/a";
  const total = Math.floor(seconds);
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (days > 0) return `${days}d ${hours}h ${minutes}m`;
  return `${hours}h ${minutes}m`;
}

function App() {
  const [messages, setMessages] = useState(initialMessages);
  const [input, setInput] = useState("");
  const [isThinking, setIsThinking] = useState(false);
  const [isVoiceMode, setIsVoiceMode] = useState(false);
  const [isVoiceBusy, setIsVoiceBusy] = useState(false);
  const [speakReplies, setSpeakReplies] = useState(true);
  const [activityLog, setActivityLog] = useState(initialActivity);
  const [runtimeHealth, setRuntimeHealth] = useState(null);
  const [healthError, setHealthError] = useState("");
  const [systemLive, setSystemLive] = useState(null);
  const [systemError, setSystemError] = useState("");
  const [electronLogLines, setElectronLogLines] = useState([]);
  const [electronLogsError, setElectronLogsError] = useState("");
  const inputRef = useRef(null);

  function pushActivity(item) {
    setActivityLog((current) => [item, ...current].slice(0, MAX_ACTIVITY_ITEMS));
  }

  function updateActivity(id, patch) {
    setActivityLog((current) =>
      current.map((item) => (item.id === id ? { ...item, ...patch } : item)),
    );
  }

  async function refreshHealth({ silent = false } = {}) {
    try {
      const health = await requestJson("/health");
      setRuntimeHealth(health);
      setHealthError("");

      if (!silent) {
        pushActivity(createActivity("Health check", "Backend responded from /health.", "complete"));
      }
    } catch (error) {
      setRuntimeHealth(null);
      setHealthError(error.message);

      if (!silent) {
        pushActivity(createActivity("Health check failed", error.message, "error"));
      }
    }
  }

  async function refreshSystemLive({ silent = true } = {}) {
    try {
      const payload = await requestJson("/system/live");
      setSystemLive(payload.system ?? null);
      setSystemError("");
      if (!silent) {
        pushActivity(createActivity("System snapshot", "Backend responded from /system/live.", "complete"));
      }
    } catch (error) {
      setSystemError(error.message);
      if (!silent) {
        pushActivity(createActivity("System snapshot failed", error.message, "error"));
      }
    }
  }

  async function refreshElectronLogs({ silent = true } = {}) {
    try {
      const payload = await requestJson("/logs/electron?lines=80");
      const lines = Array.isArray(payload.lines) ? payload.lines : [];
      setElectronLogLines(lines);
      setElectronLogsError(payload.exists ? "" : "Electron log file not found yet.");
      if (!silent) {
        pushActivity(createActivity("Electron logs", "Fetched latest Electron log tail.", "complete"));
      }
    } catch (error) {
      setElectronLogsError(error.message);
      if (!silent) {
        pushActivity(createActivity("Electron logs failed", error.message, "error"));
      }
    }
  }

  useEffect(() => {
    refreshHealth({ silent: true });
    const timer = window.setInterval(() => refreshHealth({ silent: true }), 10000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    refreshSystemLive({ silent: true });
    const timer = window.setInterval(() => refreshSystemLive({ silent: true }), SYSTEM_POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    refreshElectronLogs({ silent: true });
    const timer = window.setInterval(
      () => refreshElectronLogs({ silent: true }),
      ELECTRON_LOG_POLL_INTERVAL_MS,
    );
    return () => window.clearInterval(timer);
  }, []);

  const backendOnline = Boolean(runtimeHealth?.ok) && !healthError;

  const statusText = useMemo(() => {
    if (isThinking) return "Running request";
    if (isVoiceMode) return "Voice listener on";
    if (healthError) return "Backend offline";
    return "Backend ready";
  }, [healthError, isThinking, isVoiceMode]);

  const runtimeCards = useMemo(() => {
    const sttHealth = runtimeHealth?.voice?.stt;
    const sttRunning = Boolean(sttHealth?.running);
    const sttMuted = Boolean(runtimeHealth?.voice?.stt_muted);
    const ttsConnected = Boolean(runtimeHealth?.voice?.tts_connected);

    return [
      {
        label: "API",
        value: backendOnline ? "Online" : "Offline",
        detail: backendOnline ? API_BASE_URL : healthError || "No health response yet.",
        status: backendOnline ? "complete" : "error",
        icon: backendOnline ? Wifi : WifiOff,
      },
      {
        label: "STT",
        value: sttRunning ? "Listening" : "Stopped",
        detail: sttRunning
          ? sttMuted
            ? "Muted (press Space to unmute)."
            : "Live mic (press Space to mute)."
          : sttHealth?.uptime_seconds
            ? `Uptime ${sttHealth.uptime_seconds}s`
            : "Starts through voice mode.",
        status: sttRunning ? "running" : "ready",
        icon: sttRunning ? (sttMuted ? MicOff : Mic) : MicOff,
      },
      {
        label: "TTS",
        value: ttsConnected ? "Connected" : "Idle",
        detail: speakReplies ? "Spoken replies enabled." : "Text replies only.",
        status: ttsConnected ? "running" : "ready",
        icon: Volume2,
      },
      {
        label: "Turn Lock",
        value: isThinking ? "Busy" : "Open",
        detail: isThinking ? "Waiting for the current agent turn." : "Ready for the next request.",
        status: isThinking ? "running" : "complete",
        icon: isThinking ? Clock3 : CheckCircle2,
      },
    ];
  }, [backendOnline, healthError, isThinking, runtimeHealth, speakReplies]);

  async function handleVoiceToggle() {
    if (isVoiceBusy) return;

    const nextVoiceMode = !isVoiceMode;
    const endpoint = nextVoiceMode ? "/voice/start" : "/voice/stop";
    const voiceEvent = createActivity(
      nextVoiceMode ? "Starting voice runtime" : "Stopping voice runtime",
      nextVoiceMode ? "Launching STT and TTS in Python." : "Closing microphone and speaker streams.",
      "running",
    );

    setIsVoiceBusy(true);
    pushActivity(voiceEvent);

    try {
      const health = await requestJson(endpoint, { method: "POST" });
      setRuntimeHealth((current) => ({ ...(current ?? {}), ok: true, voice: health.voice }));
      setHealthError("");
      setIsVoiceMode(nextVoiceMode);
      updateActivity(voiceEvent.id, {
        status: "complete",
        detail: nextVoiceMode ? "Voice runtime is listening." : "Voice runtime stopped.",
      });
    } catch (error) {
      updateActivity(voiceEvent.id, { status: "error", detail: error.message });
    } finally {
      setIsVoiceBusy(false);
    }
  }

  async function handleMuteToggle() {
    if (isVoiceBusy || !isVoiceMode) return;

    const muteEvent = createActivity(
      "Voice mute toggle",
      "POST /voice/toggle-mute",
      "running",
    );
    pushActivity(muteEvent);

    try {
      const result = await requestJson("/voice/toggle-mute", { method: "POST" });
      setRuntimeHealth((current) => ({ ...(current ?? {}), ok: true, voice: result.voice }));
      setHealthError("");
      updateActivity(muteEvent.id, {
        status: "complete",
        detail: result.voice?.stt_muted ? "Microphone muted." : "Microphone unmuted.",
      });
    } catch (error) {
      updateActivity(muteEvent.id, { status: "error", detail: error.message });
    }
  }

  useEffect(() => {
    function onGlobalKeyDown(event) {
      if (event.code !== "Space") return;

      const active = document.activeElement;
      const isTypingTarget =
        active &&
        (active.tagName === "INPUT" ||
          active.tagName === "TEXTAREA" ||
          active.isContentEditable);

      if (isTypingTarget) return;
      if (!isVoiceMode || isVoiceBusy) return;

      event.preventDefault();
      handleMuteToggle();
    }

    window.addEventListener("keydown", onGlobalKeyDown);
    return () => window.removeEventListener("keydown", onGlobalKeyDown);
  }, [isVoiceMode, isVoiceBusy, runtimeHealth]);

  async function handleSubmit(event) {
    event.preventDefault();

    const message = input.trim();
    if (!message || isThinking) return;

    const userMessage = {
      id: crypto.randomUUID(),
      role: "user",
      text: message,
      time: getTimestamp(),
    };
    const requestEvent = createActivity(
      "Agent request",
      `POST /chat${speakReplies ? " with speech" : ""}`,
      "running",
    );

    setMessages((current) => [...current, userMessage]);
    pushActivity(requestEvent);
    setInput("");
    setIsThinking(true);

    try {
      const data = await requestJson("/chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ message, speak: speakReplies }),
      });

      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          text: data.reply || "I completed the request.",
          time: getTimestamp(),
        },
      ]);
      updateActivity(requestEvent.id, {
        status: "complete",
        detail: speakReplies ? "Reply returned and spoken." : "Reply returned.",
      });
      refreshHealth({ silent: true });
    } catch (error) {
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          text: error.message,
          time: getTimestamp(),
          error: true,
        },
      ]);
      updateActivity(requestEvent.id, { status: "error", detail: error.message });
    } finally {
      setIsThinking(false);
      inputRef.current?.focus();
    }
  }

  return (
    <main className="min-h-screen overflow-hidden bg-[#030711] text-slate-100">
      <div className="fixed inset-0 jarvis-grid opacity-60" />
      <div className="fixed -left-32 top-20 h-96 w-96 rounded-full bg-cyan-500/20 blur-3xl" />
      <div className="fixed -right-24 bottom-0 h-[28rem] w-[28rem] rounded-full bg-blue-700/20 blur-3xl" />

      <div className="relative mx-auto flex min-h-screen max-w-[1800px] flex-col gap-4 p-4 sm:p-5 lg:p-6">
        <AppHeader
          backendOnline={backendOnline}
          isThinking={isThinking}
          isVoiceMode={isVoiceMode}
          statusText={statusText}
        />

        <TopSystemStats systemLive={systemLive} systemError={systemError} />

        <section className="grid flex-1 grid-cols-1 gap-4 xl:grid-cols-[320px_minmax(0,1fr)_320px]">
          <RuntimePanel
            cards={runtimeCards}
            healthError={healthError}
            onRefresh={() => refreshHealth()}
          />
          <ConversationView
            input={input}
            inputRef={inputRef}
            isThinking={isThinking}
            isVoiceBusy={isVoiceBusy}
            isVoiceMode={isVoiceMode}
            messages={messages}
            onSubmit={handleSubmit}
            onVoiceToggle={handleVoiceToggle}
            setInput={setInput}
            setSpeakReplies={setSpeakReplies}
            speakReplies={speakReplies}
          />
          <ActivityPanel
            events={activityLog}
            electronLogLines={electronLogLines}
            electronLogsError={electronLogsError}
            isThinking={isThinking}
            isVoiceMode={isVoiceMode}
          />
        </section>
      </div>
    </main>
  );
}

function AppHeader({ backendOnline, statusText, isThinking, isVoiceMode }) {
  return (
    <header className="glass-panel flex flex-col gap-4 px-5 py-4 lg:flex-row lg:items-center lg:justify-between">
      <div className="flex items-center gap-4">
        <div className="relative grid h-12 w-12 place-items-center rounded-2xl border border-cyan-300/40 bg-cyan-300/10 shadow-[0_0_35px_rgba(34,211,238,0.35)]">
          <Bot className="h-6 w-6 text-cyan-200" />
          <span className="absolute -right-1 -top-1 h-3 w-3 rounded-full bg-emerald-300 shadow-[0_0_16px_rgba(110,231,183,0.9)]" />
        </div>
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.45em] text-cyan-200/80">
            MyJarvis
          </p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-white">
            Desktop Assistant Console
          </h1>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3 text-sm text-slate-300">
        <StatusPill icon={ShieldCheck} label="Localhost only" />
        <StatusPill icon={backendOnline ? Server : WifiOff} label={statusText} active={isThinking} />
        <StatusPill
          icon={isVoiceMode ? Mic : MicOff}
          label={isVoiceMode ? "Voice listening" : "Voice paused"}
          active={isVoiceMode}
        />
        <StatusPill icon={Activity} label="Tool calling enabled" />
      </div>
    </header>
  );
}

function StatusPill({ icon: Icon, label, active = false }) {
  return (
    <div className="flex items-center gap-2 rounded-full border border-cyan-200/15 bg-white/[0.04] px-3 py-2">
      <Icon className={`h-4 w-4 ${active ? "animate-pulse text-cyan-200" : "text-cyan-300"}`} />
      <span>{label}</span>
    </div>
  );
}

function TopSystemStats({ systemLive, systemError }) {
  const cpuPercent = Number(systemLive?.cpu?.percent ?? NaN);
  const memoryPercent = Number(systemLive?.memory?.percent ?? NaN);
  const diskPercent = Number(systemLive?.disk?.percent ?? NaN);
  const cpuStatus = Number.isFinite(cpuPercent) && cpuPercent >= 85 ? "error" : "running";
  const memoryStatus = Number.isFinite(memoryPercent) && memoryPercent >= 85 ? "error" : "running";
  const diskStatus = Number.isFinite(diskPercent) && diskPercent >= 90 ? "error" : "running";

  const cards = [
    {
      label: "CPU",
      value: Number.isFinite(cpuPercent) ? `${cpuPercent.toFixed(1)}%` : "n/a",
      detail: systemLive
        ? `Load(1m) ${systemLive?.cpu?.load_avg?.["1m"] ?? "n/a"} • ${systemLive?.cpu?.logical_cores ?? "n/a"} cores`
        : systemError || "Waiting for live system metrics...",
      status: systemLive ? cpuStatus : "ready",
      icon: Cpu,
    },
    {
      label: "Memory",
      value: Number.isFinite(memoryPercent) ? `${memoryPercent.toFixed(1)}%` : "n/a",
      detail: systemLive
        ? `${systemLive?.memory?.used_gb ?? "n/a"}GB / ${systemLive?.memory?.total_gb ?? "n/a"}GB in use`
        : systemError || "Waiting for live system metrics...",
      status: systemLive ? memoryStatus : "ready",
      icon: Database,
    },
    {
      label: "Disk",
      value: Number.isFinite(diskPercent) ? `${diskPercent.toFixed(1)}%` : "n/a",
      detail: systemLive
        ? `${systemLive?.disk?.used_gb ?? "n/a"}GB / ${systemLive?.disk?.total_gb ?? "n/a"}GB used`
        : systemError || "Waiting for live system metrics...",
      status: systemLive ? diskStatus : "ready",
      icon: Server,
    },
    {
      label: "Network",
      value: systemLive
        ? `↑ ${formatRate(systemLive?.network?.upload_bps)} • ↓ ${formatRate(systemLive?.network?.download_bps)}`
        : "n/a",
      detail: systemLive
        ? `${systemLive?.host?.hostname ?? "unknown host"} • Uptime ${formatUptime(systemLive?.uptime_seconds)} • stale ${systemLive?.stale_ms ?? 0}ms`
        : systemError || "Waiting for live system metrics...",
      status: systemLive ? "running" : "ready",
      icon: Activity,
    },
  ];

  return (
    <section className="glass-panel px-5 py-4">
      <div className="mb-3 flex items-center gap-2 text-sm font-medium text-white">
        <Cpu className="h-4 w-4 text-cyan-200" />
        System stats
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {cards.map((card) => (
          <div key={card.label} className="min-w-0">
            <RuntimeCard {...card} />
          </div>
        ))}
      </div>
      {!systemLive && systemError && (
        <div className="mt-3 rounded-2xl border border-red-300/20 bg-red-500/10 p-3 text-xs text-red-100">
          {systemError}
        </div>
      )}
    </section>
  );
}

function RuntimePanel({ cards, healthError, onRefresh }) {
  return (
    <aside className="glass-panel panel-height order-2 flex flex-col p-4 xl:order-1">
      <div className="mb-3 flex items-center justify-between">
        <Cpu className="h-5 w-5 text-cyan-200" />
        <button
          aria-label="Refresh backend health"
          className="rounded-full border border-cyan-200/15 bg-white/[0.04] p-2 text-cyan-100 transition hover:border-cyan-200/35"
          type="button"
          onClick={onRefresh}
        >
          <RefreshCw className="h-4 w-4" />
        </button>
      </div>
      <PanelTitle title="Runtime" subtitle="Backend status" />

      <div className="mt-5 grid gap-3">
        {cards.map((card) => (
          <RuntimeCard key={card.label} {...card} />
        ))}
      </div>

      <div className="mt-auto rounded-3xl border border-cyan-200/10 bg-cyan-200/[0.03] p-4">
        <p className="text-xs uppercase tracking-[0.3em] text-cyan-200/70">Endpoint</p>
        <p className="mt-3 break-words text-sm leading-6 text-slate-300">
          {healthError || `${API_BASE_URL}/health`}
        </p>
      </div>
    </aside>
  );
}

function ConversationView({
  messages,
  input,
  setInput,
  inputRef,
  isThinking,
  isVoiceMode,
  isVoiceBusy,
  speakReplies,
  setSpeakReplies,
  onVoiceToggle,
  onSubmit,
}) {
  return (
    <section className="glass-panel panel-height order-1 flex min-h-[720px] flex-col overflow-hidden xl:order-2">
      <div className="relative border-b border-cyan-200/10 px-5 py-5">
        <div className="absolute left-1/2 top-4 hidden -translate-x-1/2 lg:block">
          <AssistantCore isThinking={isThinking} />
        </div>
        <div className="max-w-md">
          <p className="text-xs font-semibold uppercase tracking-[0.35em] text-cyan-200/70">
            Conversation
          </p>
          <h2 className="mt-2 text-xl font-semibold text-white">Send a command</h2>
          <p className="mt-3 max-w-sm text-sm leading-6 text-slate-400">
            Type a request, or start voice mode to use the microphone pipeline.
            While voice mode is running, press Space to mute or unmute the mic.
          </p>
        </div>
      </div>

      <div className="flex justify-center border-b border-cyan-200/10 py-6 lg:hidden">
        <AssistantCore isThinking={isThinking} />
      </div>

      <div className="scroll-soft flex-1 space-y-4 overflow-y-auto px-4 py-5 sm:px-6">
        {messages.map((message) => (
          <MessageBubble key={message.id} message={message} />
        ))}

        {isThinking && (
          <div className="flex items-center gap-3 rounded-3xl border border-cyan-200/15 bg-cyan-200/[0.04] p-4 text-sm text-cyan-100">
            <Loader2 className="h-4 w-4 animate-spin" />
            Waiting for the agent response...
          </div>
        )}
      </div>

      <form onSubmit={onSubmit} className="border-t border-cyan-200/10 p-4 sm:p-5">
        <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <button
            className={`flex items-center justify-center gap-2 rounded-2xl border px-4 py-3 text-sm font-medium transition ${
              isVoiceMode
                ? "border-cyan-200/40 bg-cyan-300/15 text-cyan-100 shadow-[0_0_28px_rgba(34,211,238,0.22)]"
                : "border-cyan-200/15 bg-white/[0.035] text-slate-300 hover:border-cyan-200/30 hover:text-cyan-100"
            }`}
            disabled={isVoiceBusy}
            type="button"
            onClick={onVoiceToggle}
          >
            {isVoiceBusy ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : isVoiceMode ? (
              <Mic className="h-4 w-4" />
            ) : (
              <Power className="h-4 w-4" />
            )}
            {isVoiceMode ? "Stop voice mode" : "Start voice mode"}
          </button>

          <label className="flex cursor-pointer items-center justify-between gap-3 rounded-2xl border border-cyan-200/15 bg-white/[0.035] px-4 py-3 text-sm text-slate-300">
            <span className="flex items-center gap-2">
              <Volume2 className="h-4 w-4 text-cyan-200" />
              Speak typed replies
            </span>
            <input
              checked={speakReplies}
              className="h-4 w-4 accent-cyan-300"
              type="checkbox"
              onChange={(event) => setSpeakReplies(event.target.checked)}
            />
          </label>
        </div>

        <div className="flex items-end gap-3 rounded-3xl border border-cyan-200/20 bg-slate-950/70 p-2 shadow-[inset_0_0_30px_rgba(34,211,238,0.05)]">
          <button
            aria-label={isVoiceMode ? "Stop voice mode" : "Start voice mode"}
            className={`grid h-12 w-12 shrink-0 place-items-center rounded-2xl border transition ${
              isVoiceMode
                ? "border-cyan-200/40 bg-cyan-300/15 text-cyan-100"
                : "border-cyan-200/15 bg-cyan-200/[0.05] text-cyan-200"
            }`}
            disabled={isVoiceBusy}
            type="button"
            onClick={onVoiceToggle}
          >
            {isVoiceBusy ? (
              <Loader2 className="h-5 w-5 animate-spin" />
            ) : isVoiceMode ? (
              <Mic className="h-5 w-5" />
            ) : (
              <MicOff className="h-5 w-5" />
            )}
          </button>
          <textarea
            ref={inputRef}
            value={input}
            className="min-h-12 flex-1 resize-none bg-transparent px-1 py-3 text-base text-slate-100 outline-none placeholder:text-slate-500"
            placeholder="Ask Jarvis to play music, open apps, search notes..."
            rows={1}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
          />
          <button
            aria-label="Send message"
            className="group grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-cyan-300 text-slate-950 transition hover:bg-white disabled:cursor-not-allowed disabled:opacity-40"
            disabled={isThinking || !input.trim()}
            type="submit"
          >
            {isThinking ? (
              <Loader2 className="h-5 w-5 animate-spin" />
            ) : (
              <Send className="h-5 w-5 transition group-hover:translate-x-0.5" />
            )}
          </button>
        </div>
      </form>
    </section>
  );
}

function ActivityPanel({ events, isThinking, isVoiceMode, electronLogLines, electronLogsError }) {
  return (
    <aside className="glass-panel panel-height order-3 flex flex-col p-4">
      <TerminalSquare className="mb-3 h-5 w-5 text-cyan-200" />
      <PanelTitle title="Activity" subtitle="Request log" />

      <div className="mt-5 space-y-3">
        {events.map((event) => (
          <ActivityItem key={event.id} event={event} />
        ))}
      </div>

      <div className="mt-4 rounded-3xl border border-cyan-200/10 bg-slate-950/60 p-4">
        <div className="mb-2 flex items-center justify-between">
          <p className="text-xs uppercase tracking-[0.3em] text-cyan-200/70">Electron logs</p>
          <span className="text-[11px] text-slate-500">live tail</span>
        </div>
        {electronLogsError ? (
          <p className="text-xs text-red-200">{electronLogsError}</p>
        ) : (
          <div className="max-h-44 overflow-y-auto rounded-xl border border-cyan-200/10 bg-black/30 p-2 font-mono text-[11px] leading-5 text-cyan-100/90">
            {electronLogLines.length > 0 ? (
              electronLogLines.map((line, index) => (
                <div key={`${index}-${line.slice(0, 24)}`} className="whitespace-pre-wrap break-words">
                  {line}
                </div>
              ))
            ) : (
              <div className="text-slate-500">No log lines yet.</div>
            )}
          </div>
        )}
      </div>

      <div className="mt-auto rounded-3xl border border-cyan-200/10 bg-slate-950/60 p-4">
        <div className="flex items-center justify-between">
          <p className="text-xs uppercase tracking-[0.3em] text-cyan-200/70">Status</p>
          <span
            className={`h-2.5 w-2.5 rounded-full ${
              isThinking || isVoiceMode ? "animate-ping bg-cyan-300" : "bg-emerald-300"
            }`}
          />
        </div>
        <p className="mt-3 text-sm leading-6 text-slate-300">
          {isVoiceMode
            ? "Voice mode is streaming microphone input through the Python backend."
            : "Text requests stay available even when the voice runtime is stopped."}
        </p>
      </div>
    </aside>
  );
}

function AssistantCore({ isThinking }) {
  return (
    <div className="relative grid h-40 w-40 place-items-center">
      <div className="absolute inset-0 rounded-full border border-cyan-200/20" />
      <div className="absolute inset-4 rounded-full border border-cyan-200/25" />
      <div className="absolute inset-8 rounded-full border border-blue-300/20" />
      <div className={`absolute inset-0 rounded-full bg-cyan-300/10 blur-xl ${isThinking ? "animate-pulse" : ""}`} />
      <div className="jarvis-ring absolute inset-2 rounded-full" />
      <div className="grid h-20 w-20 place-items-center rounded-full border border-cyan-100/50 bg-cyan-200/15 shadow-[0_0_55px_rgba(103,232,249,0.55)]">
        <BrainCircuit className="h-9 w-9 text-cyan-100" />
      </div>
    </div>
  );
}

function MessageBubble({ message }) {
  const isUser = message.role === "user";

  return (
    <article className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] rounded-3xl border p-4 shadow-lg sm:max-w-[72%] ${
          isUser
            ? "border-blue-300/20 bg-blue-500/15"
            : message.error
              ? "border-red-300/20 bg-red-500/10"
              : "border-cyan-200/20 bg-cyan-200/[0.06]"
        }`}
      >
        <div className="mb-2 flex items-center gap-2 text-xs uppercase tracking-[0.22em] text-slate-400">
          {isUser ? <TerminalSquare className="h-3.5 w-3.5" /> : <Bot className="h-3.5 w-3.5" />}
          <span>{isUser ? "You" : "Jarvis"}</span>
          <span className="tracking-normal text-slate-500">{message.time}</span>
        </div>
        <p className="whitespace-pre-wrap text-[15px] leading-7 text-slate-100">{message.text}</p>
      </div>
    </article>
  );
}

function PanelTitle({ title, subtitle }) {
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-[0.35em] text-cyan-200/70">
        {subtitle}
      </p>
      <h2 className="mt-2 text-lg font-semibold text-white">{title}</h2>
    </div>
  );
}

function RuntimeCard({ label, value, detail, status, icon: Icon }) {
  const statusStyles = {
    ready: "border-cyan-200/10 bg-white/[0.035] text-cyan-200",
    running: "border-blue-200/20 bg-blue-400/10 text-blue-100",
    complete: "border-emerald-200/20 bg-emerald-400/10 text-emerald-100",
    error: "border-red-200/20 bg-red-500/10 text-red-100",
  };

  return (
    <div className={`rounded-3xl border p-4 ${statusStyles[status] ?? statusStyles.ready}`}>
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-white">{label}</p>
          <p className="mt-1 text-xs uppercase tracking-[0.25em]">{value}</p>
        </div>
        <div className="grid h-10 w-10 place-items-center rounded-2xl border border-cyan-200/15 bg-cyan-200/[0.05]">
          <Icon className="h-5 w-5 text-cyan-200" />
        </div>
      </div>
      <p className="mt-4 break-words text-sm leading-6 text-slate-400">{detail}</p>
    </div>
  );
}

function ActivityItem({ event }) {
  const styles = {
    ready: "border-cyan-200/10 bg-white/[0.035] text-cyan-200",
    running: "border-blue-200/20 bg-blue-400/10 text-blue-100",
    complete: "border-emerald-200/20 bg-emerald-400/10 text-emerald-100",
    error: "border-red-200/20 bg-red-400/10 text-red-100",
  };

  return (
    <div className={`rounded-3xl border p-4 ${styles[event.status] ?? styles.ready}`}>
      <div className="flex items-center gap-3">
        <div className="grid h-9 w-9 place-items-center rounded-2xl bg-white/5">
          {event.status === "running" ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : event.status === "error" ? (
            <XCircle className="h-4 w-4" />
          ) : event.status === "complete" ? (
            <CheckCircle2 className="h-4 w-4" />
          ) : (
            <Settings2 className="h-4 w-4" />
          )}
        </div>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <p className="truncate text-sm font-medium text-white">{event.title}</p>
            <span className="shrink-0 text-[11px] uppercase tracking-[0.18em] text-slate-500">
              {event.time}
            </span>
          </div>
          <p className="mt-1 break-words text-xs leading-5 text-slate-400">{event.detail}</p>
        </div>
      </div>
    </div>
  );
}

export default App;
