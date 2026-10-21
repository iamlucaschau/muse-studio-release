import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple


def get_ffmpeg_Path() -> str:
    """Tìm đường dẫn thực thi của FFmpeg trên hệ thống Windows."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    for candidate in (
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\ffmpeg\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    ):
        if Path(candidate).exists():
            return candidate
    return "ffmpeg"


def extract_last_frame(video_path: str, output_image_path: str) -> Tuple[bool, str]:
    """
    Trích xuất khung hình cuối cùng sắc nét của clip video 10s trước đó
    để làm khung hình bắt đầu (Starting Frame) cho clip 10s kế tiếp.
    """
    v_path = Path(video_path)
    out_path = Path(output_image_path)
    if not v_path.exists():
        return False, f"Không tìm thấy video nguồn: {v_path}"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg_bin = get_ffmpeg_Path()

    try:
        # Lấy frame cách điểm cuối 0.12 giây để tránh frame đen cuối clip
        cmd = [
            ffmpeg_bin,
            "-y",
            "-sseof",
            "-0.12",
            "-i",
            str(v_path),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(out_path),
        ]
        subprocess.run(cmd, capture_output=True, timeout=20, check=False)
        if out_path.exists() and out_path.stat().st_size > 1000:
            return True, str(out_path.resolve())

        # Fallback: lấy frame đầu nếu clip quá ngắn
        cmd_fallback = [
            ffmpeg_bin,
            "-y",
            "-i",
            str(v_path),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(out_path),
        ]
        subprocess.run(cmd_fallback, capture_output=True, timeout=20, check=False)
        if out_path.exists() and out_path.stat().st_size > 1000:
            return True, str(out_path.resolve())
        return False, "Không thể trích xuất khung hình cuối từ video"
    except Exception as exc:
        return False, f"Lỗi FFmpeg khi trích xuất frame: {exc}"


def stitch_video_clips(
    video_paths: List[str], output_video_path: str
) -> Tuple[bool, str, float]:
    """
    Ghép nối mượt mà nhiều clip 10s thành 1 Video dài hoàn chỉnh (.mp4) bằng FFmpeg.
    Trả về: (ok, message_or_path, file_size_mb)
    """
    valid_paths: List[Path] = []
    for p in video_paths:
        if p and Path(p).exists() and Path(p).is_file():
            valid_paths.append(Path(p).resolve())

    if len(valid_paths) < 2:
        return False, "Cần ít nhất 2 video hợp lệ để ghép nối", 0.0

    out_path = Path(output_video_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg_bin = get_ffmpeg_Path()

    list_file = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as tf:
            list_file = Path(tf.name)
            for vp in valid_paths:
                escaped = str(vp).replace("'", "'\\''")
                tf.write(f"file '{escaped}'\n")

        # Cách 1: Stream copy siêu tốc (giữ nguyên 100% chất lượng gốc khi cùng chuẩn Muse.ai)
        cmd_copy = [
            ffmpeg_bin,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(out_path),
        ]
        subprocess.run(cmd_copy, capture_output=True, timeout=120, check=False)
        if out_path.exists() and out_path.stat().st_size > 20_000:
            size_mb = round(out_path.stat().st_size / (1024 * 1024), 2)
            return True, str(out_path), size_mb

        # Cách 2: Fallback re-encode đồng bộ H.264 + AAC nếu các clip khác độ phân giải/FPS
        cmd_encode = [
            ffmpeg_bin,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(out_path),
        ]
        subprocess.run(cmd_encode, capture_output=True, timeout=300, check=False)
        if out_path.exists() and out_path.stat().st_size > 20_000:
            size_mb = round(out_path.stat().st_size / (1024 * 1024), 2)
            return True, str(out_path), size_mb

        return False, "FFmpeg không thể ghép nối các video này", 0.0
    except Exception as exc:
        return False, f"Lỗi khi ghép video bằng FFmpeg: {exc}", 0.0
    finally:
        if list_file and list_file.exists():
            try:
                list_file.unlink()
            except Exception:
                pass
