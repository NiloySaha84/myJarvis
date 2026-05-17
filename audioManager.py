import subprocess
import time
from collections import defaultdict


class AudioManager:
    def __init__(self, duck_volume: int = 25):
        self.duck_volume = max(0, min(100, duck_volume))
        self.saved_volume = None
        self.metrics = defaultdict(int)

    def get_metrics(self):
        return dict(self.metrics)

    def run_osascript(self, script: str) -> str:
        self.metrics["run_osascript_calls"] += 1
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            check=True,
        )
        self.metrics["run_osascript_success"] += 1
        return result.stdout.strip()

    def get_volume(self) -> int:
        self.metrics["get_volume_calls"] += 1
        out = self.run_osascript("output volume of (get volume settings)")
        return int(out)

    def duck(self) -> None:
        self.metrics["duck_calls"] += 1
        if self.saved_volume is None:
            self.saved_volume = self.get_volume()
        self.run_osascript(f"set volume output volume {self.duck_volume}")
        self.metrics["duck_success"] += 1

    def restore(self) -> None:
        self.metrics["restore_calls"] += 1
        if self.saved_volume is not None:
            self.run_osascript(f"set volume output volume {self.saved_volume}")
            self.saved_volume = None
            self.metrics["restore_success"] += 1