import subprocess
import time


class AudioManager:
    def __init__(self, duck_volume: int = 25):
        self.duck_volume = max(0, min(100, duck_volume))
        self.saved_volume = None

    def run_osascript(self, script: str) -> str:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    def get_volume(self) -> int:
        out = self.run_osascript("output volume of (get volume settings)")
        return int(out)

    def duck(self) -> None:
        if self.saved_volume is None:
            self.saved_volume = self.get_volume()
        self.run_osascript(f"set volume output volume {self.duck_volume}")

    def restore(self) -> None:
        if self.saved_volume is not None:
            self.run_osascript(f"set volume output volume {self.saved_volume}")
            self.saved_volume = None