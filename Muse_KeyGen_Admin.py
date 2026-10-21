import argparse
import json
import sys
import tkinter as tk
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import messagebox, ttk

from backend.license_manager import (
    activate_license_key,
    generate_license_key,
    get_machine_hwid,
    verify_license_key,
)

BASE_DIR = Path(__file__).resolve().parent
HISTORY_FILE = BASE_DIR / ".muse" / "admin_issued_keys.json"


def load_key_history():
    try:
        if HISTORY_FILE.exists():
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def save_key_history(item):
    history = load_key_history()
    history.insert(0, item)
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(
        json.dumps(history[:200], ensure_ascii=False, indent=2), encoding="utf-8"
    )


def run_gui():
    root = tk.Tk()
    root.title("Muse Studio — Admin License Key Generator (Công cụ Cấp Key Bản Quyền)")
    root.geometry("820x650")
    root.configure(bg="#0b0f19")
    root.minsize(760, 600)

    # Biến trạng thái
    var_hwid = tk.StringVar(value=get_machine_hwid())
    var_customer = tk.StringVar(value="Khách hàng VIP")
    var_days = tk.StringVar(value="30")
    var_exp_date = tk.StringVar(
        value=(datetime.now() + timedelta(days=29)).strftime("%Y-%m-%d")
    )
    var_generated_key = tk.StringVar(value="")

    def on_days_change(*_):
        try:
            d = int(var_days.get().strip() or "0")
            if d > 0:
                target_dt = datetime.now() + timedelta(days=max(0, d - 1))
                var_exp_date.set(target_dt.strftime("%Y-%m-%d"))
        except Exception:
            pass

    def set_preset_days(days_val: int):
        var_days.set(str(days_val))
        on_days_change()

    # Header
    hdr = tk.Frame(root, bg="#111827", pady=12, padx=18)
    hdr.pack(fill="x")
    tk.Label(
        hdr,
        text="🔑 MUSE STUDIO — CÔNG CỤ TẠO LICENSE KEY (DÀNH RIÊNG CHO ADMIN)",
        bg="#111827",
        fg="#34d399",
        font=("Segoe UI", 12, "bold"),
    ).pack(anchor="w")
    tk.Label(
        hdr,
        text="Khóa cứng theo Mã máy (HWID) + Kiểm soát Ngày hết hạn (Chữ ký số HMAC-SHA256 chống giả mạo)",
        bg="#111827",
        fg="#9ca3af",
        font=("Segoe UI", 9),
    ).pack(anchor="w", pady=(2, 0))

    # Form chính
    body = tk.Frame(root, bg="#0b0f19", padx=18, pady=12)
    body.pack(fill="both", expand=True)

    # Dòng 1: Mã máy HWID
    tk.Label(
        body,
        text="1. Mã thiết bị của khách hàng (HWID - Bắt buộc):",
        bg="#0b0f19",
        fg="#e5e7eb",
        font=("Segoe UI", 10, "bold"),
    ).pack(anchor="w")

    row_hwid = tk.Frame(body, bg="#0b0f19")
    row_hwid.pack(fill="x", pady=(4, 10))
    entry_hwid = tk.Entry(
        row_hwid,
        textvariable=var_hwid,
        bg="#161f33",
        fg="#fbbf24",
        insertbackground="white",
        font=("Consolas", 12, "bold"),
        relief="flat",
        bd=6,
    )
    entry_hwid.pack(side="left", fill="x", expand=True, padx=(0, 8))

    def fill_my_hwid():
        var_hwid.set(get_machine_hwid())

    tk.Button(
        row_hwid,
        text="🖥 Lấy Mã Máy Hiện Tại (Máy Admin)",
        command=fill_my_hwid,
        bg="#1e293b",
        fg="#93c5fd",
        activebackground="#334155",
        activeforeground="white",
        font=("Segoe UI", 9, "bold"),
        relief="flat",
        padx=10,
        pady=5,
        cursor="hand2",
    ).pack(side="right")

    # Dòng 2: Tên khách hàng + Số ngày + Ngày hết hạn
    grid_info = tk.Frame(body, bg="#0b0f19")
    grid_info.pack(fill="x", pady=(0, 8))
    grid_info.columnconfigure(0, weight=2)
    grid_info.columnconfigure(1, weight=1)
    grid_info.columnconfigure(2, weight=1)

    tk.Label(
        grid_info,
        text="2. Tên khách hàng / Ghi chú:",
        bg="#0b0f19",
        fg="#e5e7eb",
        font=("Segoe UI", 10, "bold"),
    ).grid(row=0, column=0, sticky="w", padx=(0, 8))
    tk.Label(
        grid_info,
        text="3. Số ngày cấp:",
        bg="#0b0f19",
        fg="#e5e7eb",
        font=("Segoe UI", 10, "bold"),
    ).grid(row=0, column=1, sticky="w", padx=(0, 8))
    tk.Label(
        grid_info,
        text="4. Ngày hết hạn (YYYY-MM-DD):",
        bg="#0b0f19",
        fg="#e5e7eb",
        font=("Segoe UI", 10, "bold"),
    ).grid(row=0, column=2, sticky="w")

    tk.Entry(
        grid_info,
        textvariable=var_customer,
        bg="#161f33",
        fg="white",
        insertbackground="white",
        font=("Segoe UI", 10),
        relief="flat",
        bd=6,
    ).grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=4)

    entry_days = tk.Entry(
        grid_info,
        textvariable=var_days,
        bg="#161f33",
        fg="#34d399",
        insertbackground="white",
        font=("Consolas", 11, "bold"),
        relief="flat",
        bd=6,
    )
    entry_days.grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=4)
    entry_days.bind("<KeyRelease>", on_days_change)

    tk.Entry(
        grid_info,
        textvariable=var_exp_date,
        bg="#161f33",
        fg="#38bdf8",
        insertbackground="white",
        font=("Consolas", 11, "bold"),
        relief="flat",
        bd=6,
    ).grid(row=1, column=2, sticky="ew", pady=4)

    # Các nút chọn nhanh thời hạn
    row_presets = tk.Frame(body, bg="#0b0f19")
    row_presets.pack(fill="x", pady=(2, 12))
    tk.Label(
        row_presets,
        text="Chọn nhanh thời hạn:",
        bg="#0b0f19",
        fg="#9ca3af",
        font=("Segoe UI", 9),
    ).pack(side="left", padx=(0, 8))

    for label, d_val in [
        ("1 Ngày (Test)", 1),
        ("3 Ngày", 3),
        ("7 Ngày (1 Tuần)", 7),
        ("30 Ngày (1 Tháng)", 30),
        ("90 Ngày (3 Tháng)", 90),
        ("365 Ngày (1 Năm)", 365),
        ("Vĩnh viễn (25 Năm)", 9999),
    ]:
        tk.Button(
            row_presets,
            text=label,
            command=lambda v=d_val: set_preset_days(v),
            bg="#1e293b",
            fg="#e2e8f0",
            activebackground="#4f46e5",
            activeforeground="white",
            font=("Segoe UI", 8, "bold"),
            relief="flat",
            padx=8,
            pady=3,
            cursor="hand2",
        ).pack(side="left", padx=2)

    # Nút Tạo Key & Kích hoạt
    def do_generate_key():
        hwid_val = var_hwid.get().strip()
        cust_val = var_customer.get().strip() or "Khách hàng"
        exp_val = var_exp_date.get().strip()
        try:
            days_val = int(var_days.get().strip() or "30")
        except Exception:
            days_val = 30

        try:
            key = generate_license_key(
                hwid=hwid_val,
                expires_date_str=exp_val,
                customer_name=cust_val,
                days_granted=days_val,
            )
            var_generated_key.set(key)
            root.clipboard_clear()
            root.clipboard_append(key)
            root.update()

            info = verify_license_key(key, current_hwid=hwid_val)
            rec = {
                "created_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
                "customer": cust_val,
                "hwid": info["hwid"],
                "days": days_val,
                "expires_at": info["expires_at"],
                "key": key,
            }
            save_key_history(rec)
            refresh_history_table()
        except Exception as exc:
            messagebox.showerror("Lỗi tạo Key", str(exc))

    def copy_full_customer_message():
        key = var_generated_key.get().strip()
        if not key:
            do_generate_key()
            key = var_generated_key.get().strip()
        if not key:
            return
        msg = (
            f"=== THÔNG TIN BẢN QUYỀN MUSE STUDIO ===\n"
            f"👤 Khách hàng: {var_customer.get().strip()}\n"
            f"🖥 Mã thiết bị (HWID): {var_hwid.get().strip()}\n"
            f"📅 Hạn sử dụng đến hết ngày: {var_exp_date.get().strip()} ({var_days.get().strip()} ngày)\n"
            f"🔑 Mã kích hoạt (License Key):\n{key}\n"
            f"======================================="
        )
        root.clipboard_clear()
        root.clipboard_append(msg)
        root.update()
        messagebox.showinfo("Đã sao chép", "Đã copy trọn bộ thông tin + License Key để gửi cho khách!")

    def activate_on_this_machine():
        key = var_generated_key.get().strip()
        if not key:
            do_generate_key()
            key = var_generated_key.get().strip()
        if not key:
            return
        res = activate_license_key(key)
        if res["is_valid"]:
            messagebox.showinfo("Kích hoạt thành công", res["message"])
        else:
            messagebox.showwarning("Không thể kích hoạt trên máy này", res["message"])

    row_actions = tk.Frame(body, bg="#0b0f19")
    row_actions.pack(fill="x", pady=(0, 8))

    tk.Button(
        row_actions,
        text="✨ TẠO LICENSE KEY & COPY KEY",
        command=do_generate_key,
        bg="#10b981",
        fg="#052e16",
        activebackground="#34d399",
        font=("Segoe UI", 10, "bold"),
        relief="flat",
        padx=16,
        pady=7,
        cursor="hand2",
    ).pack(side="left", padx=(0, 8))

    tk.Button(
        row_actions,
        text="📋 Copy Trọn Bộ Tin Nhắn Gửi Khách",
        command=copy_full_customer_message,
        bg="#4f46e5",
        fg="white",
        activebackground="#6366f1",
        font=("Segoe UI", 9, "bold"),
        relief="flat",
        padx=12,
        pady=7,
        cursor="hand2",
    ).pack(side="left", padx=(0, 8))

    tk.Button(
        row_actions,
        text="⚡ Kích Hoạt Luôn Cho Máy Này",
        command=activate_on_this_machine,
        bg="#1e293b",
        fg="#fde047",
        activebackground="#334155",
        font=("Segoe UI", 9, "bold"),
        relief="flat",
        padx=12,
        pady=7,
        cursor="hand2",
    ).pack(side="left")

    # Ô hiển thị License Key vừa tạo
    tk.Label(
        body,
        text="License Key vừa tạo (Đã tự động Copy vào Clipboard):",
        bg="#0b0f19",
        fg="#9ca3af",
        font=("Segoe UI", 9),
    ).pack(anchor="w")

    entry_key_out = tk.Entry(
        body,
        textvariable=var_generated_key,
        bg="#111827",
        fg="#34d399",
        insertbackground="white",
        font=("Consolas", 10, "bold"),
        relief="flat",
        bd=7,
    )
    entry_key_out.pack(fill="x", pady=(3, 12))

    # Bảng lịch sử các Key đã cấp
    tk.Label(
        body,
        text="📜 Lịch sử các License Key đã cấp gần đây (Nhấp đúp vào dòng để Copy lại Key):",
        bg="#0b0f19",
        fg="#e5e7eb",
        font=("Segoe UI", 9, "bold"),
    ).pack(anchor="w", pady=(0, 4))

    cols = ("created_at", "customer", "hwid", "days", "expires_at", "key")
    tree = ttk.Treeview(body, columns=cols, show="headings", height=8)
    tree.heading("created_at", text="Ngày tạo")
    tree.heading("customer", text="Khách hàng")
    tree.heading("hwid", text="Mã máy (HWID)")
    tree.heading("days", text="Số ngày")
    tree.heading("expires_at", text="Hết hạn")
    tree.heading("key", text="License Key")

    tree.column("created_at", width=110, anchor="center")
    tree.column("customer", width=140, anchor="w")
    tree.column("hwid", width=155, anchor="center")
    tree.column("days", width=65, anchor="center")
    tree.column("expires_at", width=90, anchor="center")
    tree.column("key", width=210, anchor="w")
    tree.pack(fill="both", expand=True)

    def refresh_history_table():
        for item in tree.get_children():
            tree.delete(item)
        for row in load_key_history():
            tree.insert(
                "",
                "end",
                values=(
                    row.get("created_at", ""),
                    row.get("customer", ""),
                    row.get("hwid", ""),
                    row.get("days", ""),
                    row.get("expires_at", ""),
                    row.get("key", ""),
                ),
            )

    def on_tree_double_click( _event):
        sel = tree.selection()
        if not sel:
            return
        vals = tree.item(sel[0], "values")
        if vals and len(vals) >= 6:
            k = vals[5]
            var_generated_key.set(k)
            root.clipboard_clear()
            root.clipboard_append(k)
            root.update()
            messagebox.showinfo("Đã copy Key", f"Đã copy lại Key của [{vals[1]}] vào Clipboard!")

    tree.bind("<Double-1>", on_tree_double_click)
    refresh_history_table()
    root.mainloop()


