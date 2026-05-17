import os
import time
import threading
import queue
import logging
from collections import defaultdict
from typing import Optional

import pyaudio
from dotenv import load_dotenv
from deepgram import DeepgramClient
from deepgram.core.events import EventType
from deepgram.speak.v1.types import SpeakV1Text

load_dotenv()

TTS_API_KEY = os.getenv("DpGram_API_KEY") or os.getenv("DEEPGRAM_API_KEY")
TTS_MODEL = "aura-2-apollo-en"

# 48k sounds cleaner on mac than 24k
SAMPLE_RATE = 48000
CHANNELS = 1
SUPPORTED_SAMPLE_RATES = (8000, 16000, 24000, 32000, 48000)

FORMAT = pyaudio.paInt16
SAMPLE_WIDTH = 2  # int16

# bigger buffer = fewer clicks
CHUNK = 4096
QUEUE_TIMEOUT = 0.1

# tiny prebuffer so first word doesn't clip
PREBUFFER_SECONDS = 0.08


class StopSentinel:
    """Marker to stop the speaker thread."""


STOP = StopSentinel()


class Speaker:
    """Plays PCM chunks on a background thread."""

    def __init__(
        self,
        rate: int = SAMPLE_RATE,
        chunk: int = CHUNK,
        channels: int = CHANNELS,
        output_device_index: Optional[int] = None,
        prebuffer_seconds: float = PREBUFFER_SECONDS,
    ):
        self.rate = rate
        self.chunk = chunk
        self.channels = channels
        self.format = FORMAT
        self.output_device_index = output_device_index
        self.prebuffer_bytes = max(
            0,
            int(rate * SAMPLE_WIDTH * channels * prebuffer_seconds),
        )

        self.audio: Optional[pyaudio.PyAudio] = None
        self.queue: "queue.Queue" = queue.Queue()
        self.exit = threading.Event()

        self.stream = None
        self.thread: Optional[threading.Thread] = None
        self.lock = threading.Lock()
        self.log = logging.getLogger(self.__class__.__name__)

    def start(self) -> None:
        with self.lock:
            if self.stream is not None:
                return

            self.exit.clear()

            # clear old queue
            while not self.queue.empty():
                try:
                    self.queue.get_nowait()
                except queue.Empty:
                    break

            if self.audio is None:
                self.audio = pyaudio.PyAudio()

            self.stream = self.audio.open(
                format=self.format,
                channels=self.channels,
                rate=self.rate,
                input=False,
                output=True,
                frames_per_buffer=self.chunk,
                output_device_index=self.output_device_index,
            )

            self.thread = threading.Thread(
                target=self.play_loop,
                name="SpeakerPlayLoop",
                daemon=True,
            )
            self.thread.start()

    def play_loop(self) -> None:
        # prebuffer first, then stream
        prebuffer = bytearray()
        prebuffered = self.prebuffer_bytes == 0

        while not self.exit.is_set():
            try:
                item = self.queue.get(timeout=QUEUE_TIMEOUT)
            except queue.Empty:
                continue

            if item is STOP or item is None:
                break
            if not item:
                continue

            if not prebuffered:
                prebuffer.extend(item)
                if len(prebuffer) >= self.prebuffer_bytes:
                    self.safe_write(bytes(prebuffer))
                    prebuffer.clear()
                    prebuffered = True
                continue

            self.safe_write(item)

        if prebuffer and not self.exit.is_set():
            self.safe_write(bytes(prebuffer))

    def safe_write(self, data: bytes) -> None:
        stream = self.stream
        if stream is None:
            return
        try:
            stream.write(data, exception_on_underflow=False)
        except OSError as e:
            self.log.warning("Speaker stream write error: %s", e)
        except Exception as e:
            self.log.exception("Unexpected speaker error: %s", e)

    def play(self, data: bytes) -> None:
        if self.exit.is_set() or not data:
            return
        self.queue.put(data)

    def drain(self, timeout: float = 5.0) -> bool:
        """Wait until the play queue is empty."""
        deadline = time.monotonic() + max(0.0, timeout)
        while time.monotonic() < deadline:
            if self.queue.empty():
                return True
            time.sleep(0.02)
        return False

    def get_output_latency(self) -> float:
        """Rough seconds still in the device buffer."""
        stream = self.stream
        if stream is None:
            return 0.0
        try:
            value = stream.get_output_latency()
        except Exception:
            return 0.0
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def stop(self) -> None:
        """Stop playback, keep PyAudio for next start."""
        if self.exit.is_set() and self.stream is None:
            return

        self.exit.set()
        # don't wait on queue timeout
        self.queue.put(STOP)

        thread = self.thread
        self.thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)

        with self.lock:
            stream = self.stream
            self.stream = None

        if stream is not None:
            try:
                if stream.is_active():
                    # lets buffered audio finish
                    stream.stop_stream()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass

    def close(self) -> None:
        """Tear down PyAudio for good."""
        self.stop()
        if self.audio is not None:
            try:
                self.audio.terminate()
            except Exception:
                pass
            self.audio = None


