import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.database import BASE_DIR, get_settings, update_settings

VERSION_FILE = BASE_DIR / "version.json"

# Các thư mục/file dữ liệu người dùng và công cụ Admin TUYỆT ĐỐI KHÔNG BAO GIỜ ghi đè khi cập nhật
PROTECTED_PREFIXES = (
    ".muse",
    "output",
    ".venv",
    "venv",
    ".git",
    "dist_update",
    "dist_package",
    "__pycache__",
)
ADMIN_ONLY_FILES = {
    "muse_keygen_admin.py",
    "run_keygen_admin.bat",
    "publish_update_admin.py",
    "publish_update_admin.bat",
    "package_customer_release.py",
    "package_customer_release.bat",
}


def _parse_semver(ver_str: str) -> Tuple[int, ...]:
    nums = [int(x) for x in re.findall(r"\d+", ver_str or "0.0.0")]
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums[:4])


def get_local_version_info() -> Dict[str, Any]:
    default_info = {
        "version": "1.2.0",
        "released_at": "21/10/2026",
        "update_manifest_url": "",
        "download_zip_url": "",
        "changelog": [],
    }
    try:
        if VERSION_FILE.exists():
            data = json.loads(VERSION_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                default_info.update(data)
    except Exception:
        pass

    settings = get_settings()
    custom_url = (settings.get("update_source_url") or "").strip()
    if custom_url:
        default_info["update_manifest_url"] = custom_url

    return default_info


def resolve_manifest_and_zip_urls(raw_url: str, branch: str = "master") -> Tuple[str, str]:
    """
    Chuyển đổi thông minh từ Link GitHub Repo (VD: https://github.com/user/repo)
    hoặc Link trực tiếp thành cặp (manifest_json_url, update_zip_url).
    """
    u = (raw_url or "").strip().rstrip("/")
    if not u:
        return "", ""

    # Nếu người dùng nhập link GitHub repo: https://github.com/owner/repo
    m = re.match(r"^https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?$", u, re.IGNORECASE)
    if m:
        owner, repo = m.group(1), m.group(2)
        manifest_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/version.json"
        zip_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/dist_update/muse_update.zip"
        return manifest_url, zip_url

    # Nếu người dùng nhập trực tiếp link tới version.json
    if u.lower().endswith("version.json"):
        base_parent = u.rsplit("/", 1)[0]
        return u, f"{base_parent}/dist_update/muse_update.zip"

    return u, ""


def _http_get_json(url: str, timeout: float = 8.0) -> Dict[str, Any]:
    sep = "&" if "?" in url else "?"
    bust_url = f"{url}{sep}_t={int(time.time())}"
    req = urllib.request.Request(
        bust_url,
        headers={
            "User-Agent": "MuseStudio-Updater/1.2",
            "Cache-Control": "no-cache",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw)


def check_for_updates(custom_source_url: Optional[str] = None) -> Dict[str, Any]:
    """
    Kiểm tra phiên bản mới từ Server / GitHub.
    Nếu truyền custom_source_url thì lưu lại vào cấu hình để các lần sau dùng luôn.
    """
    if custom_source_url is not None and custom_source_url.strip():
        update_settings({"update_source_url": custom_source_url.strip()})

    local_info = get_local_version_info()
    local_ver = str(local_info.get("version") or "1.0.0")
    source_url = (
        (custom_source_url or "").strip()
        or str(local_info.get("update_manifest_url") or "").strip()
    )

    result = {
        "ok": True,
        "has_update": False,
        "local_version": local_ver,
        "local_released_at": local_info.get("released_at", ""),
        "local_changelog": local_info.get("changelog", []),
        "remote_version": local_ver,
        "remote_released_at": "",
        "remote_changelog": [],
        "download_url": "",
        "source_url": source_url,
        "message": f"Bạn đang sử dụng phiên bản {local_ver}.",
    }

    if not source_url:
        result["ok"] = False
        result["message"] = (
            "Chưa cấu hình Link nguồn cập nhật (GitHub Repo hoặc Server URL). "
            "Vui lòng nhập Link nguồn cập nhật hoặc liên hệ Admin!"
        )
        return result

    remote_data = None
    last_err = ""
    used_zip_url = ""

    # Thử cả 2 nhánh phổ biến trên GitHub (master và main)
    for br in ("master", "main"):
        manifest_url, fallback_zip_url = resolve_manifest_and_zip_urls(source_url, branch=br)
        if not manifest_url:
            continue
        try:
            remote_data = _http_get_json(manifest_url)
            used_zip_url = str(remote_data.get("download_zip_url") or "").strip() or fallback_zip_url
            break
        except Exception as exc:
            last_err = str(exc)

    if not remote_data or not isinstance(remote_data, dict):
        result["ok"] = False
        result["message"] = f"Không thể kết nối tới máy chủ cập nhật: {last_err}"
        return result

    remote_ver = str(remote_data.get("version") or local_ver).strip()
    remote_rel = str(remote_data.get("released_at") or "").strip()
    remote_log = remote_data.get("changelog") or []

    # Nếu repo GitHub chưa có dist_update/muse_update.zip thì có thể tải trực tiếp archive ZIP của repo
    m_gh = re.match(
        r"^https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?$",
        source_url.strip().rstrip("/"),
        re.IGNORECASE,
    )
    if not used_zip_url and m_gh:
        owner, repo = m_gh.group(1), m_gh.group(2)
        used_zip_url = f"https://github.com/{owner}/{repo}/archive/refs/heads/master.zip"

    has_new = _parse_semver(remote_ver) > _parse_semver(local_ver)

    result.update(
        {
            "ok": True,
            "has_update": has_new,
            "remote_version": remote_ver,
            "remote_released_at": remote_rel,
            "remote_changelog": remote_log if isinstance(remote_log, list) else [str(remote_log)],
            "download_url": used_zip_url,
            "message": (
                f"🎉 Đã có bản cập nhật mới v{remote_ver} (Phát hành: {remote_rel})! Bấm 'Cập nhật ngay' để nâng cấp."
                if has_new
                else f"✅ Bạn đang ở phiên bản mới nhất (v{local_ver})."
            ),
        }
    )
    return result


def _is_safe_to_overwrite(rel_path_str: str) -> bool:
    """Đảm bảo không bao giờ ghi đè lên dữ liệu người dùng (.muse/, output/, .venv/) hoặc công cụ Admin."""
    norm = rel_path_str.replace("\\", "/").lstrip("/")
    if not norm:
        return False
    first_part = norm.split("/", 1)[0].lower()
    if first_part in PROTECTED_PREFIXES:
        return False
    fname = Path(norm).name.lower()
    if fname in ADMIN_ONLY_FILES:
        return False
    return True


def download_and_apply_update(custom_source_url: Optional[str] = None) -> Dict[str, Any]:
    """
    Tải gói cập nhật ZIP từ máy chủ/GitHub, giải nén an toàn đè lên code ứng dụng
    (bảo toàn 100% .muse/, output/, .venv/) và kích hoạt tự khởi động lại ứng dụng.
    """
    chk = check_for_updates(custom_source_url)
    if not chk.get("ok"):
        return chk

    download_url = chk.get("download_url") or ""
    if not download_url:
        return {
            "ok": False,
            "message": "Không tìm thấy đường dẫn tải gói cập nhật (download_zip_url).",
        }

    tmp_dir = Path(tempfile.mkdtemp(prefix="muse_ota_"))
    zip_path = tmp_dir / "update_pkg.zip"

    try:
        sep = "&" if "?" in download_url else "?"
        bust_dl_url = f"{download_url}{sep}_t={int(time.time())}"
        req = urllib.request.Request(
            bust_dl_url,
            headers={"User-Agent": "MuseStudio-Updater/1.2"},
        )
        with urllib.request.urlopen(req, timeout=30.0) as resp:
            zip_path.write_bytes(resp.read())

        extract_dir = tmp_dir / "extracted"
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)

        # Kiểm tra nếu file ZIP của GitHub có 1 thư mục gốc bọc ngoài (VD: muse-studio-master/)
        source_root = extract_dir
        children = [p for p in extract_dir.iterdir()]
        if len(children) == 1 and children[0].is_dir() and (children[0] / "app.py").exists():
            source_root = children[0]

        if not (source_root / "app.py").exists() and not (source_root / "frontend").exists():
            return {
                "ok": False,
                "message": "Gói cập nhật tải về không đúng cấu trúc của Muse Studio!",
            }

        updated_files_count = 0
        for src_file in source_root.rglob("*"):
            if not src_file.is_file():
                continue
            rel = src_file.relative_to(source_root).as_posix()
            if not _is_safe_to_overwrite(rel):
                continue
            dest_file = BASE_DIR / rel
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src_file), str(dest_file))
            updated_files_count += 1

        # Khôi phục lại update_manifest_url trong version.json nếu người dùng dùng link riêng
        if chk.get("source_url"):
            update_settings({"update_source_url": chk["source_url"]})

        return {
            "ok": True,
            "updated_files": updated_files_count,
            "new_version": chk.get("remote_version"),
            "message": f"Đã cập nhật thành công {updated_files_count} tệp lên phiên bản v{chk.get('remote_version')}! Ứng dụng sẽ tự khởi động lại sau 2 giây...",
        }
    except Exception as exc:
        return {
            "ok": False,
            "message": f"Lỗi khi tải và cài đặt bản cập nhật: {exc}",
        }
    finally:
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


