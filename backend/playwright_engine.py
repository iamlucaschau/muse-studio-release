import asyncio
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
import httpx

from backend.database import PROFILES_DIR, get_connection, get_settings
from backend.matcher import wrap_prompt

MUSE_COMPOSER_URL = "https://muse.ai/?open_composer=1"

# Các selector nhận diện khung nhập prompt (Composer) chuẩn xác trên Muse.ai
COMPOSER_SELECTORS = [
    "textarea[placeholder='Message']",
    "textarea[aria-label='Message']",
    "textarea[placeholder*='Message' i]",
    "textarea[placeholder*='Ask' i]",
    "textarea[placeholder*='Create' i]",
    "textarea[placeholder*='Describe' i]",
    "textarea[placeholder*='prompt' i]",
    "div[contenteditable='true'][role='textbox']",
    "div[contenteditable='true']",
    "textarea",
]

# Các văn bản nút xác nhận tự động (Auto-Approve)
APPROVE_BUTTON_TEXTS = ["Approve", "Allow", "Cho phép", "Continue", "Accept", "Confirm"]


def get_account_profile_dir(account_id: int, custom_path: Optional[str] = None) -> Path:
    if custom_path:
        p = Path(custom_path)
    else:
        p = PROFILES_DIR / f"acc_{account_id}"
    p.mkdir(parents=True, exist_ok=True)
    return p


def cleanup_orphaned_profile_processes(profile_dir: Path) -> None:
    """
    Giải phóng các tiến trình chrome.exe bị treo đang giữ khóa ProcessSingleton
    trên thư mục profile_dir (tránh lỗi Failed to create a ProcessSingleton).
    """
    if sys.platform == "win32":
        try:
            prof_name = profile_dir.name
            cmd = (
                f"Get-CimInstance Win32_Process -Filter \"Name = 'chrome.exe'\" | "
                f"Where-Object {{ $_.CommandLine -like '*{prof_name}*' }} | "
                f"ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }}"
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", cmd],
                capture_output=True,
                timeout=6,
            )
        except Exception:
            pass

    for lock_name in ("SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile"):
        lock_file = profile_dir / lock_name
        if lock_file.exists():
            try:
                lock_file.unlink()
            except Exception:
                pass


def _is_current_desktop_default() -> bool:
    """Kiểm tra xem tiến trình Python hiện tại có đang gắn vào WinSta0\\Default hay không."""
    if sys.platform != "win32":
        return True
    try:
        import ctypes

        u32 = ctypes.windll.user32
        k32 = ctypes.windll.kernel32
        hdesk = u32.GetThreadDesktop(k32.GetCurrentThreadId())
        buf = ctypes.create_unicode_buffer(256)
        if u32.GetUserObjectInformationW(hdesk, 2, buf, 512, None):
            return buf.value.strip().lower() == "default"
    except Exception:
        pass
    return True


_ACTIVE_LOGIN_PROCS: Dict[int, int] = {}


def _run_login_subprocess_on_default_desktop(account_id: int) -> Dict[str, Any]:
    """
    Khởi chạy tiến trình đăng nhập tương tác trực tiếp trên màn hình thật WinSta0\\Default
    của người dùng Windows (vượt qua cô lập Desktop sandbox khi server chạy ngầm).
    """
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.windll.kernel32
    u32 = ctypes.windll.user32

    # Nếu tài khoản này đang có tiến trình Login cũ chưa đóng, dừng tiến trình cũ trước
    old_pid = _ACTIVE_LOGIN_PROCS.pop(account_id, None)
    if old_pid:
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(old_pid)],
                capture_output=True,
                timeout=4,
            )
            time.sleep(0.8)
        except Exception:
            pass

    base_dir = PROFILES_DIR.parent.parent
    result_file = PROFILES_DIR.parent / f"login_result_{account_id}.json"
    if result_file.exists():
        try:
            result_file.unlink()
        except Exception:
            pass

    try:
        hdesk = u32.OpenDesktopW("Default", 0, False, 0x10000000)
        if hdesk:
            u32.SetThreadDesktop(hdesk)
        u32.keybd_event(0x12, 0, 0, 0)
        u32.keybd_event(0x12, 0, 2, 0)
    except Exception:
        pass

    cmd_line = (
        f'"{sys.executable}" -m backend.playwright_engine '
        f'--interactive-login {account_id} "{result_file}"'
    )

    class STARTUPINFOW(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("lpReserved", wintypes.LPWSTR),
            ("lpDesktop", wintypes.LPWSTR),
            ("lpTitle", wintypes.LPWSTR),
            ("dwX", wintypes.DWORD),
            ("dwY", wintypes.DWORD),
            ("dwXSize", wintypes.DWORD),
            ("dwYSize", wintypes.DWORD),
            ("dwXCountChars", wintypes.DWORD),
            ("dwYCountChars", wintypes.DWORD),
            ("dwFillAttribute", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("wShowWindow", wintypes.WORD),
            ("cbReserved2", wintypes.WORD),
            ("lpReserved2", ctypes.c_void_p),
            ("hStdInput", wintypes.HANDLE),
            ("hStdOutput", wintypes.HANDLE),
            ("hStdError", wintypes.HANDLE),
        ]

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("hProcess", wintypes.HANDLE),
            ("hThread", wintypes.HANDLE),
            ("dwProcessId", wintypes.DWORD),
            ("dwThreadId", wintypes.DWORD),
        ]

    si = STARTUPINFOW()
    si.cb = ctypes.sizeof(si)
    si.lpDesktop = "WinSta0\\Default"
    si.dwFlags = 1
    si.wShowWindow = 0
    pi = PROCESS_INFORMATION()
    buf = ctypes.create_unicode_buffer(cmd_line)
    cwd_buf = ctypes.create_unicode_buffer(str(base_dir))

    ok = k32.CreateProcessW(
        None,
        buf,
        None,
        None,
        False,
        0x08000000,  # CREATE_NO_WINDOW cho python wrapper, Chrome con sẽ tự hiện GUI trên WinSta0\Default
        None,
        cwd_buf,
        ctypes.byref(si),
        ctypes.byref(pi),
    )
    if not ok:
        return {
            "ok": False,
            "message": "Không thể khởi tạo tiến trình Login trên màn hình Windows.",
        }

    _ACTIVE_LOGIN_PROCS[account_id] = int(pi.dwProcessId)
    try:
        # Chờ tối đa 10 phút cho người dùng nhập OTP
        k32.WaitForSingleObject(pi.hProcess, 610000)
    finally:
        _ACTIVE_LOGIN_PROCS.pop(account_id, None)
        if pi.hProcess:
            k32.CloseHandle(pi.hProcess)
        if pi.hThread:
            k32.CloseHandle(pi.hThread)

    if result_file.exists():
        try:
            return json.loads(result_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "ok": False,
        "message": "Cửa sổ đăng nhập đã đóng trước khi hoàn tất lưu Cookie.",
    }