class RealTimeTTS:
    """Deepgram TTS -> local speaker."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = TTS_MODEL,
        sample_rate: int = SAMPLE_RATE,
        channels: int = CHANNELS,
        output_device_index: Optional[int] = None,
    ):
        resolved_api_key = api_key or TTS_API_KEY
        if not resolved_api_key:
            raise ValueError(
                "Missing Deepgram API key. Set DpGram_API_KEY or DEEPGRAM_API_KEY."
            )
        if sample_rate not in SUPPORTED_SAMPLE_RATES:
            raise ValueError(
                f"sample_rate must be one of {SUPPORTED_SAMPLE_RATES}."
            )
        if not isinstance(channels, int) or channels <= 0:
            raise ValueError("channels must be a positive integer.")

        self.log = logging.getLogger(self.__class__.__name__)

        self.client = DeepgramClient(api_key=resolved_api_key)
        self.model = model
        self.sample_rate = sample_rate
        self.channels = channels

        self.stop_event = threading.Event()
        self.ready_event = threading.Event()
        self.connection_failed = threading.Event()
        self.connection_error: Optional[BaseException] = None
        self.thread: Optional[threading.Thread] = None
        self.send_lock = threading.Lock()

        # count pending flushes from deepgram
        self.flush_lock = threading.Lock()
        self.pending_flushes = 0
        self.all_flushed_event = threading.Event()
        self.all_flushed_event.set()

        self.connection = None
        self.speaker = Speaker(
            rate=self.sample_rate,
            channels=self.channels,
            output_device_index=output_device_index,
        )
        self.metrics = defaultdict(int)
        self.metrics_lock = threading.Lock()
        self.last_say_latency_ms = 0.0
        self.avg_say_latency_ms = 0.0

    def _inc_metric(self, name: str, value: int = 1) -> None:
        with self.metrics_lock:
            self.metrics[name] += value

    def _observe_say_latency(self, elapsed_ms: float) -> None:
        with self.metrics_lock:
            self.last_say_latency_ms = round(elapsed_ms, 2)
            count = self.metrics.get("say_requests_completed", 0)
            if count <= 0:
                self.avg_say_latency_ms = round(elapsed_ms, 2)
                return
            self.avg_say_latency_ms = round(
                ((self.avg_say_latency_ms * (count - 1)) + elapsed_ms) / count,
                2,
            )

    def get_health(self) -> dict:
        with self.metrics_lock:
            metrics = dict(self.metrics)
            metrics["say_last_latency_ms"] = self.last_say_latency_ms
            metrics["say_avg_latency_ms"] = self.avg_say_latency_ms
        return {
            "connected": self.connection is not None,
            "ready": self.ready_event.is_set() and not self.connection_failed.is_set(),
            "pending_flushes": self.pending_flushes,
            "metrics": metrics,
        }

    def build_speak_message(self, text: str):
        # deepgram sdk versions differ on this shape
        try:
            return SpeakV1Text(text=text)
        except Exception:
            return SpeakV1Text(type="Speak", text=text)

    def start(self) -> None:
        if self.thread is not None and self.thread.is_alive():
            self._inc_metric("start_skipped_already_running")
            self.log.info("TTS is already running.")
            return

        self._inc_metric("start_attempts")
        self.stop_event.clear()
        self.ready_event.clear()
        self.connection_failed.clear()
        self.connection_error = None

        def run():
            try:
                with self.client.speak.v1.connect(
                    model=self.model,
                    encoding="linear16",
                    sample_rate=self.sample_rate,
                ) as connection:
                    self.connection = connection
                    self._inc_metric("connection_opened")

                    connection.on(EventType.MESSAGE, self.on_message)
                    connection.on(EventType.ERROR, self.on_error)

                    self.speaker.start()
                    self.ready_event.set()
                    self.log.info("TTS connection ready.")

                    connection.start_listening()

            except BaseException as e:
                self._inc_metric("connection_failures")
                self.connection_error = e
                self.connection_failed.set()
                self.log.exception("TTS connection failed: %s", e)
            finally:
                self._inc_metric("connection_closed")
                self.connection = None
                self.speaker.stop()
                self.ready_event.set()

        self.thread = threading.Thread(
            target=run,
            name="RealTimeTTSConnection",
            daemon=True,
        )
        self.thread.start()

        if not self.ready_event.wait(timeout=10):
            self._inc_metric("ready_wait_timeouts")
            raise TimeoutError("TTS connection did not become ready in time.")

        if self.connection_failed.is_set():
            self._inc_metric("start_failed")
            err = self.connection_error or RuntimeError(
                "Unknown TTS connection error"
            )
            raise err
        self._inc_metric("start_completed")

    def say(
        self,
        text: str,
        flush: bool = True,
        wait: bool = False,
        wait_timeout: float = 30.0,
    ) -> bool:
        """Speak text. wait=True blocks until audio finishes."""
        if not text or not text.strip():
            self._inc_metric("say_empty_text")
            return True

        connection = self.connection
        if connection is None:
            self._inc_metric("say_rejected_not_connected")
            raise RuntimeError("TTS is not connected yet. Call start() first.")

        # one sender at a time
        say_started = time.monotonic()
        self._inc_metric("say_requests_started")
        with self.send_lock:
            try:
                connection.send_text(self.build_speak_message(text))
                self._inc_metric("tts_text_messages_sent")
                if flush:
                    with self.flush_lock:
                        self.pending_flushes += 1
                        self.all_flushed_event.clear()
                    connection.send_flush()
                    self._inc_metric("tts_flush_messages_sent")
            except Exception as e:
                self._inc_metric("say_requests_failed")
                self.log.exception("Failed to send text to TTS: %s", e)
                raise

        self._inc_metric("say_requests_completed")
        self._observe_say_latency((time.monotonic() - say_started) * 1000)

        if wait and flush:
            self._inc_metric("say_wait_requests")
            return self.wait_for_idle(timeout=wait_timeout)
        return True

    def wait_until_idle(self, timeout: float = 30.0) -> bool:
        """Wait until nothing is still playing."""
        return self.wait_for_idle(timeout=timeout)

    def wait_for_idle(self, timeout: float) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)

        # deepgram done sending chunks
        if not self.all_flushed_event.wait(timeout=timeout):
            self._inc_metric("wait_for_idle_timeout_on_flush")
            return False

        # our queue drained
        remaining = max(0.0, deadline - time.monotonic())
        if not self.speaker.drain(timeout=remaining):
            self._inc_metric("wait_for_idle_timeout_on_drain")
            return False

        # device buffer + a little tail room
        device_latency = self.speaker.get_output_latency()
        tail = max(0.30, device_latency + 0.10)
        sleep_for = min(tail, max(0.0, deadline - time.monotonic()))
        if sleep_for > 0:
            time.sleep(sleep_for)
        return True

    def on_message(self, message):
        try:
            if isinstance(message, (bytes, bytearray)):
                self._inc_metric("audio_chunks_received")
                self.log.debug("Got audio chunk: %d bytes", len(message))
                self.speaker.play(bytes(message))
            else:
                msg_type = getattr(message, "type", "Unknown")
                self.log.debug("TTS event: %s", msg_type)
                if msg_type == "Flushed":
                    self._inc_metric("flush_events_received")
                    with self.flush_lock:
                        if self.pending_flushes > 0:
                            self.pending_flushes -= 1
                        if self.pending_flushes == 0:
                            self.all_flushed_event.set()
        except Exception as e:
            self._inc_metric("on_message_errors")
            self.log.exception("Error while handling TTS message: %s", e)

    def on_error(self, error):
        self._inc_metric("deepgram_error_events")
        self.log.error("TTS error: %s", error)

    def stop(self) -> None:
        if self.stop_event.is_set():
            self._inc_metric("stop_skipped_already_stopped")
            return
        self._inc_metric("stop_calls")
        self.stop_event.set()

        connection = self.connection
        if connection is not None:
            # flush last words before close
            try:
                connection.send_flush()
            except Exception:
                pass
            try:
                connection.send_close()
            except Exception:
                pass
        self.connection = None

        # connection thread done
        thread = self.thread
        self.thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)

        # finish what's queued
        self.speaker.drain(timeout=3.0)
        self.speaker.close()

        # reset flush state
        with self.flush_lock:
            self.pending_flushes = 0
            self.all_flushed_event.set()

        self.log.info("TTS stopped")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    tts = RealTimeTTS()
    tts.start()
    try:
        tts.say(
            "Hello. This is Deepgram text to speech. "
            "Lorem ipsum dolor sit amet, consectetur adipiscing elit. "
            "Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua."
        )
        time.sleep(30)
    finally:
        tts.stop()
