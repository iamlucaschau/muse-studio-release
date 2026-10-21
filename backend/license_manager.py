import base64
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from backend.database import BASE_DIR, DATA_DIR

# Khóa bí mật chữ ký số HMAC-SHA256 dành riêng cho Muse Studio
_MUSE_MASTER_SECRET = b"MuseStudio_Pro_2026_MasterSigningKey_#98A7F6E5D4C3B2A1_LuisEdition"
LICENSE_FILE_PATH = DATA_DIR / "license.key"
CLOCK_STATE_PATH = DATA_DIR / "clock_guard.dat"

VN_TZ = timezone(timedelta(hours=7))

# Bộ nhớ đệm cho Mã máy (HWID) và Giờ chuẩn Quốc tế
_CACHED_HWID: Optional[str] = None
_CACHED_NET_TIME: Optional[Tuple[float, float]] = None  # (net_epoch, local_monotonic)


def _normalize_hwid_Input(raw_hwid: str) -> str:
    """Chuẩn hóa chuỗi HWID (bỏ khoảng trắng dư, viết hoa)."""
    clean = re.sub(r"[^A-Z0-9]", "", (raw_hwid or "").upper())
    if clean.startswith("MUSE"):
        clean = clean[4:]
    if len(clean) >= 12:
        clean = clean[:12]
        return f"MUSE-{clean[0:4]}-{clean[4:8]}-{clean[8:12]}"
    return (raw_hwid or "").strip().upper()


def get_machine_hwid() -> str:
    """
    Lấy Mã phần cứng cố định của máy tính Windows (HWID).
    Kết hợp MachineGuid trong Registry + UUID phần cứng + Tên CPU, băm SHA-256 thành mã MUSE-XXXX-XXXX-XXXX.
    """
    global _CACHED_HWID
    if _CACHED_HWID:
        return _CACHED_HWID

    parts = []

    # 1. Đọc MachineGuid từ Windows Registry (nhanh, ổn định 100% trên mọi bản Windows)
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
                0,
                winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
            ) as key:
                val, _ = winreg.QueryValueEx(key, "MachineGuid")
                if val:
                    parts.append(str(val).strip())
        except Exception:
            pass

    # 2. Kết hợp MAC node / hardware node và thông tin CPU
    try:
        parts.append(str(uuid.getnode()))
    except Exception:
        pass

    parts.append(os.environ.get("PROCESSOR_IDENTIFIER", ""))
    parts.append(os.environ.get("COMPUTERNAME", ""))

    raw_fingerprint = "|".join(p for p in parts if p)
    digest = hashlib.sha256(
        (raw_fingerprint + "|MuseStudioHWID_v1").encode("utf-8")
    ).hexdigest().upper()

    code12 = digest[:12]
    _CACHED_HWID = f"MUSE-{code12[0:4]}-{code12[4:8]}-{code12[8:12]}"
    return _CACHED_HWID


def _fetch_network_epoch() -> Optional[float]:
    """Lấy thời gian thực tế từ HTTP Date header của Google / Cloudflare để chống chỉnh lùi giờ máy."""
    global _CACHED_NET_TIME
    now_mono = time.monotonic()
    if _CACHED_NET_TIME is not None:
        cached_epoch, cached_mono = _CACHED_NET_TIME
        if (now_mono - cached_mono) < 600:  # Cache trong 10 phút
            return cached_epoch + (now_mono - cached_mono)

    urls = (
        "https://www.google.com/generate_204",
        "https://1.1.1.1/cdn-cgi/trace",
        "https://www.microsoft.com",
    )
    for url in urls:
        try:
            req = urllib.request.Request(url, method="HEAD")
            req.add_header("User-Agent", "Mozilla/5.0")
            with urllib.request.urlopen(req, timeout=2.5) as resp:
                date_str = resp.headers.get("Date")
                if date_str:
                    dt = parsedate_to_datetime(date_str)
                    epoch = dt.timestamp()
                    _CACHED_NET_TIME = (epoch, now_mono)
                    return epoch
        except Exception:
            continue
    return None


def _load_max_seen_epoch() -> float:
    try:
        if CLOCK_STATE_PATH.exists():
            raw = CLOCK_STATE_PATH.read_text(encoding="utf-8").strip()
            data = json.loads(base64.b64decode(raw.encode("ascii")).decode("utf-8"))
            ts = float(data.get("ts", 0))
            sig = data.get("sig", "")
            expected_sig = hmac.new(
                _MUSE_MASTER_SECRET, f"clock:{ts:.0f}".encode("utf-8"), hashlib.sha256
            ).hexdigest()[:16]
            if hmac.compare_digest(sig, expected_sig):
                return ts
    except Exception:
        pass
    return 0.0