def build_playwright_proxy(proxy_row: Optional[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    if not proxy_row or not proxy_row.get("host") or not proxy_row.get("port"):
        return None
    protocol = (proxy_row.get("protocol") or "http").lower()
    server = f"{protocol}://{proxy_row['host']}:{proxy_row['port']}"
    proxy_cfg: Dict[str, str] = {"server": server}
    if proxy_row.get("username"):
        proxy_cfg["username"] = str(proxy_row["username"])
    if proxy_row.get("password"):
        proxy_cfg["password"] = str(proxy_row["password"])
    return proxy_cfg


class AccountBrowserSession:
    """
    Quản lý 1 Persistent BrowserContext duy nhất cho 1 tài khoản Muse,
    cho phép mở nhiều Tab (Page) song song bên trong cùng 1 tiến trình Chrome.
    """

    def __init__(
        self,
        account: Dict[str, Any],
        proxy: Optional[Dict[str, Any]],
        playwright_instance: Any,
        offscreen: bool = True,
    ):
        self.account = account
        self.account_id = int(account["id"])
        self.proxy = proxy
        self.pw = playwright_instance
        self.offscreen = offscreen
        self.context: Any = None
        self._lock = asyncio.Lock()
        self.submit_lock = asyncio.Lock()
        self.active_tabs = 0
        self.last_used_ts: float = time.time()

    async def ensure_context(self) -> Any:
        async with self._lock:
            if self.context is not None:
                try:
                    _ = self.context.pages
                    return self.context
                except Exception:
                    self.context = None

            profile_dir = get_account_profile_dir(
                self.account_id, self.account.get("profile_path")
            )
            await asyncio.to_thread(cleanup_orphaned_profile_processes, profile_dir)

            args = [
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--disable-dev-shm-usage",
            ]
            if self.offscreen:
                args.append("--window-position=-32000,-32000")
                args.append("--window-size=1280,800")

            proxy_cfg = build_playwright_proxy(self.proxy)

            launch_kwargs: Dict[str, Any] = {
                "user_data_dir": str(profile_dir),
                "headless": False,
                "args": args,
                "viewport": {"width": 1280, "height": 800},
                "ignore_https_errors": True,
                "accept_downloads": True,
            }
            if proxy_cfg:
                launch_kwargs["proxy"] = proxy_cfg

            try:
                self.context = await self.pw.chromium.launch_persistent_context(
                    channel="chrome", **launch_kwargs
                )
            except Exception:
                await asyncio.to_thread(cleanup_orphaned_profile_processes, profile_dir)
                await asyncio.sleep(1.0)
                self.context = await self.pw.chromium.launch_persistent_context(
                    channel="chrome", **launch_kwargs
                )

            return self.context

    async def new_tab(self) -> Any:
        ctx = await self.ensure_context()
        page = await ctx.new_page()
        self.active_tabs += 1
        self.last_used_ts = time.time()
        return page

    async def close_tab(self, page: Any) -> None:
        try:
            if page and not page.is_closed():
                await page.close()
        except Exception:
            pass
        finally:
            self.active_tabs = max(0, self.active_tabs - 1)
            self.last_used_ts = time.time()

    async def close_context(self) -> None:
        async with self._lock:
            if self.context is not None:
                try:
                    await asyncio.wait_for(self.context.close(), timeout=4.0)
                except Exception:
                    pass
                self.context = None
                self.active_tabs = 0
            profile_dir = get_account_profile_dir(
                self.account_id, self.account.get("profile_path")
            )
            await asyncio.to_thread(cleanup_orphaned_profile_processes, profile_dir)


class PlaywrightEngine:
    """
    Engine điều khiển đăng nhập 1 lần (Interactive Login), kiểm tra Cookie/Hạn mức,
    và thực thi các Tab song song kèm Auto-Approve & DOM Blob/Media Downloader.
    """

    def __init__(self) -> None:
        self._pw_context_manager: Any = None
        self._pw: Any = None
        self._pw_lock = asyncio.Lock()
        self._sessions_lock = asyncio.Lock()
        self._sessions: Dict[int, AccountBrowserSession] = {}

    async def get_playwright(self) -> Any:
        async with self._pw_lock:
            if self._pw is None:
                from playwright.async_api import async_playwright

                self._pw_context_manager = async_playwright()
                self._pw = await self._pw_context_manager.start()
            return self._pw

    async def get_or_create_session(
        self, account: Dict[str, Any], proxy: Optional[Dict[str, Any]], offscreen: bool
    ) -> AccountBrowserSession:
        async with self._sessions_lock:
            acc_id = int(account["id"])
            if acc_id in self._sessions:
                sess = self._sessions[acc_id]
                old_proxy_id = (sess.proxy or {}).get("id")
                new_proxy_id = (proxy or {}).get("id")
                if (old_proxy_id != new_proxy_id or sess.offscreen != offscreen) and sess.active_tabs == 0:
                    await sess.close_context()
                sess.offscreen = offscreen
                sess.proxy = proxy
                return sess

            pw = await self.get_playwright()
            sess = AccountBrowserSession(
                account=account, proxy=proxy, playwright_instance=pw, offscreen=offscreen
            )
            self._sessions[acc_id] = sess
            return sess

    async def close_account_session(self, account_id: int) -> None:
        sess = self._sessions.pop(account_id, None)
        if sess:
            await sess.close_context()

    async def cleanup_idle_sessions(self, idle_timeout_sec: int = 180) -> int:
        """
        Tự động đóng (Auto-Sleep) các phiên trình duyệt Chrome không còn Tab hoạt động
        sau khoảng thời gian nhàn rỗi (mặc định 180 giây) để giải phóng RAM hệ thống.
        """
        if idle_timeout_sec <= 0:
            return 0
        now_ts = time.time()
        slept_count = 0
        async with self._sessions_lock:
            for acc_id, sess in list(self._sessions.items()):
                if (
                    sess.context is not None
                    and sess.active_tabs <= 0
                    and (now_ts - sess.last_used_ts) >= idle_timeout_sec
                ):
                    await sess.close_context()
                    slept_count += 1
        return slept_count

    async def clear_account_video_memory(self, account_id: int) -> Dict[str, Any]:
        """
        Gửi chỉ thị xóa ghi chú giới hạn vùng (Region-block) trong Memory của tài khoản Muse
        để tài khoản luôn gọi trực tiếp công cụ tạo Video khi đã gắn Proxy US.
        """
        conn = get_connection()
        row = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        if not row:
            conn.close()
            return {"ok": False, "message": "Không tìm thấy tài khoản"}
        account = dict(row)
        proxy = None
        if account.get("proxy_id"):
            p_row = conn.execute("SELECT * FROM proxies WHERE id = ?", (account["proxy_id"],)).fetchone()
            if p_row:
                proxy = dict(p_row)
        conn.close()

        settings = get_settings()
        offscreen = settings.get("offscreen_mode", "1") == "1"
        session = await self.get_or_create_session(account, proxy, offscreen=offscreen)
        page = None
        try:
            async with session.submit_lock:
                page = await session.new_tab()
                await page.goto(MUSE_COMPOSER_URL, wait_until="domcontentloaded", timeout=35000)
                composer = None
                for _ in range(12):
                    composer = await self._detect_composer(page)
                    if composer is not None:
                        break
                    await asyncio.sleep(1.0)
                if composer is None:
                    return {
                        "ok": False,
                        "message": "Không tìm thấy khung Composer (Hãy kiểm tra đăng nhập tài khoản)",
                    }
                await composer.click()
                await composer.fill(
                    "Please update your memory and preferences immediately: remove any note or assumption that video generation is unavailable or region-blocked for this account. Whenever I ask for a video, always invoke the video generation tool directly without falling back to keyframes."
                )
                await asyncio.sleep(0.5)
                send_btn = page.locator("button[aria-label='Send']").first
                if await send_btn.count() > 0 and await send_btn.is_visible():
                    await send_btn.click()
                else:
                    await page.keyboard.press("Enter")
            await asyncio.sleep(8.0)
            return {
                "ok": True,
                "message": "Đã gửi lệnh làm sạch Memory giới hạn Video trên tài khoản Muse!",
            }
        except Exception as exc:
            return {"ok": False, "message": f"Lỗi khi xóa Memory Video: {exc}"}
        finally:
            if page is not None:
                await session.close_tab(page)

    async def shutdown(self) -> None:
        for acc_id in list(self._sessions.keys()):
            await self.close_account_session(acc_id)
        if self._pw_context_manager is not None:
            try:
                await self._pw_context_manager.__aexit__(None, None, None)
            except Exception:
                pass
            self._pw = None
            self._pw_context_manager = None

    async def interactive_login(self, account_id: int) -> Dict[str, Any]:
        """
        Cơ chế Quản lý Phiên & Đăng nhập 1 lần (Persistent Profile):
        - Mở Chrome trực quan (headless=False, --no-sandbox) tới https://muse.ai/?open_composer=1
        - Người dùng nhập Email, OTP 6 số từ Gmail và tích Remember this device.
        - Vòng lặp mỗi 2 giây kiểm tra DOM/Cookie. Ngay khi phát hiện composer xuất hiện
          cùng cookie xác thực của Muse (hatch_native_auth_device / __Host-hatch_one_tap),
          tự động trích xuất Cookie lưu vào DB, cập nhật trạng thái thành 'Cookie tốt'
          kèm thời gian và đóng cửa sổ trình duyệt.
        """
        await self.close_account_session(account_id)

        # Nếu server đang chạy trong Desktop cô lập (ví dụ WinSta0\exebox-...),
        # khởi chạy tiến trình con gắn trực tiếp vào WinSta0\Default để cửa sổ Chrome hiện ngay trước mắt người dùng.
        if sys.platform == "win32" and not _is_current_desktop_default():
            return await asyncio.to_thread(
                _run_login_subprocess_on_default_desktop, account_id
            )

        conn = get_connection()
        acc_row = conn.execute(
            "SELECT * FROM accounts WHERE id = ?", (account_id,)
        ).fetchone()
        if not acc_row:
            conn.close()
            return {"ok": False, "message": "Không tìm thấy tài khoản"}
        account = dict(acc_row)

        proxy = None
        if account.get("proxy_id"):
            p_row = conn.execute(
                "SELECT * FROM proxies WHERE id = ?", (account["proxy_id"],)
            ).fetchone()
            if p_row:
                proxy = dict(p_row)
        conn.close()

        profile_dir = get_account_profile_dir(account_id, account.get("profile_path"))
        await asyncio.to_thread(cleanup_orphaned_profile_processes, profile_dir)
        await asyncio.sleep(0.5)

        pw = await self.get_playwright()

        args = [
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--window-position=120,80",
            "--window-size=1280,840",
        ]
        launch_kwargs: Dict[str, Any] = {
            "user_data_dir": str(profile_dir),
            "headless": False,
            "args": args,
            "viewport": {"width": 1280, "height": 800},
            "ignore_https_errors": True,
        }
        proxy_cfg = build_playwright_proxy(proxy)
        if proxy_cfg:
            launch_kwargs["proxy"] = proxy_cfg

        context = None
        try:
            try:
                context = await pw.chromium.launch_persistent_context(
                    channel="chrome", **launch_kwargs
                )
            except Exception:
                await asyncio.to_thread(cleanup_orphaned_profile_processes, profile_dir)
                await asyncio.sleep(1.2)
                try:
                    context = await pw.chromium.launch_persistent_context(
                        channel="chrome", **launch_kwargs
                    )
                except Exception:
                    context = await pw.chromium.launch_persistent_context(**launch_kwargs)

            page = context.pages[0] if context.pages else await context.new_page()
            try:
                await page.bring_to_front()
            except Exception:
                pass
            try:
                await page.goto(MUSE_COMPOSER_URL, wait_until="domcontentloaded", timeout=45000)
            except Exception:
                # Giữ cửa sổ Chrome mở ngay cả khi Proxy phản hồi chậm ở lần tải đầu tiên
                pass

            logged_in = False
            last_valid_cookies: List[Dict[str, Any]] = []
            consecutive_ready = 0

            for _ in range(300):
                await asyncio.sleep(2.0)
                if page.is_closed() or len(context.pages) == 0:
                    if any(
                        c.get("name", "").lower()
                        in ("hatch_native_auth_device", "__host-hatch_one_tap", "hatch_sess")
                        for c in last_valid_cookies
                    ):
                        logged_in = True
                    break

                try:
                    last_valid_cookies = await context.cookies()
                except Exception:
                    pass

                try:
                    user_clicked_save = await page.evaluate(
                        """() => {
                            if (window.__museConfirmLogin === true) return true;
                            if (!document.getElementById('muse-studio-login-helper') && document.body) {
                                const bar = document.createElement('div');
                                bar.id = 'muse-studio-login-helper';
                                bar.style.cssText = 'position:fixed;bottom:16px;right:16px;z-index:2147483647;background:#111420;border:2px solid #6366F1;color:#fff;padding:10px 14px;border-radius:12px;font-family:sans-serif;font-size:13px;box-shadow:0 10px 25px rgba(0,0,0,0.6);display:flex;align-items:center;gap:10px;';
                                const label = document.createElement('span');
                                label.textContent = '🔐 Muse Studio: Khi đã vào giao diện chính →';
                                const btn = document.createElement('button');
                                btn.textContent = '✅ Lưu Cookie & Đóng';
                                btn.style.cssText = 'background:#6366F1;color:#fff;border:none;padding:6px 12px;border-radius:8px;font-weight:bold;cursor:pointer;';
                                btn.addEventListener('click', () => {
                                    window.__museConfirmLogin = true;
                                    btn.textContent = '⏳ Đang lưu...';
                                });
                                bar.appendChild(label);
                                bar.appendChild(btn);
                                document.body.appendChild(bar);
                            }
                            return false;
                        }"""
                    )
                    if user_clicked_save:
                        logged_in = True
                        break
                except Exception:
                    pass

                is_login_form = False
                try:
                    otp_or_email = await page.locator(
                        "input[type='email'], input[type='password'], input[autocomplete='one-time-code'], input[placeholder*='code' i], input[placeholder*='OTP' i]"
                    ).count()
                    if otp_or_email > 0:
                        is_login_form = True
                except Exception:
                    pass

                composer_found = await self._detect_composer(page)

                has_muse_auth_cookie = any(
                    c.get("name", "").lower()
                    in (
                        "hatch_native_auth_device",
                        "__host-hatch_one_tap",
                        "c_user",
                        "xs",
                        "sessionid",
                    )
                    for c in last_valid_cookies
                )

                if composer_found is not None and not is_login_form and has_muse_auth_cookie:
                    consecutive_ready += 1
                    if consecutive_ready >= 2:
                        logged_in = True
                        break
                else:
                    consecutive_ready = 0

            if logged_in and last_valid_cookies:
                cookie_file = profile_dir / "cookies.json"
                cookie_file.write_text(
                    json.dumps(last_valid_cookies, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                conn = get_connection()
                conn.execute(
                    """
                    UPDATE accounts
                    SET cookie_status = 'Cookie tốt',
                        cookie_updated_at = ?,
                        quota_status = 'Còn hạn mức (100%)',
                        profile_path = ?
                    WHERE id = ?
                    """,
                    (now_str, str(profile_dir), account_id),
                )
                conn.commit()
                conn.close()
                try:
                    await asyncio.wait_for(context.close(), timeout=3.0)
                except Exception:
                    pass
                await asyncio.to_thread(cleanup_orphaned_profile_processes, profile_dir)
                return {
                    "ok": True,
                    "cookie_status": "Cookie tốt",
                    "cookie_updated_at": now_str,
                    "message": "Đăng nhập thành công! Đã trích xuất Cookie và lưu Persistent Profile.",
                }
            else:
                try:
                    await asyncio.wait_for(context.close(), timeout=3.0)
                except Exception:
                    pass
                await asyncio.to_thread(cleanup_orphaned_profile_processes, profile_dir)
                return {
                    "ok": False,
                    "message": "Cửa sổ đăng nhập đã đóng hoặc hết thời gian chờ trước khi xác nhận đăng nhập.",
                }
        except Exception as exc:
            if context:
                try:
                    await asyncio.wait_for(context.close(), timeout=3.0)
                except Exception:
                    pass
            await asyncio.to_thread(cleanup_orphaned_profile_processes, profile_dir)
            return {"ok": False, "message": f"Lỗi khi mở trình duyệt Login: {exc}"}

    async def check_account_cookie_and_quota(
        self, account_id: int, check_quota: bool = False
    ) -> Dict[str, Any]:
        """
        Kiểm tra nhanh trạng thái Cookie & Hạn mức của tài khoản từ Persistent Profile.
        """
        conn = get_connection()
        row = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        if not row:
            conn.close()
            return {"ok": False, "message": "Không tìm thấy tài khoản"}
        acc = dict(row)
        conn.close()

        profile_dir = get_account_profile_dir(account_id, acc.get("profile_path"))
        cookie_file = profile_dir / "cookies.json"
        chromium_cookies_db = profile_dir / "Default" / "Network" / "Cookies"
        chromium_cookies_alt = profile_dir / "Default" / "Cookies"

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        has_valid_cookie = False

        if cookie_file.exists():
            try:
                cookies = json.loads(cookie_file.read_text(encoding="utf-8"))
                now_ts = time.time()
                valid_list = [
                    c
                    for c in cookies
                    if c.get("expires", -1) in (-1, 0) or c.get("expires", 0) > now_ts
                ]
                if len(valid_list) > 0:
                    has_valid_cookie = True
            except Exception:
                pass

        if not has_valid_cookie and (chromium_cookies_db.exists() or chromium_cookies_alt.exists()):
            has_valid_cookie = True

        cookie_status = "Cookie tốt" if has_valid_cookie else "Hết hạn"
        if not cookie_file.exists() and not chromium_cookies_db.exists() and not chromium_cookies_alt.exists():
            cookie_status = "Chưa có"

        quota_status = acc.get("quota_status") or "Chưa kiểm tra"
        if check_quota:
            quota_status = "Còn hạn mức (100%)" if cookie_status == "Cookie tốt" else "Cần đăng nhập"

        conn = get_connection()
        conn.execute(
            """
            UPDATE accounts
            SET cookie_status = ?,
                cookie_updated_at = CASE WHEN ? = 'Cookie tốt' THEN ? ELSE cookie_updated_at END,
                quota_status = ?
            WHERE id = ?
            """,
            (cookie_status, cookie_status, now_str, quota_status, account_id),
        )
        conn.commit()
        conn.close()

        return {
            "ok": True,
            "account_id": account_id,
            "cookie_status": cookie_status,
            "quota_status": quota_status,
            "cookie_updated_at": now_str if cookie_status == "Cookie tốt" else acc.get("cookie_updated_at"),
        }

    async def _detect_composer(self, page: Any) -> Optional[Any]:
        for sel in COMPOSER_SELECTORS:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    return loc
            except Exception:
                continue
        return None

    async def _auto_approve_step(self, page: Any) -> bool:
        """
        Kiểm tra DOM xem Muse có hiển thị nút xác nhận (Approve, Allow, Cho phép, Continue)
        không và tự động click ngay lập tức.
        """
        for btn_text in APPROVE_BUTTON_TEXTS:
            try:
                btn = page.get_by_role("button", name=re.compile(rf"^{re.escape(btn_text)}$", re.I)).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click(timeout=2000)
                    return True
            except Exception:
                pass
            try:
                btn2 = page.locator(f"button:has-text('{btn_text}')").first
                if await btn2.count() > 0 and await btn2.is_visible():
                    await btn2.click(timeout=2000)
                    return True
            except Exception:
                pass
        return False

    async def _snapshot_existing_media_urls(self, page: Any) -> Set[str]:
        """Ghi nhận toàn bộ các URL video/ảnh đã có sẵn trên trang trước khi gửi Prompt mới."""
        try:
            urls = await page.evaluate(
                """() => {
                    const list = [];
                    document.querySelectorAll('video').forEach(v => {
                        if (v.src) list.push(v.src);
                        v.querySelectorAll('source').forEach(s => { if (s.src) list.push(s.src); });
                    });
                    document.querySelectorAll('img').forEach(img => {
                        if (img.src) list.push(img.src);
                    });
                    return list;
                }"""
            )
            return set(urls or [])
        except Exception:
            return set()

    async def execute_task_on_tab(
        self,
        task: Dict[str, Any],
        account: Dict[str, Any],
        proxy: Optional[Dict[str, Any]],
        project_name: str,
        settings: Dict[str, str],
        progress_callback: Callable[[int, str], None],
        cancel_event: asyncio.Event,
    ) -> Tuple[bool, str, Optional[str], float]:
        """
        Thực thi 1 tác vụ trên 1 Tab (Page) nằm trong BrowserContext của tài khoản.
        Trả về: (success, status_message, output_file_path, file_size_mb)
        """
        task_type = (task.get("task_type") or "video").lower()
        aspect_ratio = task.get("aspect_ratio") or "16:9"
        raw_prompt = task.get("prompt_text") or ""
        task_name = task.get("task_name") or f"Task_{task['id']}"

        ref_images: List[str] = []
        if task.get("ref_images_json"):
            try:
                parsed = json.loads(task["ref_images_json"])
                if isinstance(parsed, list):
                    ref_images = [str(x) for x in parsed if x and Path(str(x)).exists()]
            except Exception:
                ref_images = []

        wrapped_prompt = wrap_prompt(
            raw_prompt=raw_prompt,
            task_type=task_type,
            aspect_ratio=aspect_ratio,
            has_ref_images=len(ref_images) > 0,
            settings=settings,
        )

        offscreen = settings.get("offscreen_mode", "1") == "1"
        auto_approve = settings.get("auto_approve", "1") == "1"
        timeout_sec = (
            int(settings.get("image_timeout_sec", "300") or 300)
            if task_type == "image"
            else int(settings.get("video_timeout_sec", "600") or 600)
        )

        output_root = Path(settings.get("output_dir") or "output")
        (output_root / "IMG").mkdir(parents=True, exist_ok=True)
        (output_root / "VIDEO").mkdir(parents=True, exist_ok=True)
        safe_task = re.sub(r'[<>:"/\\|?*]', "_", task_name.strip()) or f"Task_{task['id']}"
        sub_folder = "IMG" if task_type == "image" else "VIDEO"
        project_out_dir = output_root / sub_folder
        if settings.get("group_output_by_project", "0") == "1":
            safe_proj = re.sub(r'[<>:"/\\|?*]', "_", (project_name or "Mặc định").strip()) or "Mặc_định"
            project_out_dir = project_out_dir / safe_proj
        project_out_dir.mkdir(parents=True, exist_ok=True)

        ext = ".png" if task_type == "image" else ".mp4"
        target_file = project_out_dir / f"{safe_task}{ext}"

        progress_callback(5, "Khởi tạo Tab trình duyệt...")
        session = await self.get_or_create_session(account, proxy, offscreen=offscreen)
        page = None

        try:
            initial_media_urls: Set[str] = set()
            async with session.submit_lock:
                page = await session.new_tab()

                progress_callback(10, "Đang mở Muse Composer...")
                try:
                    nav_timeout = 20000 if session.proxy else 45000
                    await page.goto(MUSE_COMPOSER_URL, wait_until="domcontentloaded", timeout=nav_timeout)
                except Exception as nav_exc:
                    if session.proxy:
                        # Proxy bị Dead hoặc chặn kết nối tới Muse -> Tự động gỡ Proxy Dead và chuyển về kết nối trực tiếp
                        dead_proxy_id = session.proxy.get("id")
                        try:
                            conn = get_connection()
                            if dead_proxy_id:
                                conn.execute(
                                    "UPDATE proxies SET status = 'Dead', assigned_account_id = NULL WHERE id = ?",
                                    (dead_proxy_id,),
                                )
                            conn.execute(
                                "UPDATE accounts SET proxy_id = NULL WHERE id = ?",
                                (account["id"],),
                            )
                            conn.commit()
                            conn.close()
                        except Exception:
                            pass
                        progress_callback(12, "Proxy phản hồi chậm/Dead, tự động chuyển sang kết nối trực tiếp...")
                        await session.close_tab(page)
                        await session.close_context()
                        session.proxy = None
                        page = await session.new_tab()
                        await page.goto(MUSE_COMPOSER_URL, wait_until="domcontentloaded", timeout=45000)
                    else:
                        raise nav_exc

                if cancel_event.is_set():
                    return False, "Đã dừng bởi người dùng", None, 0.0

                composer = None
                for _ in range(15):
                    if cancel_event.is_set():
                        return False, "Đã dừng bởi người dùng", None, 0.0
                    if auto_approve:
                        await self._auto_approve_step(page)
                    composer = await self._detect_composer(page)
                    if composer is not None:
                        break
                    await asyncio.sleep(1.0)

                if composer is None:
                    return (
                        False,
                        "Không tìm thấy khung Composer (Tài khoản chưa đăng nhập hoặc Cookie hết hạn)",
                        None,
                        0.0,
                    )

                # Chờ 1.5s để Main chat hoàn tất hydrate trước khi chuyển sang New side chat
                await asyncio.sleep(1.5)
                pre_side_urls = await self._snapshot_existing_media_urls(page)
                initial_media_urls.update(pre_side_urls)

                # Chờ nút New side chat xuất hiện, click và xác nhận đã vào Side chat (có nút Back to main chat)
                for _ in range(10):
                    try:
                        back_btn = page.locator("button[aria-label='Back to main chat']").first
                        if await back_btn.count() > 0 and await back_btn.is_visible():
                            break
                        new_side_btn = page.locator(
                            "button[aria-label='New side chat'], button[title='New side chat']"
                        ).first
                        if await new_side_btn.count() > 0:
                            try:
                                await new_side_btn.click(force=True, timeout=2500)
                            except Exception:
                                await page.evaluate(
                                    """() => {
                                        const btn = document.querySelector("button[aria-label='New side chat'], button[title='New side chat']");
                                        if (btn) btn.click();
                                    }"""
                                )
                            await asyncio.sleep(1.2)
                            new_comp = await self._detect_composer(page)
                            if new_comp is not None:
                                composer = new_comp
                            if await back_btn.count() > 0 and await back_btn.is_visible():
                                break
                    except Exception:
                        pass
                    await asyncio.sleep(0.8)

                post_side_urls = await self._snapshot_existing_media_urls(page)
                initial_media_urls.update(post_side_urls)

                # Đính kèm ảnh tham chiếu nếu có
                if ref_images:
                    progress_callback(18, f"Đang tải lên {len(ref_images)} ảnh tham chiếu...")
                    uploaded = False
                    try:
                        file_input = page.locator("input[type='file']").first
                        if await file_input.count() > 0:
                            await file_input.set_input_files(ref_images)
                            uploaded = True
                            await asyncio.sleep(2.5)
                    except Exception:
                        pass

                    if not uploaded:
                        try:
                            async with page.expect_file_chooser(timeout=5000) as fc_info:
                                attach_btn = page.locator(
                                    "button[aria-label='Attach file'], button[aria-label*='attach' i], button[aria-label*='upload' i]"
                                ).first
                                await attach_btn.click()
                            file_chooser = await fc_info.value
                            await file_chooser.set_files(ref_images)
                            await asyncio.sleep(2.5)
                        except Exception:
                            pass

                    post_upload_urls = await self._snapshot_existing_media_urls(page)
                    initial_media_urls.update(post_upload_urls)

                # Điền prompt đã bọc mẫu vào Composer và bấm nút Send
                progress_callback(25, "Đang gửi Prompt...")
                new_comp = await self._detect_composer(page)
                if new_comp is not None:
                    composer = new_comp
                await composer.click()
                await composer.fill(wrapped_prompt)
                await asyncio.sleep(0.6)

                send_btn = page.locator("button[aria-label='Send']").first
                if await send_btn.count() > 0 and await send_btn.is_visible():
                    await send_btn.click()
                else:
                    await page.keyboard.press("Enter")

                prompt_anchor = raw_prompt.strip()[:65]

                # Chờ Muse khởi tạo URL /thread/<uuid> hoặc hiển thị bong bóng câu lệnh trước khi mở Tab kế tiếp
                for _ in range(10):
                    await asyncio.sleep(0.6)
                    if "/thread/" in (page.url or ""):
                        break

            # Bắt đầu vòng lặp chờ render + Auto-Approve mỗi 2 giây (chạy song song trên tất cả các Tab)
            start_wait = time.time()
            media_downloaded = False
            saw_generating_state = False

            while (time.time() - start_wait) < timeout_sec:
                if cancel_event.is_set():
                    return False, "Đã dừng bởi người dùng", None, 0.0

                elapsed = int(time.time() - start_wait)
                pct = min(94, 28 + int((elapsed / max(1, timeout_sec)) * 66))

                if auto_approve:
                    approved = await self._auto_approve_step(page)
                    if approved:
                        progress_callback(pct, f"Đã tự động bấm Approve ({elapsed}s)...")

                # Kiểm tra trạng thái hiển thị trên giao diện Muse (Generating image / Generating video)
                gen_status = await self._check_muse_generation_state(page, prompt_anchor)
                if gen_status.get("is_generating"):
                    saw_generating_state = True
                    progress_callback(pct, f"Muse đang tạo media ({elapsed}s)...")
                else:
                    progress_callback(pct, f"Đang chờ kết quả ({elapsed}s)...")

                # Kiểm tra DOM xem có thẻ video/image kết quả MỚI nằm SAU bong bóng prompt của tác vụ này
                if elapsed >= 6:
                    dom_url = await self._extract_new_dom_media_url(
                        page, task_type, list(initial_media_urls), prompt_anchor
                    )
                    if dom_url:
                        progress_callback(96, "Đang trích xuất & lưu file độ phân giải gốc...")
                        ok_dl = await self._download_media_url(page, dom_url, target_file)
                        if ok_dl:
                            media_downloaded = True
                            break
                        else:
                            # Nếu URL này trùng nội dung với file của tác vụ trước đó, đưa vào danh sách bỏ qua
                            initial_media_urls.add(dom_url)

                # Kiểm tra nếu Muse báo lỗi không tạo được media
                if elapsed >= 15 and not gen_status.get("is_generating"):
                    err_reason = gen_status.get("error_reason")
                    if err_reason:
                        return False, err_reason, None, 0.0

                await asyncio.sleep(2.0)

            if not media_downloaded:
                return False, f"Quá thời gian chờ ({timeout_sec}s) chưa nhận được file media", None, 0.0

            size_mb = round(target_file.stat().st_size / (1024 * 1024), 2)
            progress_callback(100, "Hoàn thành")
            return True, "Hoàn thành", str(target_file), size_mb

        except Exception as exc:
            return False, f"Lỗi thực thi: {exc}", None, 0.0
        finally:
            if page is not None:
                await session.close_tab(page)

    async def _check_muse_generation_state(
        self, page: Any, prompt_anchor: str = ""
    ) -> Dict[str, Any]:
        """
        Kiểm tra xem Muse đang trong trạng thái Generating hay đã dừng/báo lỗi.
        Chỉ kiểm tra các phần tử DOM xuất hiện SAU bong bóng tin nhắn chứa prompt_anchor
        để không bị nhầm với lịch sử chat cũ ở Main chat.
        """
        try:
            return await page.evaluate(
                """(promptSnippet) => {
                    const cleanSnippet = (promptSnippet || '').trim();
                    let promptNode = null;
                    if (cleanSnippet.length >= 6) {
                        const candidates = Array.from(document.querySelectorAll('div, p, span'));
                        for (let i = candidates.length - 1; i >= 0; i--) {
                            const el = candidates[i];
                            if (el.closest('textarea, input, button, nav, aside, [aria-label*="Muse"]')) continue;
                            const txt = (el.textContent || '').trim();
                            if (txt.includes(cleanSnippet)) {
                                const childHas = Array.from(el.children).some(
                                    c => (c.textContent || '').includes(cleanSnippet)
                                );
                                if (!childHas) {
                                    promptNode = el;
                                    break;
                                }
                            }
                        }
                    }

                    // Thu thập toàn bộ text của các node nằm SAU promptNode trong cột chat chính ở giữa
                    let postPromptText = '';
                    if (promptNode) {
                        const allNodes = Array.from(document.querySelectorAll('div, p, span'));
                        for (const el of allNodes) {
                            if (el === promptNode || el.contains(promptNode) || promptNode.contains(el)) continue;
                            if (el.closest('textarea, input, nav, aside, [aria-label*="Muse"]')) continue;
                            const r = el.getBoundingClientRect();
                            // Chỉ xét các tin nhắn nằm trong cột khung chat trung tâm (loại trừ cột lịch sử bên phải r.left > 920)
                            if (r.width > 0 && (r.left < 200 || r.left > 920)) continue;
                            if (promptNode.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING) {
                                const t = (el.innerText || el.textContent || '').trim();
                                if (t) postPromptText += ' ' + t;
                            }
                        }
                    } else {
                        postPromptText = document.body ? document.body.innerText : '';
                    }

                    const is_generating = (
                        postPromptText.includes('Generating image') ||
                        postPromptText.includes('Generating video') ||
                        postPromptText.includes('Creating video') ||
                        postPromptText.includes('Creating image') ||
                        !!document.querySelector('button[aria-label*="Stop" i]')
                    );
                    let error_reason = null;
                    if (!is_generating && promptNode) {
                        const lower = postPromptText.toLowerCase();
                        if (
                            lower.includes("không khả dụng ở quốc gia") ||
                            lower.includes("không render được") ||
                            lower.includes("couldn't create that video") ||
                            lower.includes("not available in your country") ||
                            lower.includes("can't create videos") ||
                            lower.includes("unable to create")
                        ) {
                            error_reason = "Muse báo tính năng tạo Video bị giới hạn vùng (Region-block) trên tài khoản/IP hiện tại (Cần tài khoản & Proxy Mỹ/US để tạo Video)";
                        }
                    }
                    return { is_generating, error_reason };
                }""",
                prompt_anchor,
            )
        except Exception:
            return {"is_generating": False, "error_reason": None}

    async def _extract_new_dom_media_url(
        self,
        page: Any,
        task_type: str,
        ignore_urls: List[str],
        prompt_anchor: str = "",
    ) -> Optional[str]:
        """
        Trích xuất URL của media kết quả mới trong khung chat:
        - Neo vị trí DOM (DOM Position Anchoring): CHỈ nhận ảnh/video nằm SAU (DOCUMENT_POSITION_FOLLOWING)
          bong bóng tin nhắn chứa prompt_anchor của chính tác vụ này, và TRƯỚC bất kỳ bong bóng prompt kế tiếp nào.
        - Loại trừ 100% ảnh lịch sử ở trên, video Mascot Avatar 480x480 và ảnh OpenGraph (/api/og-metadata/).
        """
        try:
            return await page.evaluate(
                """({ ignoreList, taskType, promptSnippet }) => {
                    const ignoreSet = new Set(ignoreList || []);

                    // 1. Tìm bong bóng tin nhắn chứa câu lệnh promptSnippet của tác vụ hiện tại
                    let promptNode = null;
                    const cleanSnippet = (promptSnippet || '').trim();
                    if (cleanSnippet.length >= 6) {
                        const candidates = Array.from(document.querySelectorAll('div, p, span'));
                        for (let i = candidates.length - 1; i >= 0; i--) {
                            const el = candidates[i];
                            if (el.closest('textarea, input, button, nav, aside, [aria-label*="Muse"]')) continue;
                            const txt = (el.textContent || '').trim();
                            if (txt.includes(cleanSnippet)) {
                                const childHas = Array.from(el.children).some(
                                    c => (c.textContent || '').includes(cleanSnippet)
                                );
                                if (!childHas) {
                                    promptNode = el;
                                    break;
                                }
                            }
                        }
                    }

                    // Nếu chưa tìm thấy bong bóng tin nhắn của tác vụ này trong DOM thì tuyệt đối không lấy media cũ
                    if (cleanSnippet.length >= 6 && !promptNode) {
                        return null;
                    }

                    // 2. Tìm xem có bong bóng câu lệnh nào khác nằm SAU promptNode không (nếu chung luồng chat)
                    let nextPromptNode = null;
                    if (promptNode) {
                        const allBlocks = Array.from(document.querySelectorAll('div, p, span'));
                        for (const el of allBlocks) {
                            if (el === promptNode || el.contains(promptNode) || promptNode.contains(el)) continue;
                            if (el.closest('textarea, input, button, nav, aside, [aria-label*="Muse"]')) continue;
                            const txt = (el.textContent || '').trim();
                            if (
                                (txt.startsWith('Create 1 image(s)') || txt.startsWith('Create a video')) &&
                                !txt.includes(cleanSnippet)
                            ) {
                                const childHas = Array.from(el.children).some(
                                    c => (c.textContent || '').trim().startsWith('Create ')
                                );
                                if (!childHas && (promptNode.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING)) {
                                    nextPromptNode = el;
                                    break;
                                }
                            }
                        }
                    }

                    const isValidPosition = (mediaEl) => {
                        if (!promptNode) return true;
                        const afterOurPrompt = Boolean(
                            promptNode.compareDocumentPosition(mediaEl) & Node.DOCUMENT_POSITION_FOLLOWING
                        );
                        if (!afterOurPrompt) return false;
                        if (nextPromptNode) {
                            const afterNextPrompt = Boolean(
                                nextPromptNode.compareDocumentPosition(mediaEl) & Node.DOCUMENT_POSITION_FOLLOWING
                            );
                            if (afterNextPrompt) return false;
                        }
                        return true;
                    };

                    if (taskType === 'video' || taskType === 'img2vid') {
                        const videos = Array.from(document.querySelectorAll('video'));
                        for (let i = videos.length - 1; i >= 0; i--) {
                            const v = videos[i];
                            if (
                                v.hasAttribute('data-hatch-avatar-layer') ||
                                v.hasAttribute('data-hatch-avatar-slot') ||
                                v.closest('[aria-label*="Muse"]')
                            ) {
                                continue;
                            }
                            if (!isValidPosition(v)) continue;
                            if (v.videoWidth === 0 || v.videoHeight === 0) {
                                try { v.preload = 'auto'; } catch (e) {}
                                continue;
                            }
                            if (v.videoWidth === 480 && v.videoHeight === 480) continue;
                            if (Math.max(v.videoWidth, v.videoHeight) < 500) continue;
                            if (v.src && (v.src.startsWith('http') || v.src.startsWith('blob:')) && !ignoreSet.has(v.src)) {
                                return v.src;
                            }
                            const srcEl = v.querySelector('source');
                            if (srcEl && srcEl.src && (srcEl.src.startsWith('http') || srcEl.src.startsWith('blob:')) && !ignoreSet.has(srcEl.src)) {
                                return srcEl.src;
                            }
                        }
                        return null;
                    } else {
                        const genImgs = Array.from(
                            document.querySelectorAll('button[aria-label^="Open generated image"] img, img.outline-media-protection-border')
                        );
                        for (let i = genImgs.length - 1; i >= 0; i--) {
                            const img = genImgs[i];
                            if (img.closest('[aria-label*="Muse"]')) continue;
                            const src = img.src || '';
                            if (!src || ignoreSet.has(src)) continue;
                            if (
                                src.includes('/api/og-metadata/') ||
                                src.includes('/_next/') ||
                                src.includes('/images/') ||
                                src.includes('favicon') ||
                                src.includes('avatar')
                            ) {
                                continue;
                            }
                            if (!isValidPosition(img)) continue;
                            if (
                                img.complete &&
                                img.naturalWidth >= 512 &&
                                img.naturalHeight >= 512 &&
                                (src.startsWith('blob:') || src.startsWith('http'))
                            ) {
                                return src;
                            }
                        }
                        return null;
                    }
                }""",
                {
                    "ignoreList": ignore_urls,
                    "taskType": task_type,
                    "promptSnippet": prompt_anchor,
                },
            )
        except Exception:
            return None

    def _is_duplicate_of_other_task(self, raw_bytes: bytes, target_file: Path) -> bool:
        """
        Kiểm tra mã băm SHA-256 để đảm bảo file tải về không bao giờ trùng lặp nội dung
        với bất kỳ file đã hoàn thành nào của các tác vụ khác trong cùng thư mục dự án.
        """
        try:
            new_hash = hashlib.sha256(raw_bytes).hexdigest()
            parent = target_file.parent
            if not parent.exists():
                return False
            target_resolved = target_file.resolve()
            for existing in parent.iterdir():
                if not existing.is_file():
                    continue
                if existing.resolve() == target_resolved:
                    continue
                if existing.stat().st_size == len(raw_bytes):
                    old_hash = hashlib.sha256(existing.read_bytes()).hexdigest()
                    if old_hash == new_hash:
                        return True
            return False
        except Exception:
            return False

    async def _download_media_url(self, page: Any, url: str, target_file: Path) -> bool:
        """
        Tải trực tiếp cả URL dạng blob:https://muse.ai/... (từ bộ nhớ trình duyệt)
        lẫn URL https://... về ổ cứng với độ phân giải gốc (2048x1152 / 1080p).
        """
        # 1. Trích xuất trực tiếp qua fetch() bên trong ngữ cảnh trang (hỗ trợ hoàn hảo blob: URL)
        try:
            b64_data = await page.evaluate(
                """async (targetUrl) => {
                    const resp = await fetch(targetUrl);
                    if (!resp.ok) return null;
                    const blob = await resp.blob();
                    return await new Promise((resolve, reject) => {
                        const reader = new FileReader();
                        reader.onloadend = () => {
                            const res = reader.result || '';
                            const idx = res.indexOf(',');
                            resolve(idx !== -1 ? res.slice(idx + 1) : null);
                        };
                        reader.onerror = () => resolve(null);
                        reader.readAsDataURL(blob);
                    });
                }""",
                url,
            )
            if b64_data:
                raw_bytes = base64.b64decode(b64_data)
                if raw_bytes and len(raw_bytes) > 10_000:
                    if self._is_duplicate_of_other_task(raw_bytes, target_file):
                        return False
                    target_file.write_bytes(raw_bytes)
                    return True
        except Exception:
            pass

        # 2. Fallback cho URL http/https thông thường
        if url.startswith("http"):
            try:
                resp = await page.context.request.get(url, timeout=60000)
                if resp.ok:
                    data = await resp.body()
                    if data and len(data) > 10_000:
                        if self._is_duplicate_of_other_task(data, target_file):
                            return False
                        target_file.write_bytes(data)
                        return True
            except Exception:
                pass

            try:
                async with httpx.AsyncClient(follow_redirects=True, timeout=60.0, verify=False) as client:
                    r = await client.get(url)
                    if r.status_code == 200 and len(r.content) > 10_000:
                        if self._is_duplicate_of_other_task(r.content, target_file):
                            return False
                        target_file.write_bytes(r.content)
                        return True
            except Exception:
                pass

        return False


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "--interactive-login":
        acc_id_arg = int(sys.argv[2])
        res_file_arg = Path(sys.argv[3])

        async def _cli_login():
            eng = PlaywrightEngine()
            try:
                res = await eng.interactive_login(acc_id_arg)
            except Exception as exc:
                res = {"ok": False, "message": f"Lỗi khi mở trình duyệt Login: {exc}"}
            finally:
                await eng.shutdown()
            res_file_arg.parent.mkdir(parents=True, exist_ok=True)
            res_file_arg.write_text(
                json.dumps(res, ensure_ascii=False), encoding="utf-8"
            )

        asyncio.run(_cli_login())
