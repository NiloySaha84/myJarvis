import os
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path

device_metrics = defaultdict(int)


def _mark_call(name: str):
    device_metrics["calls_total"] += 1
    device_metrics[f"{name}_calls"] += 1


def _mark_success(name: str):
    device_metrics["success_total"] += 1
    device_metrics[f"{name}_success"] += 1


def _mark_error(name: str):
    device_metrics["errors_total"] += 1
    device_metrics[f"{name}_errors"] += 1


def _mark_validation_error(name: str):
    device_metrics["validation_errors_total"] += 1
    device_metrics[f"{name}_validation_errors"] += 1


def get_device_metrics():
    return dict(device_metrics)


def open_browser(browser_name: str = "Safari", url: str = "https://www.google.com") -> str:
    method = "open_browser"
    _mark_call(method)
    try:
        if not browser_name or not browser_name.strip():
            _mark_validation_error(method)
            return "Please provide a valid browser name."
        if not url or not url.strip():
            _mark_validation_error(method)
            return "Please provide a valid URL."

        result = subprocess.run(
            ["open", "-a", browser_name, url],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            _mark_success(method)
            return f"Opened {browser_name} with {url}"
        _mark_error(method)
        return f"Failed to open {browser_name} with {url}: {result.stderr.strip() or result.stdout.strip() or 'Unknown error'}"
    except Exception as e:
        _mark_error(method)
        return f"Error opening browser: {e}"


def open_app(app_name: str) -> str:
    method = "open_app"
    _mark_call(method)
    try:
        if not app_name or not app_name.strip():
            _mark_validation_error(method)
            return "Please provide a valid app name."

        result = subprocess.run(
            ["open", "-a", app_name],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            _mark_success(method)
            return f"Opened {app_name}"
        _mark_error(method)
        return f"Failed to open {app_name}: {result.stderr.strip() or result.stdout.strip() or 'Unknown error'}"
    except Exception as e:
        _mark_error(method)
        return f"Error opening app: {e}"


def close_app(app_name: str) -> str:
    method = "close_app"
    _mark_call(method)
    try:
        blocked_apps = ["System Preferences", "Terminal", "Finder", "Dock"]

        if not app_name or not app_name.strip():
            _mark_validation_error(method)
            return "Please provide a valid app name."
        if app_name in blocked_apps:
            _mark_validation_error(method)
            return f"Cannot close {app_name} as it is a system app."

        result = subprocess.run(
            ["osascript", "-e", f'tell application "{app_name}" to quit'],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            _mark_success(method)
            return f"Closed {app_name}"
        _mark_error(method)
        return f"Failed to close {app_name}: {result.stderr.strip() or result.stdout.strip() or 'Unknown error'}"
    except Exception as e:
        _mark_error(method)
        return f"Error closing app: {e}"


def create_folder(folder_name: str) -> str:
    method = "create_folder"
    _mark_call(method)
    try:
        if not folder_name or not folder_name.strip():
            _mark_validation_error(method)
            return "Please provide a valid folder name."

        base_path = Path.home()
        full_path = base_path / folder_name
        full_path.mkdir(parents=True, exist_ok=True)
        _mark_success(method)
        return f"Created folder: {full_path}"
    except Exception as e:
        _mark_error(method)
        return f"Error creating folder: {e}"


def create_file(file_name: str) -> str:
    method = "create_file"
    _mark_call(method)
    try:
        if not file_name or not file_name.strip():
            _mark_validation_error(method)
            return "Please provide a valid file name."

        base_path = Path.home()
        full_path = base_path / file_name
        full_path.touch(exist_ok=True)
        _mark_success(method)
        return f"Created file: {full_path}"
    except Exception as e:
        _mark_error(method)
        return f"Error creating file: {e}"


def open_folder(folder_path: str, app: str) -> str:
    method = "open_folder"
    _mark_call(method)
    try:
        if not folder_path or not folder_path.strip():
            _mark_validation_error(method)
            return "Please provide a valid folder path."
        if not app or not app.strip():
            _mark_validation_error(method)
            return "Please provide a valid app name."

        folder_path = os.path.abspath(os.path.expanduser(folder_path))

        if not os.path.exists(folder_path):
            _mark_validation_error(method)
            return f"Path does not exist: {folder_path}"

        result = subprocess.run(
            ["open", "-a", app, folder_path],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            _mark_success(method)
            return f"Opened folder: {folder_path}"
        _mark_error(method)
        return f"Failed to open folder: {result.stderr.strip() or result.stdout.strip() or 'Unknown error'}"
    except Exception as e:
        _mark_error(method)
        return f"Error opening folder: {e}"


def open_file(file_path: str, app: str) -> str:
    method = "open_file"
    _mark_call(method)
    try:
        if not file_path or not file_path.strip():
            _mark_validation_error(method)
            return "Please provide a valid file path."
        if not app or not app.strip():
            _mark_validation_error(method)
            return "Please provide a valid app name."

        file_path = os.path.abspath(os.path.expanduser(file_path))

        if not os.path.exists(file_path):
            _mark_validation_error(method)
            return f"Path does not exist: {file_path}"

        result = subprocess.run(
            ["open", "-a", app, file_path],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            _mark_success(method)
            return f"Opened file: {file_path}"
        _mark_error(method)
        return f"Failed to open file: {result.stderr.strip() or result.stdout.strip() or 'Unknown error'}"
    except Exception as e:
        _mark_error(method)
        return f"Error opening file: {e}"


def rename_folder_file(folder_path: str, new_name: str) -> str:
    method = "rename_folder_file"
    _mark_call(method)
    try:
        if not folder_path or not folder_path.strip():
            _mark_validation_error(method)
            return "Please provide a valid folder path."
        if not new_name or not new_name.strip():
            _mark_validation_error(method)
            return "Please provide a valid new name."

        folder_path = os.path.abspath(os.path.expanduser(folder_path))

        if not os.path.exists(folder_path):
            _mark_validation_error(method)
            return f"Path does not exist: {folder_path}"

        new_path = os.path.join(os.path.dirname(folder_path), new_name)
        os.rename(folder_path, new_path)
        _mark_success(method)
        return f"Renamed: {folder_path} to {new_path}"
    except Exception as e:
        _mark_error(method)
        return f"Error renaming item: {e}"


def copy_file(file_path: str, new_path: str) -> str:
    method = "copy_file"
    _mark_call(method)
    try:
        if not file_path or not file_path.strip():
            _mark_validation_error(method)
            return "Please provide a valid file path."
        if not new_path or not new_path.strip():
            _mark_validation_error(method)
            return "Please provide a valid new path."

        file_path = os.path.abspath(os.path.expanduser(file_path))
        new_path = os.path.abspath(os.path.expanduser(new_path))

        if not os.path.exists(file_path):
            _mark_validation_error(method)
            return f"Path does not exist: {file_path}"

        # dir -> copy inside, file -> exact path
        if os.path.isdir(new_path):
            dest = os.path.join(new_path, os.path.basename(file_path))
        else:
            dest = new_path

        shutil.copy(file_path, dest)
        _mark_success(method)
        return f"Copied file: {file_path} to {dest}"
    except Exception as e:
        _mark_error(method)
        return f"Error copying file: {e}"


def copy_folder(folder_path: str, new_path: str) -> str:
    method = "copy_folder"
    _mark_call(method)
    try:
        if not folder_path or not folder_path.strip():
            _mark_validation_error(method)
            return "Please provide a valid folder path."
        if not new_path or not new_path.strip():
            _mark_validation_error(method)
            return "Please provide a valid new path."

        folder_path = os.path.abspath(os.path.expanduser(folder_path))
        new_path = os.path.abspath(os.path.expanduser(new_path))

        if not os.path.exists(folder_path):
            _mark_validation_error(method)
            return f"Folder does not exist: {folder_path}"
        if not os.path.exists(new_path):
            _mark_validation_error(method)
            return f"Destination path does not exist: {new_path}"

        final_dest = os.path.join(new_path, os.path.basename(folder_path))
        shutil.copytree(folder_path, final_dest, dirs_exist_ok=True)
        _mark_success(method)
        return f"Copied folder: {folder_path} to {final_dest}"
    except Exception as e:
        _mark_error(method)
        return f"Error copying folder: {e}"




# todo: move, search


if __name__ == "__main__":
    print(open_browser("Firefox"))