def trigger_app_restart(delay_sec: float = 1.5) -> None:
    """
    Tự động đóng tiến trình hiện tại và khởi chạy lại Muse Studio sau delay_sec giây.
    """
    def _restart_worker():
        time.sleep(delay_sec)
        venv_py = BASE_DIR / ".venv" / "Scripts" / "python.exe"
        py_exe = str(venv_py) if venv_py.exists() else sys.executable
        app_script = str((BASE_DIR / "app.py").resolve())

        if sys.platform == "win32":
            # Khởi chạy tiến trình mới tách rời trước khi đóng tiến trình cũ
            cmd = f'cmd.exe /c timeout /t 2 /nobreak >nul & "{py_exe}" "{app_script}"'
            subprocess.Popen(
                cmd,
                cwd=str(BASE_DIR),
                creationflags=0x08000000 | 0x00000008,  # CREATE_NO_WINDOW | DETACHED_PROCESS
                close_fds=True,
            )
        else:
            subprocess.Popen([py_exe, app_script], cwd=str(BASE_DIR), close_fds=True)

        os._exit(0)

    threading.Thread(target=_restart_worker, daemon=True).start()


def build_customer_update_zip(output_zip_path: Path) -> Tuple[int, float]:
    """
    Đóng gói toàn bộ mã nguồn ứng dụng (app.py, backend/, frontend/, version.json...)
    thành gói cập nhật nhẹ muse_update.zip (~100KB) để phát hành cho khách hàng.
    Trả về (file_count, size_kb).
    """
    output_zip_path.parent.mkdir(parents=True, exist_ok=True)
    include_files = [
        "Muse Studio.exe",
        "muse_studio.ico",
        "app.py",
        "desktop_window.py",
        "requirements.txt",
        "run.bat",
        "version.json",
    ]
    include_dirs = ["backend", "frontend"]

    count = 0
    with zipfile.ZipFile(output_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname in include_files:
            fpath = BASE_DIR / fname
            if fpath.exists() and fpath.is_file():
                zf.write(fpath, arcname=fname)
                count += 1

        for dname in include_dirs:
            dpath = BASE_DIR / dname
            if not dpath.exists():
                continue
            for sub in dpath.rglob("*"):
                if not sub.is_file():
                    continue
                if "__pycache__" in sub.parts or sub.suffix.lower() in (".pyc", ".pyo"):
                    continue
                rel = sub.relative_to(BASE_DIR).as_posix()
                if not _is_safe_to_overwrite(rel):
                    continue
                zf.write(sub, arcname=rel)
                count += 1

    size_kb = round(output_zip_path.stat().st_size / 1024.0, 1)
    return count, size_kb
