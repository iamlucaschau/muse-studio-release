import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

WINDOW_TITLE = "Muse Studio - AI Media & Video"
WINDOW_WIDTH = 1440
WINDOW_HEIGHT = 900


def wait_for_server(host: str, port: int, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.15)
    return False


def find_chromium_app_binary() -> Optional[str]:
    """Tìm trình duyệt Chrome hoặc Microsoft Edge trên Windows để chạy chế độ Standalone App Mode (--app=...)."""
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
    ]
    for c in candidates:
        if c and Path(c).exists():
            return str(Path(c).resolve())
    for name in ("chrome", "msedge"):
        found = shutil.which(name)
        if found:
            return found
    return None


def launch_chromium_app_window(url: str, base_dir: Path, spawn_on_desktop_fn=None) -> bool:
    """
    Mở cửa sổ Desktop độc lập (Standalone App Mode) không có thanh URL và không có tab trình duyệt:
    --app=http://127.0.0.1:18688 --window-size=1440,900
    """
    browser_bin = find_chromium_app_binary()
    if not browser_bin:
        return False

    app_shell_dir = (base_dir / ".muse" / "desktop_app_shell").resolve()
    app_shell_dir.mkdir(parents=True, exist_ok=True)

    args = [
        browser_bin,
        f"--app={url}",
        f"--window-size={WINDOW_WIDTH},{WINDOW_HEIGHT}",
        f"--user-data-dir={app_shell_dir}",
        "--new-window",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=Translate,GlobalMediaControls",
    ]
    cmd_line = subprocess.list2cmdline(args)

    if sys.platform == "win32" and callable(spawn_on_desktop_fn):
        if spawn_on_desktop_fn(cmd_line, show_window=1):
            return True

    try:
        subprocess.Popen(args, close_fds=True)
        return True
    except Exception:
        return False


def run_pywebview_window(url: str) -> bool:
    """Khởi chạy cửa sổ Desktop gốc bằng pywebview kích thước 1440x900."""
    try:
        import webview  # type: ignore

        webview.create_window(
            WINDOW_TITLE,
            url,
            width=WINDOW_WIDTH,
            height=WINDOW_HEIGHT,
            min_size=(1100, 700),
            background_color="#0b0f19",
            text_select=True,
        )
        webview.start()
        return True
    except Exception as exc:
        print(f"[Muse Studio] pywebview gặp xung đột ({exc}) -> Chuyển sang chế độ Standalone App Window...", flush=True)
        return False


if __name__ == "__main__":
    target_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:18688"
    root_dir = Path(__file__).resolve().parent
    if not run_pywebview_window(target_url):
        launch_chromium_app_window(target_url, root_dir)