def main():
    parser = argparse.ArgumentParser(description="Muse Studio Admin License Key Generator")
    parser.add_argument("--hwid", type=str, help="Mã máy HWID của khách (VD: MUSE-XXXX-XXXX-XXXX)")
    parser.add_argument("--days", type=int, default=30, help="Số ngày sử dụng (mặc định: 30)")
    parser.add_argument("--expires", type=str, default="", help="Ngày hết hạn cụ thể YYYY-MM-DD")
    parser.add_argument("--customer", type=str, default="Khách hàng VIP", help="Tên khách hàng")
    parser.add_argument("--activate-local", action="store_true", help="Kích hoạt luôn vào máy hiện tại")
    args = parser.parse_args()

    if args.hwid or args.activate_local:
        target_hwid = args.hwid or get_machine_hwid()
        exp_str = args.expires or (
            datetime.now() + timedelta(days=max(0, args.days - 1))
        ).strftime("%Y-%m-%d")
        key = generate_license_key(
            hwid=target_hwid,
            expires_date_str=exp_str,
            customer_name=args.customer,
            days_granted=args.days,
        )
        print(f"HWID      : {target_hwid}")
        print(f"Customer  : {args.customer}")
        print(f"Expires   : {exp_str} ({args.days} days)")
        print(f"Key       : {key}")
        if args.activate_local:
            res = activate_license_key(key)
            print(f"Activated : {res['is_valid']} - {res['message']}")
        return

    run_gui()


if __name__ == "__main__":
    main()
