import os
import time
import threading
import logging
from collections import defaultdict

import numpy as np
import sounddevice as sd
from dotenv import load_dotenv

from deepgram import DeepgramClient
from deepgram.core.events import EventType

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

load_dotenv()

STT_API_KEY = os.getenv("DpGram_API_KEY")
STT_MODEL = "flux-general-en"

SAMPLE_RATE = int(os.getenv("SAMPLE_RATE", "16000"))
CHANNELS = int(os.getenv("CHANNELS", "1"))

SILENCE_TIMEOUT = 100  # sec, then auto-stop
SILENCE_THRESHOLD = 0.02  # rms gate for "speech"
HEALTH_CHECK_INTERVAL = 5


class RealTimeSTT:
    def __init__(self, api_key=None, model=STT_MODEL, sample_rate=SAMPLE_RATE, channels=CHANNELS):
        resolved_api_key = api_key or STT_API_KEY
        if not resolved_api_key:
            raise ValueError("Missing Deepgram API key. Set DpGram_API_KEY in your environment.")
        if not isinstance(sample_rate, int) or sample_rate <= 0:
            raise ValueError("sample_rate must be a positive integer.")
        if not isinstance(channels, int) or channels <= 0:
            raise ValueError("channels must be a positive integer.")

        self.log = logging.getLogger(self.__class__.__name__)

        self.client = DeepgramClient(api_key=resolved_api_key)
        self.model = model
        self.sample_rate = sample_rate
        self.channels = channels

        self.partial_transcript = ""
        self.final_transcript = ""

        self.on_partial = None
        self.on_final = None

        self.stop_event = threading.Event()
        self.mute_event = threading.Event()
        self.connection = None
        self.runner_thread = None
        self.monitor_thread = None

        self.metrics = defaultdict(int)

        self.started_at = None
        self.connection_opened_at = None
        self.last_audio_time = None
        self.last_message_time = None
        self.last_partial_time = None
        self.last_final_time = None
        self.last_speech_time = time.monotonic()

    def start(self):
        if self.runner_thread and self.runner_thread.is_alive():
            self.log.info("STT is already running.")
            return

        self.stop_event.clear()
        self.started_at = time.monotonic()
        self.last_speech_time = time.monotonic()
        self.metrics["stt_start_attempts"] += 1

        def run():
            try:
                with self.client.listen.v2.connect(
                    model=self.model,
                    encoding="linear16",
                    sample_rate=self.sample_rate
                ) as connection:

                    self.connection = connection
                    self.connection_opened_at = time.monotonic()
                    self.metrics["dg_connection_opened"] += 1
                    self.log.info("Deepgram connection opened.")

                    connection.on(EventType.MESSAGE, self.on_message)

                    threading.Thread(
                        target=connection.start_listening,
                        daemon=True
                    ).start()

                    threading.Thread(
                        target=self.start_mic_stream,
                        daemon=True
                    ).start()

                    self.start_monitoring()
                    self.log.info("Listening...")

                    while not self.stop_event.is_set():
                        sd.sleep(100)

            except Exception as e:
                self.metrics["stt_start_failure"] += 1
                self.metrics["errors"] += 1
                self.log.exception("STT failed to start: %s", e)
            finally:
                self.connection = None
                self.connection_opened_at = None

        self.runner_thread = threading.Thread(target=run, daemon=True)
        self.runner_thread.start()

    def start_monitoring(self):
        if self.monitor_thread and self.monitor_thread.is_alive():
            return

        def monitor():
            while not self.stop_event.is_set():
                self.print_health()

                now = time.monotonic()
                silence_duration = now - self.last_speech_time

                if self.connection is not None and silence_duration >= SILENCE_TIMEOUT:
                    self.log.info("Silence detected for %ss. Stopping STT.", SILENCE_TIMEOUT)
                    self.stop()
                    return

                time.sleep(HEALTH_CHECK_INTERVAL)

        self.monitor_thread = threading.Thread(target=monitor, daemon=True)
        self.monitor_thread.start()

    def print_health(self):
        now = time.monotonic()

        connected = self.connection is not None
        since_audio = None if self.last_audio_time is None else round(now - self.last_audio_time, 2)
        since_partial = None if self.last_partial_time is None else round(now - self.last_partial_time, 2)
        since_final = None if self.last_final_time is None else round(now - self.last_final_time, 2)
        since_speech = round(now - self.last_speech_time, 2)

        status = "healthy" if connected else "disconnected"

        self.log.info(
            "STT health | status=%s | partials=%d | finals=%d | errors=%d | last_audio=%s | last_partial=%s | last_final=%s | silence_for=%ss",
            status,
            self.metrics["partial_transcript_received"],
            self.metrics["final_transcript_received"],
            self.metrics["errors"],
            since_audio,
            since_partial,
            since_final,
            since_speech
        )

    def get_health(self):
        now = time.monotonic()
        return {
            "running": self.runner_thread is not None and self.runner_thread.is_alive(),
            "connected": self.connection is not None,
            "uptime_seconds": None if self.started_at is None else round(now - self.started_at, 2),
            "seconds_since_last_audio": None if self.last_audio_time is None else round(now - self.last_audio_time, 2),
            "seconds_since_last_partial": None if self.last_partial_time is None else round(now - self.last_partial_time, 2),
            "seconds_since_last_final": None if self.last_final_time is None else round(now - self.last_final_time, 2),
            "seconds_since_last_speech": round(now - self.last_speech_time, 2),
            "metrics": dict(self.metrics),
        }

    def on_message(self, message):
        try:
            self.last_message_time = time.monotonic()
            self.metrics["messages_received"] += 1

            if not hasattr(message, "type"):
                self.metrics["ignored_messages"] += 1
                return

            if message.type == "Transcript":
                channel = getattr(message, "channel", None)
                alternatives = getattr(channel, "alternatives", []) if channel else []

                if alternatives:
                    alt = alternatives[0]
                    transcript = getattr(alt, "transcript", "")
                    if transcript:
                        self.partial_transcript = transcript
                        self.last_partial_time = time.monotonic()
                        self.metrics["partial_transcript_received"] += 1

                        if callable(self.on_partial):
                            self.on_partial(self.partial_transcript)
                    else:
                        self.metrics["empty_partial_transcript"] += 1

            elif message.type == "TurnInfo":
                if getattr(message, "event", None) == "EndOfTurn":
                    transcript = getattr(message, "transcript", "")
                    if transcript:
                        self.final_transcript = transcript.strip()
                        self.last_final_time = time.monotonic()
                        self.metrics["final_transcript_received"] += 1

                        if callable(self.on_final):
                            self.on_final(self.final_transcript)
                    else:
                        self.metrics["empty_final_transcript"] += 1

        except Exception as e:
            self.metrics["errors"] += 1
            self.log.exception("Error while processing STT message: %s", e)

    def start_mic_stream(self):
        def callback(indata, frames, time_info, status):
            if status:
                self.metrics["mic_status_warnings"] += 1
                self.log.warning("Microphone status: %s", status)

            try:
                if not self.connection or self.stop_event.is_set():
                    return

                # skip audio while muted (jarvis is speaking)
                if self.mute_event.is_set():
                    self.metrics["audio_chunks_muted"] += 1
                    return

                audio = indata.astype(np.float32)
                audio /= 32768.0  # int16 -> float

                volume = float(np.sqrt(np.mean(audio ** 2)))

                if volume > SILENCE_THRESHOLD:
                    self.last_speech_time = time.monotonic()

                self.last_audio_time = time.monotonic()
                self.metrics["audio_chunks_sent"] += 1
                self.connection.send_media(indata.tobytes())

            except Exception as e:
                self.metrics["errors"] += 1
                self.log.exception("Failed to send mic audio: %s", e)

        try:
            self.metrics["mic_stream_started"] += 1
            with sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="int16",
                callback=callback
            ):
                while not self.stop_event.is_set():
                    sd.sleep(100)

        except Exception as e:
            self.metrics["mic_stream_failed"] += 1
            self.metrics["errors"] += 1
            self.log.exception("Microphone stream failed: %s", e)
            self.stop_event.set()

    def mute(self):
        if not self.mute_event.is_set():
            self.mute_event.set()
            self.log.debug("STT muted.")

    def unmute(self):
        if self.mute_event.is_set():
            self.mute_event.clear()
            # don't auto-stop just because we were muted
            self.last_speech_time = time.monotonic()
            self.log.debug("STT unmuted.")

    @property
    def is_muted(self) -> bool:
        return self.mute_event.is_set()

    def stop(self):
        if self.stop_event.is_set():
            return

        self.stop_event.set()

        try:
            if self.connection:
                close_fn = getattr(self.connection, "send_close_stream", None)
                if callable(close_fn):
                    close_fn()
                self.metrics["dg_connection_closed"] += 1
                self.log.info("Deepgram connection closed.")
        except Exception as e:
            self.metrics["errors"] += 1
            self.log.exception("Error while closing STT connection: %s", e)
        finally:
            self.connection = None

        self.log.info("Stopped")

# quick local test
if __name__ == "__main__":
    def handle_partial(text):
        print(f"⏳ {text}", end="\r")

    def handle_final(text):
        print(f"\nFinal: {text}")

    try:
        stt = RealTimeSTT()
    except ValueError as e:
        print(f"Configuration error: {e}")
        raise SystemExit(1) from e

    stt.on_partial = handle_partial
    stt.on_final = handle_final

    try:
        stt.start()
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        stt.stop()
        print("\nHealth snapshot:", stt.get_health())