def _save_max_seen_epoch(ts: float) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        sig = hmac.new(
            _MUSE_MASTER_SECRET, f"clock:{ts:.0f}".encode("utf-8"), hashlib.sha256
        ).hexdigest()[:16]
        payload = json.dumps({"ts": round(ts), "sig": sig})
        encoded = base64.b64encode(payload.encode("utf-8")).decode("ascii")
        CLOCK_STATE_PATH.write_text(encoded, encoding="utf-8")
    except Exception:
        pass


def get_trusted_now() -> Tuple[datetime, bool, str]:
    """
    Trả về (current_datetime_vn, is_clock_ok, error_msg).
    Kết hợp Giờ chuẩn Quốc tế (nếu có mạng) và cơ chế Anti-Clock-Rollback.
    """
    sys_epoch = time.time()
    net_epoch = _fetch_network_epoch()
    max_seen = _load_max_seen_epoch()

    effective_epoch = net_epoch if net_epoch is not None else sys_epoch

    # Nếu không lấy được giờ mạng mà giờ hệ thống bị chỉnh lùi hơn 2 tiếng so với lần chạy trước
    if net_epoch is None and max_seen > 0 and (sys_epoch + 7200) < max_seen:
        last_dt = datetime.fromtimestamp(max_seen, tz=VN_TZ).strftime("%d/%m/%Y %H:%M")
        return (
            datetime.fromtimestamp(max_seen, tz=VN_TZ),
            False,
            f"Phát hiện đồng hồ máy tính bị chỉnh lùi về trước mốc {last_dt}! Vui lòng chỉnh lại đúng ngày giờ thực tế hoặc kết nối Internet.",
        )

    if effective_epoch > max_seen:
        _save_max_seen_epoch(effective_epoch)

    return datetime.fromtimestamp(effective_epoch, tz=VN_TZ), True, ""


def _sign_payload_bytes(payload_b64: str) -> str:
    sig = hmac.new(
        _MUSE_MASTER_SECRET, payload_b64.encode("ascii"), hashlib.sha256
    ).hexdigest().upper()
    return sig[:20]


def generate_license_key(
    hwid: str,
    expires_date_str: str,
    customer_name: str = "Khách hàng",
    days_granted: int = 30,
) -> str:
    """
    Tạo chuỗi License Key đã ký số HMAC-SHA256 khóa theo đúng Mã máy (HWID) và Ngày hết hạn (YYYY-MM-DD).
    Định dạng Key: MUSEKEY-<payload_base64url>.<signature_20hex>
    """
    norm_hwid = _normalize_hwid_Input(hwid)
    if not norm_hwid or len(norm_hwid) < 8:
        raise ValueError("Mã máy (HWID) không hợp lệ")

    # Kiểm tra định dạng ngày hết hạn YYYY-MM-DD
    datetime.strptime(expires_date_str.strip(), "%Y-%m-%d")

    payload = {
        "h": norm_hwid,
        "e": expires_date_str.strip(),
        "c": (customer_name or "Khách hàng").strip()[:60],
        "d": int(days_granted),
        "i": int(time.time()),
    }
    raw_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(raw_json).decode("ascii").rstrip("=")
    sig = _sign_payload_bytes(payload_b64)
    return f"MUSEKEY-{payload_b64}.{sig}"


