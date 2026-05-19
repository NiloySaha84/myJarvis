import os
import platform
import socket
import threading
import time
from collections import defaultdict
from typing import Any

import psutil


SYSTEM_MONITOR_INTERVAL_SEC = float(os.getenv("SYSTEM_MONITOR_INTERVAL_SEC", "1.0"))


class CoreSystemMonitor:
    def __init__(self, sample_interval_sec: float = SYSTEM_MONITOR_INTERVAL_SEC):
        self.sample_interval_sec = max(0.2, float(sample_interval_sec))
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.last_snapshot: dict[str, Any] = {}
        self.metrics = defaultdict(int)
        self.prev_network_bytes: tuple[int, int] | None = None
        self.prev_sample_time: float | None = None

        # Prime psutil CPU sampling so the next call is meaningful.
        psutil.cpu_percent(interval=None)

    def start(self) -> None:
        with self.lock:
            if self.thread is not None and self.thread.is_alive():
                return

            self.stop_event.clear()
            self.thread = threading.Thread(
                target=self.run_loop,
                name="CoreSystemMonitor",
                daemon=True,
            )
            self.thread.start()

    def run_loop(self) -> None:
        while not self.stop_event.is_set():
            self.sample_once()
            self.stop_event.wait(self.sample_interval_sec)

    def sample_once(self) -> None:
        now = time.monotonic()
        self.metrics["sample_attempts"] += 1
        errors: list[str] = []
        snapshot: dict[str, Any] = {
            "sampled_at_epoch_ms": int(time.time() * 1000),
            "host": {
                "hostname": socket.gethostname(),
                "os": platform.platform(),
            },
        }

        try:
            cpu_percent = float(psutil.cpu_percent(interval=None))
            logical_cores = int(psutil.cpu_count(logical=True) or 0)
            try:
                physical_cores = int(psutil.cpu_count(logical=False) or 0)
            except Exception:
                physical_cores = 0
            try:
                load_avg_raw = os.getloadavg()
                load_avg = {
                    "1m": round(float(load_avg_raw[0]), 2),
                    "5m": round(float(load_avg_raw[1]), 2),
                    "15m": round(float(load_avg_raw[2]), 2),
                }
            except Exception:
                load_avg = None

            snapshot["cpu"] = {
                "percent": round(cpu_percent, 2),
                "logical_cores": logical_cores,
                "physical_cores": physical_cores,
                "load_avg": load_avg,
            }
        except Exception as exc:
            errors.append(f"cpu: {exc}")

        try:
            vm = psutil.virtual_memory()
            snapshot["memory"] = {
                "percent": round(float(vm.percent), 2),
                "used_gb": round(float(vm.used) / (1024 ** 3), 2),
                "total_gb": round(float(vm.total) / (1024 ** 3), 2),
                "available_gb": round(float(vm.available) / (1024 ** 3), 2),
            }
        except Exception as exc:
            errors.append(f"memory: {exc}")

        try:
            disk = psutil.disk_usage("/")
            snapshot["disk"] = {
                "percent": round(float(disk.percent), 2),
                "used_gb": round(float(disk.used) / (1024 ** 3), 2),
                "total_gb": round(float(disk.total) / (1024 ** 3), 2),
                "free_gb": round(float(disk.free) / (1024 ** 3), 2),
            }
        except Exception as exc:
            errors.append(f"disk: {exc}")

        try:
            net = psutil.net_io_counters()
            upload_bps = 0.0
            download_bps = 0.0
            if self.prev_network_bytes and self.prev_sample_time is not None:
                elapsed = max(0.001, now - self.prev_sample_time)
                prev_sent, prev_recv = self.prev_network_bytes
                upload_bps = max(0.0, float(net.bytes_sent - prev_sent) / elapsed)
                download_bps = max(0.0, float(net.bytes_recv - prev_recv) / elapsed)

            self.prev_network_bytes = (int(net.bytes_sent), int(net.bytes_recv))
            self.prev_sample_time = now
            snapshot["network"] = {
                "upload_bps": round(upload_bps, 2),
                "download_bps": round(download_bps, 2),
                "bytes_sent_total": int(net.bytes_sent),
                "bytes_recv_total": int(net.bytes_recv),
            }
        except Exception as exc:
            errors.append(f"network: {exc}")

        try:
            uptime_seconds = max(0.0, time.time() - psutil.boot_time())
            snapshot["uptime_seconds"] = round(uptime_seconds, 1)
        except Exception as exc:
            errors.append(f"uptime: {exc}")

        if errors:
            self.metrics["sample_errors"] += 1
            snapshot["error"] = "Partial system metrics collection failure."
            snapshot["error_details"] = errors
        else:
            self.metrics["sample_success"] += 1

        with self.lock:
            self.last_snapshot = snapshot

    def get_snapshot(self) -> dict[str, Any]:
        with self.lock:
            snapshot = dict(self.last_snapshot)

        if not snapshot:
            self.sample_once()
            with self.lock:
                snapshot = dict(self.last_snapshot)

        sampled_at = snapshot.get("sampled_at_epoch_ms", 0)
        if sampled_at:
            snapshot["stale_ms"] = max(0, int(time.time() * 1000) - int(sampled_at))
        snapshot["monitor"] = {
            "interval_sec": self.sample_interval_sec,
            "metrics": dict(self.metrics),
        }
        return snapshot


system_monitor = CoreSystemMonitor()
system_monitor.start()


def get_live_core_system_data() -> dict[str, Any]:
    """Return current core host stats for CPU, memory, disk, network, and uptime."""
    return system_monitor.get_snapshot()
