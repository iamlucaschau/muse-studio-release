import json
import re
import shutil
import subprocess
import sys
import tkinter as tk
import zipfile
from datetime import datetime
from pathlib import Path
from tkinter import messagebox

from backend.updater import (
    VERSION_FILE,
    _is_safe_to_overwrite,
    build_customer_update_zip,
    get_local_version_info,
    resolve_manifest_and_zip_urls,
)

BASE_DIR = Path(__file__).resolve().parent


def suggest_next_version(cur_ver: str) -> str:
    parts = [int(x) for x in re.findall(r"\d+", cur_ver or "1.2.0")]
    while len(parts) < 3:
        parts.append(0)
    parts[2] += 1
    return f"{parts[0]}.{parts[1]}.{parts[2]}"


def create_clean_customer_full_package(version_str: str) -> Path:
    """
    Tạo gói phần mềm hoàn chỉnh sạch 100% để gửi cho khách hàng mới:
    - Loại bỏ hoàn toàn công cụ tạo Key của Admin (Muse_KeyGen_Admin.py, Publish_Update_Admin.py)
    - Loại bỏ Cookie/Profile cá nhân của Admin (.muse/profiles, .muse/license.key, .muse/muse_studio.db)
    - Loại bỏ video/ảnh cá nhân trong output/
    Khi khách tải về và mở run.bat, ứng dụng sẽ ở trạng thái sạch và yêu cầu nhập License Key.
    """
    dist_dir = BASE_DIR / "dist_package"
    dist_dir.mkdir(parents=True, exist_ok=True)
    zip_out = dist_dir / f"Muse_Studio_v{version_str}_Customer_Release.zip"

    include_root_files = [
        "app.py",
        "desktop_window.py",
        "requirements.txt",
        "run.bat",
        "version.json",
    ]
    include_dirs = ["backend", "frontend"]

    with zipfile.ZipFile(zip_out, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname in include_root_files:
            fpath = BASE_DIR / fname
            if fpath.exists() and fpath.is_file():
                zf.write(fpath, arcname=f"Muse Studio/{fname}")

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
                zf.write(sub, arcname=f"Muse Studio/{rel}")

    return zip_out


def run_gui():
    info = get_local_version_info()
    cur_ver = str(info.get("version") or "1.2.0")
    next_ver = suggest_next_version(cur_ver)

    root = tk.Tk()
    root.title("Muse Studio — Công Cụ Phát Hành Bản Cập Nhật OTA & Đóng Gói Gửi Khách (Admin)")
    root.geometry("800x620")
    root.configure(bg="#0b0f19")

    var_version = tk.StringVar(value=next_ver)
    var_repo_url = tk.StringVar(value=str(info.get("update_manifest_url") or ""))
    var_status = tk.StringVar(
        value=f"Phiên bản hiện tại: v{cur_ver} · Sẵn sàng phát hành bản mới v{next_ver}"
    )

    hdr = tk.Frame(root, bg="#111827", pady=12, padx=18)
    hdr.pack(fill="x")
    tk.Label(
        hdr,
        text="🚀 MUSE STUDIO — QUẢN LÝ CẬP NHẬT TỰ ĐỘNG (OTA) & ĐÓNG GÓI PHẦN MỀM",
        bg="#111827",
        fg="#38bdf8",
        font=("Segoe UI", 12, "bold"),
    ).pack(anchor="w")
    tk.Label(
        hdr,
        text="Giúp người dùng chỉ cần bấm 'Kiểm tra cập nhật' là tự tải bản mới về mà không cần cài lại",
        bg="#111827",
        fg="#9ca3af",
        font=("Segoe UI", 9),
    ).pack(anchor="w", pady=(2, 0))

    body = tk.Frame(root, bg="#0b0f19", padx=18, pady=12)
    body.pack(fill="both", expand=True)

    # Dòng 1: Phiên bản mới + Link GitHub Repo / Server
    row1 = tk.Frame(body, bg="#0b0f19")
    row1.pack(fill="x", pady=(0, 10))
    row1.columnconfigure(0, weight=1)
    row1.columnconfigure(1, weight=3)

    tk.Label(
        row1,
        text="1. Số phiên bản mới (VD: 1.3.0):",
        bg="#0b0f19",
        fg="#e5e7eb",
        font=("Segoe UI", 10, "bold"),
    ).grid(row=0, column=0, sticky="w", padx=(0, 10))

    tk.Label(
        row1,
        text="2. Link GitHub Repo hoặc URL chứa version.json (Để máy khách tự kiểm tra):",
        bg="#0b0f19",
        fg="#e5e7eb",
        font=("Segoe UI", 10, "bold"),
    ).grid(row=0, column=1, sticky="w")

    tk.Entry(
        row1,
        textvariable=var_version,
        bg="#161f33",
        fg="#34d399",
        insertbackground="white",
        font=("Consolas", 12, "bold"),
        relief="flat",
        bd=6,
    ).grid(row=1, column=0, sticky="ew", padx=(0, 10), pady=4)

    tk.Entry(
        row1,
        textvariable=var_repo_url,
        bg="#161f33",
        fg="#fbbf24",
        insertbackground="white",
        font=("Consolas", 10),
        relief="flat",
        bd=6,
    ).grid(row=1, column=1, sticky="ew", pady=4)

    # Dòng 2: Nội dung cập nhật (Changelog)
    tk.Label(
        body,
        text="3. Nội dung tính năng mới trong bản cập nhật này (Mỗi dòng 1 ý — Khách hàng sẽ nhìn thấy khi bấm Kiểm tra cập nhật):",
        bg="#0b0f19",
        fg="#e5e7eb",
        font=("Segoe UI", 10, "bold"),
    ).pack(anchor="w", pady=(4, 4))

    txt_changelog = tk.Text(
        body,
        height=7,
        bg="#161f33",
        fg="white",
        insertbackground="white",
        font=("Segoe UI", 10),
        relief="flat",
        bd=8,
    )
    txt_changelog.pack(fill="x", pady=(0, 12))
    existing_logs = info.get("changelog") or []
    txt_changelog.insert("1.0", "\n".join(existing_logs))

    def save_manifest_and_build_ota(push_git: bool = False):
        ver = var_version.get().strip()
        repo_url = var_repo_url.get().strip()
        lines = [
            ln.strip()
            for ln in txt_changelog.get("1.0", "end").splitlines()
            if ln.strip()
        ]
        if not ver:
            messagebox.showwarning("Thiếu phiên bản", "Vui lòng nhập số phiên bản mới!")
            return

        manifest_url, zip_url = resolve_manifest_and_zip_urls(repo_url)
        new_manifest = {
            "version": ver,
            "released_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "update_manifest_url": repo_url,
            "download_zip_url": zip_url,
            "changelog": lines,
        }
        VERSION_FILE.write_text(
            json.dumps(new_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        ota_zip_path = BASE_DIR / "dist_update" / "muse_update.zip"
        f_count, size_kb = build_customer_update_zip(ota_zip_path)

        msg = (
            f"✅ Đã cập nhật version.json (v{ver})\n"
            f"✅ Đã đóng gói bản cập nhật OTA: dist_update/muse_update.zip ({f_count} file — {size_kb} KB)"
        )

        if push_git:
            try:
                subprocess.run(["git", "add", "version.json", "dist_update/muse_update.zip"], cwd=str(BASE_DIR), check=False)
                subprocess.run(
                    ["git", "commit", "-m", f"release: Publish OTA update v{ver}"],
                    cwd=str(BASE_DIR),
                    check=False,
                )
                push_res = subprocess.run(
                    ["git", "push"],
                    cwd=str(BASE_DIR),
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if push_res.returncode == 0:
                    msg += "\n✅ Đã đẩy (git push) lên GitHub thành công! Tất cả máy khách hàng đã có thể bấm 'Cập nhật ngay'."
                else:
                    msg += f"\n⚠️ Đã lưu tại máy (Chưa git push được vì chưa gắn remote GitHub: {push_res.stderr.strip()[:120]})"
            except Exception as exc:
                msg += f"\n⚠️ Lỗi khi chạy git push: {exc}"

        var_status.set(f"Đã đóng gói v{ver} ({size_kb} KB) lúc {datetime.now().strftime('%H:%M:%S')}")
        messagebox.showinfo("Hoàn tất đóng gói bản cập nhật", msg)

    def do_export_clean_customer_zip():
        ver = var_version.get().strip() or cur_ver
        save_manifest_and_build_ota(push_git=False)
        out_zip = create_clean_customer_full_package(ver)
        size_kb = round(out_zip.stat().st_size / 1024.0, 1)
        subprocess.Popen(f'explorer.exe /select,"{out_zip}"', shell=True)
        messagebox.showinfo(
            "Đã xuất bộ cài sạch gửi Khách Hàng",
            f"Đã tạo gói phần mềm sạch dành cho Khách Hàng tại:\n{out_zip}\n(Dung lượng: {size_kb} KB)\n\n"
            f"🔒 Đã tự động loại bỏ Tool Admin KeyGen, Cookie cá nhân và Key của bạn.\n"
            f"Khi khách giải nén và chạy run.bat, ứng dụng sẽ yêu cầu nhập License Key!",
        )

    btn_frame = tk.Frame(body, bg="#0b0f19")
    btn_frame.pack(fill="x", pady=(4, 12))

    tk.Button(
        btn_frame,
        text="⚡ 1. Tạo Gói Cập Nhật Nhanh (muse_update.zip)",
        command=lambda: save_manifest_and_build_ota(push_git=False),
        bg="#10b981",
        fg="#052e16",
        font=("Segoe UI", 10, "bold"),
        relief="flat",
        padx=14,
        pady=8,
        cursor="hand2",
    ).pack(side="left", padx=(0, 8))

    tk.Button(
        btn_frame,
        text="☁️ 2. Tạo Gói & Tự Động Đẩy Lên GitHub (git push)",
        command=lambda: save_manifest_and_build_ota(push_git=True),
        bg="#4f46e5",
        fg="white",
        font=("Segoe UI", 10, "bold"),
        relief="flat",
        padx=14,
        pady=8,
        cursor="hand2",
    ).pack(side="left", padx=(0, 8))

    tk.Button(
        btn_frame,
        text="🎁 3. Xuất File ZIP Sạch Gửi Khách Hàng Mới",
        command=do_export_clean_customer_zip,
        bg="#f59e0b",
        fg="#0b0f19",
        font=("Segoe UI", 10, "bold"),
        relief="flat",
        padx=14,
        pady=8,
        cursor="hand2",
    ).pack(side="left")

    # Hướng dẫn ngắn gọn cho Admin
    guide = tk.Frame(body, bg="#111827", padx=14, pady=12)
    guide.pack(fill="both", expand=True)
    tk.Label(
        guide,
        text="💡 HƯỚNG DẪN CÁCH HOẠT ĐỘNG CỦA HỆ THỐNG CẬP NHẬT TỰ ĐỘNG 1 CHẠM:",
        bg="#111827",
        fg="#fde047",
        font=("Segoe UI", 9, "bold"),
    ).pack(anchor="w")
    tk.Label(
        guide,
        text=(
            "• Bước 1 (Chỉ làm 1 lần): Tạo 1 kho GitHub (Repository) của bạn và điền link (VD: https://github.com/ten-ban/muse-studio) vào ô số 2.\n"
            "• Bước 2 (Gửi phần mềm cho khách lần đầu): Bấm nút [🎁 3. Xuất File ZIP Sạch Gửi Khách Hàng Mới] -> Gửi file ZIP đó cho khách.\n"
            "• Bước 3 (Mỗi khi bạn và Luis nâng cấp tính năng mới): Bạn chỉ cần mở bảng này, tăng số phiên bản (VD: 1.3.0) rồi bấm nút [☁️ 2].\n"
            "• Phía người dùng: Họ chỉ cần bấm nút [🔄 Kiểm tra cập nhật] trên góc phải Muse Studio -> Bấm [Cập nhật ngay] là ứng dụng tự tải bản mới về và tự khởi động lại trong 3 giây (Giữ nguyên 100% License Key, Tài khoản, Cookie và Video của họ)!"
        ),
        bg="#111827",
        fg="#d1d5db",
        justify="left",
        font=("Segoe UI", 9),
    ).pack(anchor="w", pady=(4, 0))

    tk.Label(
        body,
        textvariable=var_status,
        bg="#0b0f19",
        fg="#34d399",
        font=("Segoe UI", 9, "bold"),
    ).pack(anchor="w", pady=(8, 0))

    root.mainloop()


if __name__ == "__main__":
    run_gui()