def verify_license_key(key_str: str, current_hwid: Optional[str] = None) -> Dict[str, Any]:
    """
    Kiểm tra tính hợp lệ của License Key:
    1. Chữ ký số HMAC-SHA256 (chống sửa đổi nội dung Key)
    2. Khớp đúng Mã máy (HWID) hiện tại
    3. Kiểm tra Ngày hết hạn so với Giờ chuẩn Quốc tế & chống quay lùi đồng hồ
    """
    machine_hwid = _normalize_hwid_Input(current_hwid or get_machine_hwid())
    clean_key = (key_str or "").strip()

    base_res = {
        "is_valid": False,
        "status_code": "missing",
        "message": "Ứng dụng chưa được kích hoạt License Key. Vui lòng gửi Mã máy (HWID) cho Admin để nhận Key!",
        "hwid": machine_hwid,
        "customer": "",
        "expires_at": "",
        "expires_iso": "",
        "days_remaining": 0,
        "days_granted": 0,
        "issued_at": "",
        "masked_key": "",
    }

    if not clean_key:
        return base_res

    if not clean_key.startswith("MUSEKEY-") or "." not in clean_key:
        base_res["status_code"] = "invalid_key"
        base_res["message"] = "Định dạng License Key không hợp lệ (Key chuẩn bắt đầu bằng MUSEKEY-...)"
        return base_res

    try:
        body = clean_key[len("MUSEKEY-") :]
        payload_b64, provided_sig = body.rsplit(".", 1)
        expected_sig = _sign_payload_bytes(payload_b64)
        if not hmac.compare_digest(provided_sig.upper(), expected_sig):
            base_res["status_code"] = "invalid_key"
            base_res["message"] = "Chữ ký số License Key không hợp lệ hoặc Key đã bị chỉnh sửa!"
            return base_res

        pad = "=" * ((4 - len(payload_b64) % 4) % 4)
        raw_json = base64.urlsafe_b64decode((payload_b64 + pad).encode("ascii")).decode("utf-8")
        data = json.loads(raw_json)
    except Exception:
        base_res["status_code"] = "invalid_key"
        base_res["message"] = "Không thể giải mã License Key. Vui lòng kiểm tra lại chuỗi Key đã dán!"
        return base_res

    key_hwid = _normalize_hwid_Input(str(data.get("h", "")))
    exp_iso = str(data.get("e", "")).strip()
    customer = str(data.get("c", "Khách hàng")).strip()
    days_granted = int(data.get("d", 0) or 0)
    issued_ts = int(data.get("i", 0) or 0)

    # 1. Kiểm tra khóa cứng theo Mã máy (HWID)
    if key_hwid != machine_hwid:
        base_res["status_code"] = "hwid_mismatch"
        base_res["message"] = (
            f"License Key này được cấp riêng cho thiết bị [{key_hwid}], "
            f"không thể sử dụng trên máy hiện tại [{machine_hwid}]!"
        )
        return base_res

    # 2. Kiểm tra thời gian thực tế & chống chỉnh lùi giờ
    now_dt, clock_ok, clock_err = get_trusted_now()
    if not clock_ok:
        base_res["status_code"] = "clock_rollback"
        base_res["message"] = clock_err
        return base_res

    if issued_ts > 0 and (now_dt.timestamp() + 86400) < issued_ts:
        base_res["status_code"] = "clock_rollback"
        base_res["message"] = "Đồng hồ máy tính đang bị đặt lùi về trước ngày phát hành Key! Vui lòng cập nhật lại giờ chuẩn."
        return base_res

    # 3. Kiểm tra ngày hết hạn (Hết hạn vào 23:59:59 của ngày expires_at theo giờ Việt Nam)
    try:
        exp_dt_end = datetime.strptime(exp_iso, "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, tzinfo=VN_TZ
        )
    except Exception:
        base_res["status_code"] = "invalid_key"
        base_res["message"] = "Ngày hết hạn trong Key không hợp lệ!"
        return base_res

    exp_display = exp_dt_end.strftime("%d/%m/%Y")
    issued_display = (
        datetime.fromtimestamp(issued_ts, tz=VN_TZ).strftime("%d/%m/%Y")
        if issued_ts > 0
        else "-"
    )

    masked = (
        f"{clean_key[:16]}...{clean_key[-8:]}"
        if len(clean_key) > 28
        else clean_key
    )

    base_res.update(
        {
            "customer": customer,
            "expires_at": exp_display,
            "expires_iso": exp_iso,
            "days_granted": days_granted,
            "issued_at": issued_display,
            "masked_key": masked,
        }
    )

    if now_dt > exp_dt_end:
        base_res["is_valid"] = False
        base_res["status_code"] = "expired"
        base_res["days_remaining"] = 0
        base_res["message"] = (
            f"License Key của [{customer}] đã hết hạn vào ngày {exp_display}. "
            f"Vui lòng liên hệ Admin để cấp Key gia hạn mới!"
        )
        return base_res

    # Tính số ngày còn lại
    delta_days = (exp_dt_end.date() - now_dt.date()).days + 1
    base_res["is_valid"] = True
    base_res["status_code"] = "valid"
    base_res["days_remaining"] = max(1, delta_days)
    base_res["message"] = (
        f"Bản quyền hợp lệ ({customer}) — Còn {base_res['days_remaining']} ngày (Hết hạn: {exp_display})"
    )
    return base_res


def load_saved_license_key() -> str:
    try:
        if LICENSE_FILE_PATH.exists():
            return LICENSE_FILE_PATH.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return ""


def save_license_key(key_str: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LICENSE_FILE_PATH.write_text((key_str or "").strip(), encoding="utf-8")


def clear_saved_license_key() -> None:
    try:
        if LICENSE_FILE_PATH.exists():
            LICENSE_FILE_PATH.unlink()
    except Exception:
        pass


def get_current_license_status() -> Dict[str, Any]:
    saved_key = load_saved_license_key()
    return verify_license_key(saved_key)


def activate_license_key(key_str: str) -> Dict[str, Any]:
    res = verify_license_key(key_str)
    if res["is_valid"]:
        save_license_key(key_str.strip())
    return res
