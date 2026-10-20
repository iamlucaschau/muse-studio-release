import asyncio
import base64
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.database import (
    BASE_DIR,
    DEFAULT_SETTINGS,
    PROFILES_DIR,
    get_connection,
    get_settings,
    init_db,
    parse_proxy_string,
    update_settings,
)
from backend.matcher import collect_images_from_paths, match_reference_images, wrap_prompt
from backend.orchestrator import TaskOrchestrator, test_single_proxy
from backend.playwright_engine import PlaywrightEngine, get_account_profile_dir

FRONTEND_DIR = BASE_DIR / "frontend"

pw_engine = PlaywrightEngine()
orchestrator = TaskOrchestrator(pw_engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield
    await pw_engine.shutdown()


app = FastAPI(
    title="Muse Studio (AI Media & Video Automation)",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== PYDANTIC MODELS ====================


class ProjectCreateReq(BaseModel):
    name: str


class ProjectRenameReq(BaseModel):
    name: str


class MatcherPreviewReq(BaseModel):
    prompts: List[str]
    image_paths: List[str]
    ref_mode: str = "pair"


class CreateTasksReq(BaseModel):
    project_id: int
    prompts: List[str]
    task_type: str = "video"  # 'video', 'image', 'img2vid'
    aspect_ratio: str = "16:9"
    ref_mode: str = "pair"  # 'pair', 'shared', 'by_name'
    image_paths: List[str] = []
    auto_start: bool = False


class BatchTaskActionReq(BaseModel):
    project_id: Optional[int] = None
    task_ids: Optional[List[int]] = None


class AccountAddReq(BaseModel):
    display_name: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    proxy_id: Optional[int] = None
    image_threads: int = 5
    video_threads: int = 5
    bulk_text: Optional[str] = None


class AccountUpdateReq(BaseModel):
    display_name: Optional[str] = None
    is_enabled: Optional[int] = None
    image_threads: Optional[int] = None
    video_threads: Optional[int] = None
    proxy_id: Optional[int] = None


class ThreadConfigReq(BaseModel):
    max_concurrent_accounts: int = 20
    global_max_threads: int = 25
    schedule_mode: str = "round_robin"


class ProxyBulkAddReq(BaseModel):
    raw_lines: str
    protocol: str = "http"


class ProxyCheckReq(BaseModel):
    proxy_ids: Optional[List[int]] = None


class FileOpenReq(BaseModel):
    path: str


class RefImageFileItem(BaseModel):
    name: str
    data_b64: str


class RefImageUploadReq(BaseModel):
    files: List[RefImageFileItem]
    replace: bool = False


# ==================== HELPER DIALOGS ====================


def _attach_current_thread_to_default_desktop() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes
        u32 = ctypes.windll.user32
        hdesk = u32.OpenDesktopW("Default", 0, False, 0x10000000)
        if hdesk:
            u32.SetThreadDesktop(hdesk)
        u32.keybd_event(0x12, 0, 0, 0)
        u32.keybd_event(0x12, 0, 2, 0)
    except Exception:
        pass


def open_native_file_dialog(multiple: bool = True) -> List[str]:
    """Mở hộp thoại chọn file ảnh gốc trên Windows bằng tkinter (chạy trên thread riêng)."""
    result: List[str] = []

    def _run():
        try:
            _attach_current_thread_to_default_desktop()
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            root.lift()
            root.focus_force()
            if multiple:
                files = filedialog.askopenfilenames(
                    parent=root,
                    title="Chọn ảnh tham chiếu (.png, .jpg, .jpeg, .webp)",
                    filetypes=[
                        ("Image files", "*.png *.jpg *.jpeg *.webp"),
                        ("All files", "*.*"),
                    ],
                )
                result.extend(list(files))
            else:
                f = filedialog.askopenfilename(
                    parent=root,
                    title="Chọn file ảnh",
                    filetypes=[
                        ("Image files", "*.png *.jpg *.jpeg *.webp"),
                        ("All files", "*.*"),
                    ],
                )
                if f:
                    result.append(f)
            root.destroy()
        except Exception:
            pass

    t = threading.Thread(target=_run)
    t.start()
    t.join()
    return [str(Path(p).resolve()) for p in result if p]


def open_native_folder_dialog(title: str = "Chọn thư mục") -> Optional[str]:
    """
    Mở hộp thoại chọn thư mục gốc trên Windows bằng tiến trình con gắn trực tiếp vào
    WinSta0\\Default để luôn nổi lên phía trước trình duyệt của người dùng.
    """
    out_file = BASE_DIR / ".muse" / "picked_folder.txt"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    if out_file.exists():
        try:
            out_file.unlink()
        except Exception:
            pass

    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            k32 = ctypes.windll.kernel32
            u32 = ctypes.windll.user32
            hdesk = u32.OpenDesktopW("Default", 0, False, 0x10000000)
            if hdesk:
                u32.SetThreadDesktop(hdesk)
            u32.keybd_event(0x12, 0, 0, 0)
            u32.keybd_event(0x12, 0, 2, 0)

            script = (
                "import tkinter as tk; from tkinter import filedialog; from pathlib import Path; "
                "r = tk.Tk(); r.withdraw(); r.attributes('-topmost', True); r.lift(); r.focus_force(); "
                f"f = filedialog.askdirectory(parent=r, title={repr(title)}); r.destroy(); "
                f"Path({repr(str(out_file))}).write_text(f or '', encoding='utf-8')"
            )
            cmd_line = f'"{sys.executable}" -c "{script}"'

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
            ok = k32.CreateProcessW(
                None, buf, None, None, False, 0x08000000, None, None, ctypes.byref(si), ctypes.byref(pi)
            )
            if ok:
                k32.WaitForSingleObject(pi.hProcess, 120000)
                if pi.hProcess:
                    k32.CloseHandle(pi.hProcess)
                if pi.hThread:
                    k32.CloseHandle(pi.hThread)
                if out_file.exists():
                    picked = out_file.read_text(encoding="utf-8").strip()
                    if picked:
                        return str(Path(picked).resolve())
                return None
        except Exception:
            pass

    selected: List[str] = []

    def _run():
        try:
            _attach_current_thread_to_default_desktop()
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            root.lift()
            root.focus_force()
            folder = filedialog.askdirectory(parent=root, title=title)
            if folder:
                selected.append(folder)
            root.destroy()
        except Exception:
            pass

    t = threading.Thread(target=_run)
    t.start()
    t.join()
    return str(Path(selected[0]).resolve()) if selected else None


# ==================== API ENDPOINTS ====================


@app.get("/api/state")
async def api_get_state(
    project_id: Optional[int] = Query(None),
    status_filter: str = Query("all"),
    search: str = Query(""),
):
    conn = get_connection()
    projects = [
        dict(r)
        for r in conn.execute("SELECT * FROM projects ORDER BY id ASC").fetchall()
    ]
    if not projects:
        conn.execute("INSERT INTO projects (name) VALUES (?)", ("Mặc định",))
        conn.commit()
        projects = [
            dict(r)
            for r in conn.execute("SELECT * FROM projects ORDER BY id ASC").fetchall()
        ]

    active_project_id = project_id or projects[0]["id"]
    if not any(p["id"] == active_project_id for p in projects):
        active_project_id = projects[0]["id"]

    # Lấy danh sách tasks của dự án đang chọn
    sql = """
        SELECT t.*, a.display_name AS account_name, a.email AS account_email, p.name AS project_name
        FROM tasks t
        LEFT JOIN accounts a ON a.id = t.assigned_account_id
        LEFT JOIN projects p ON p.id = t.project_id
        WHERE t.project_id = ?
    """
    params: List[Any] = [active_project_id]

    if status_filter and status_filter != "all":
        sql += " AND t.status = ?"
        params.append(status_filter)

    if search and search.strip():
        q = f"%{search.strip()}%"
        sql += " AND (t.task_name LIKE ? OR t.prompt_text LIKE ?)"
        params.extend([q, q])

    sql += " ORDER BY t.stt ASC, t.id ASC"
    task_rows = [dict(r) for r in conn.execute(sql, params).fetchall()]

    for t in task_rows:
        t["elapsed_seconds"] = (
            orchestrator.get_task_elapsed_seconds(int(t["id"]))
            if t["status"] == "running"
            else 0
        )
        try:
            t["ref_images"] = (
                json.loads(t["ref_images_json"]) if t.get("ref_images_json") else []
            )
        except Exception:
            t["ref_images"] = []

    # Đếm theo trạng thái trong dự án hiện tại
    proj_counts_rows = conn.execute(
        "SELECT status, COUNT(*) AS cnt FROM tasks WHERE project_id = ? GROUP BY status",
        (active_project_id,),
    ).fetchall()
    proj_counts = {"all": 0, "pending": 0, "running": 0, "completed": 0, "failed": 0}
    for r in proj_counts_rows:
        st = r["status"]
        c = int(r["cnt"])
        proj_counts["all"] += c
        if st in proj_counts:
            proj_counts[st] = c

    conn.close()
    global_counts = orchestrator.get_active_counts()
    settings = get_settings()

    return {
        "projects": projects,
        "active_project_id": active_project_id,
        "tasks": task_rows,
        "project_counts": proj_counts,
        "global_counts": global_counts,
        "settings": settings,
    }


# -------------------- PROJECTS --------------------


@app.post("/api/projects")
async def api_create_project(req: ProjectCreateReq):
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Tên dự án không được để trống")
    conn = get_connection()
    try:
        cur = conn.execute("INSERT INTO projects (name) VALUES (?)", (name,))
        conn.commit()
        new_id = cur.lastrowid
        row = dict(
            conn.execute("SELECT * FROM projects WHERE id = ?", (new_id,)).fetchone()
        )
        return {"ok": True, "project": row}
    except Exception:
        raise HTTPException(status_code=400, detail="Tên dự án đã tồn tại")
    finally:
        conn.close()


@app.put("/api/projects/{project_id}")
async def api_rename_project(project_id: int, req: ProjectRenameReq):
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Tên dự án không được để trống")
    conn = get_connection()
    try:
        conn.execute("UPDATE projects SET name = ? WHERE id = ?", (name, project_id))
        conn.commit()
        return {"ok": True}
    except Exception:
        raise HTTPException(status_code=400, detail="Không thể đổi tên dự án (trùng tên)")
    finally:
        conn.close()


@app.delete("/api/projects/{project_id}")
async def api_delete_project(project_id: int):
    await orchestrator.stop_tasks(project_id=project_id)
    conn = get_connection()
    conn.execute("DELETE FROM tasks WHERE project_id = ?", (project_id,))
    conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    remaining = conn.execute("SELECT COUNT(*) AS c FROM projects").fetchone()["c"]
    if remaining == 0:
        conn.execute("INSERT INTO projects (name) VALUES (?)", ("Mặc định",))
    conn.commit()
    first_proj = dict(
        conn.execute("SELECT * FROM projects ORDER BY id ASC LIMIT 1").fetchone()
    )
    conn.close()
    return {"ok": True, "next_project_id": first_proj["id"]}


# -------------------- NATIVE DIALOGS & MATCHER --------------------


@app.post("/api/dialog/select-images")
async def api_select_images():
    files = await asyncio.to_thread(open_native_file_dialog, True)
    valid = collect_images_from_paths(files)
    items = [{"path": p, "name": Path(p).name, "stem": Path(p).stem} for p in valid]
    return {"ok": True, "images": items}


@app.post("/api/dialog/select-folder")
async def api_select_folder(purpose: str = Query("ref_images")):
    title = (
        "Chọn thư mục ảnh tham chiếu"
        if purpose == "ref_images"
        else "Chọn thư mục lưu file Output"
    )
    folder = await asyncio.to_thread(open_native_folder_dialog, title)
    if not folder:
        return {"ok": False, "folder": None, "images": []}
    if purpose == "ref_images":
        valid = collect_images_from_paths([folder])
        items = [{"path": p, "name": Path(p).name, "stem": Path(p).stem} for p in valid]
        return {"ok": True, "folder": folder, "images": items}
    return {"ok": True, "folder": folder, "images": []}


@app.post("/api/dialog/upload-ref-images")
async def api_upload_ref_images(req: RefImageUploadReq):
    """
    Nhận danh sách file ảnh được chọn trực tiếp từ hộp thoại trình duyệt (<input type='file'>),
    lưu vào .muse/ref_uploads/{tên_file_gốc} để giữ nguyên 100% tên file cho cả 3 chế độ ghép ảnh
    (Ghép cặp, Dùng chung, Theo tên prompt) và cấp đường dẫn thực tế cho Playwright upload.
    """
    ref_dir = BASE_DIR / ".muse" / "ref_uploads"
    ref_dir.mkdir(parents=True, exist_ok=True)
    items: List[Dict[str, str]] = []
    valid_exts = {".png", ".jpg", ".jpeg", ".webp"}

    for f_item in req.files:
        raw_name = Path(f_item.name).name
        safe_name = re.sub(r'[<>:"/\\|?*]', "_", raw_name).strip()
        if not safe_name:
            continue
        ext = Path(safe_name).suffix.lower()
        if ext not in valid_exts:
            continue
        b64_str = f_item.data_b64
        if "," in b64_str:
            b64_str = b64_str.split(",", 1)[1]
        try:
            raw_bytes = base64.b64decode(b64_str)
            target_path = (ref_dir / safe_name).resolve()
            target_path.write_bytes(raw_bytes)
            items.append(
                {
                    "path": str(target_path),
                    "name": target_path.name,
                    "stem": target_path.stem,
                }
            )
        except Exception:
            continue

    return {"ok": True, "images": items}


@app.post("/api/matcher/preview")
async def api_matcher_preview(req: MatcherPreviewReq):
    clean_prompts = [p.strip() for p in req.prompts if p.strip()]
    matched = match_reference_images(clean_prompts, req.image_paths, req.ref_mode)
    preview = []
    for idx, p_text in enumerate(clean_prompts):
        imgs = matched[idx] if idx < len(matched) else []
        preview.append(
            {
                "index": idx + 1,
                "prompt": p_text,
                "matched_images": [
                    {"path": ip, "name": Path(ip).name} for ip in imgs
                ],
            }
        )
    return {"ok": True, "preview": preview}


# -------------------- TASKS & QUEUE ENGINE --------------------


@app.post("/api/tasks/create")
async def api_create_tasks(req: CreateTasksReq):
    clean_prompts = [p.strip() for p in req.prompts if p.strip()]
    if not clean_prompts:
        raise HTTPException(status_code=400, detail="Vui lòng nhập ít nhất 1 dòng Prompt")

    conn = get_connection()
    proj_row = conn.execute(
        "SELECT * FROM projects WHERE id = ?", (req.project_id,)
    ).fetchone()
    if not proj_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")

    proj_name = proj_row["name"]
    prefix = re.sub(r"\s+", "_", proj_name.strip())

    max_stt_row = conn.execute(
        "SELECT COALESCE(MAX(stt), 0) AS max_stt FROM tasks WHERE project_id = ?",
        (req.project_id,),
    ).fetchone()
    current_stt = int(max_stt_row["max_stt"] or 0)

    matched_lists = match_reference_images(
        clean_prompts, req.image_paths, req.ref_mode
    )

    created_ids: List[int] = []
    cur = conn.cursor()
    for idx, p_text in enumerate(clean_prompts):
        current_stt += 1
        task_name = f"{prefix}_{current_stt:03d}"
        ref_imgs = matched_lists[idx] if idx < len(matched_lists) else []
        cur.execute(
            """
            INSERT INTO tasks (
                project_id, stt, task_name, prompt_text,
                task_type, aspect_ratio, ref_mode, ref_images_json,
                status, progress_percent, status_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, 'Chờ chạy')
            """,
            (
                req.project_id,
                current_stt,
                task_name,
                p_text,
                req.task_type,
                req.aspect_ratio,
                req.ref_mode,
                json.dumps(ref_imgs, ensure_ascii=False),
            ),
        )
        created_ids.append(cur.lastrowid)

    conn.commit()
    conn.close()

    if req.auto_start and created_ids:
        await orchestrator.start_tasks(project_id=req.project_id, task_ids=created_ids)

    return {"ok": True, "created_count": len(created_ids), "task_ids": created_ids}


@app.post("/api/tasks/reindex")
async def api_reindex_tasks(req: BatchTaskActionReq):
    if not req.project_id:
        raise HTTPException(status_code=400, detail="Thiếu project_id")
    conn = get_connection()
    proj = conn.execute(
        "SELECT name FROM projects WHERE id = ?", (req.project_id,)
    ).fetchone()
    if not proj:
        conn.close()
        raise HTTPException(status_code=404, detail="Không tìm thấy dự án")

    prefix = re.sub(r"\s+", "_", proj["name"].strip())
    rows = conn.execute(
        "SELECT id FROM tasks WHERE project_id = ? ORDER BY stt ASC, id ASC",
        (req.project_id,),
    ).fetchall()
    cur = conn.cursor()
    for i, r in enumerate(rows, start=1):
        new_name = f"{prefix}_{i:03d}"
        cur.execute(
            "UPDATE tasks SET stt = ?, task_name = ? WHERE id = ?",
            (i, new_name, r["id"]),
        )
    conn.commit()
    conn.close()
    return {"ok": True, "reindexed": len(rows)}


@app.post("/api/tasks/start")
async def api_start_tasks(req: BatchTaskActionReq):
    return await orchestrator.start_tasks(
        project_id=req.project_id, task_ids=req.task_ids, only_failed=False
    )


@app.post("/api/tasks/retry-failed")
async def api_retry_failed_tasks(req: BatchTaskActionReq):
    return await orchestrator.start_tasks(
        project_id=req.project_id, task_ids=req.task_ids, only_failed=True
    )


@app.post("/api/tasks/stop")
async def api_stop_tasks(req: BatchTaskActionReq):
    return await orchestrator.stop_tasks(
        project_id=req.project_id, task_ids=req.task_ids
    )


@app.post("/api/tasks/{task_id}/retry")
async def api_retry_single_task(task_id: int):
    return await orchestrator.start_tasks(task_ids=[task_id], only_failed=False)


@app.post("/api/tasks/delete")
async def api_delete_tasks(req: BatchTaskActionReq):
    if req.task_ids:
        await orchestrator.stop_tasks(task_ids=req.task_ids)
        conn = get_connection()
        placeholders = ",".join("?" for _ in req.task_ids)
        conn.execute(f"DELETE FROM tasks WHERE id IN ({placeholders})", req.task_ids)
        conn.commit()
        conn.close()
        return {"ok": True, "deleted": len(req.task_ids)}
    elif req.project_id:
        await orchestrator.stop_tasks(project_id=req.project_id)
        conn = get_connection()
        conn.execute("DELETE FROM tasks WHERE project_id = ?", (req.project_id,))
        conn.commit()
        conn.close()
        return {"ok": True}
    return {"ok": False}


# -------------------- MEDIA GALLERY (TAB 2) --------------------


def _resolve_media_path(raw_path: str) -> Path:
    if not raw_path:
        return BASE_DIR / "output"
    p = Path(raw_path)
    if not p.is_absolute():
        p = (BASE_DIR / raw_path).resolve()
    if p.exists():
        return p.resolve()
    # Fallback lookup in output/IMG and output/VIDEO if path was moved
    fname = p.name
    if fname:
        for sub in ("IMG", "VIDEO"):
            cand = (BASE_DIR / "output" / sub / fname).resolve()
            if cand.exists():
                return cand
    return p.resolve()


def _spawn_on_default_desktop(
    cmd_line: str, show_window: int = 1, creation_flags: int = 0
) -> bool:
    """
    Launch a process explicitly on WinSta0\\Default so that even if the backend
    server was started inside an isolated desktop (e.g. exebox), Explorer and
    Media Viewer windows always appear on the user's real monitor in the foreground.
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.windll.kernel32
        u32 = ctypes.windll.user32

        hdesk = u32.OpenDesktopW("Default", 0, False, 0x10000000)
        if hdesk:
            u32.SetThreadDesktop(hdesk)

        # Release Windows ForegroundLockTimeout
        u32.keybd_event(0x12, 0, 0, 0)
        u32.keybd_event(0x12, 0, 2, 0)

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
        si.dwFlags = 1  # STARTF_USESHOWWINDOW
        si.wShowWindow = show_window
        pi = PROCESS_INFORMATION()
        buf = ctypes.create_unicode_buffer(cmd_line)

        ok = k32.CreateProcessW(
            None,
            buf,
            None,
            None,
            False,
            creation_flags,
            None,
            None,
            ctypes.byref(si),
            ctypes.byref(pi),
        )
        if ok:
            if pi.hProcess:
                k32.CloseHandle(pi.hProcess)
            if pi.hThread:
                k32.CloseHandle(pi.hThread)
            return True
    except Exception:
        pass
    return False


@app.get("/api/gallery")
async def api_get_gallery(
    media_type: str = Query("all"),
    project_id: Optional[int] = Query(None),
):
    conn = get_connection()
    sql = """
        SELECT t.*, p.name AS project_name, a.display_name AS account_name, a.email AS account_email
        FROM tasks t
        LEFT JOIN projects p ON p.id = t.project_id
        LEFT JOIN accounts a ON a.id = t.assigned_account_id
        WHERE t.status = 'completed' AND t.output_file_path IS NOT NULL
    """
    params: List[Any] = []
    if media_type == "video":
        sql += " AND t.task_type IN ('video', 'img2vid')"
    elif media_type == "image":
        sql += " AND t.task_type = 'image'"

    if project_id is not None and project_id > 0:
        sql += " AND t.project_id = ?"
        params.append(project_id)

    sql += " ORDER BY t.completed_at DESC, t.id DESC"
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    conn.close()

    items = []
    for r in rows:
        fpath = r.get("output_file_path")
        resolved = _resolve_media_path(fpath) if fpath else None
        exists = bool(resolved and resolved.exists())
        if exists and str(resolved) != fpath:
            r["output_file_path"] = str(resolved)
        items.append({**r, "file_exists": exists})

    return {"ok": True, "items": items}


@app.get("/api/media/stream")
async def api_stream_media(path: str = Query(...)):
    p = _resolve_media_path(path)
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="File không tồn tại")
    mime, _ = mimetypes.guess_type(str(p))
    return FileResponse(str(p), media_type=mime or "application/octet-stream")


@app.post("/api/system/open-file")
async def api_open_file(req: FileOpenReq):
    p = _resolve_media_path(req.path)
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail=f"File không tồn tại trên ổ đĩa: {p}")
    try:
        if sys.platform == "win32":
            # Launch via cmd.exe /c start on WinSta0\Default so Windows Photos / Video Player opens on user's screen
            if not _spawn_on_default_desktop(
                f'cmd.exe /c start "" "{p}"', show_window=0, creation_flags=0x08000000
            ):
                os.startfile(str(p))
        else:
            subprocess.Popen(["xdg-open", str(p)])
        return {"ok": True, "path": str(p)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/system/open-folder")
async def api_open_folder(req: FileOpenReq):
    p = _resolve_media_path(req.path)
    try:
        if p.exists() and p.is_file():
            if sys.platform == "win32":
                # Note: /select, MUST be outside quotes for explorer.exe to parse paths with spaces!
                if not _spawn_on_default_desktop(f'explorer.exe /select,"{p}"', show_window=1):
                    subprocess.Popen(f'explorer.exe /select,"{p}"', shell=True)
                return {"ok": True, "path": str(p)}
            p = p.parent

        if not p.exists():
            # If it had a file suffix (e.g. missing file), open its parent folder or output root
            if p.suffix:
                p = p.parent if p.parent.exists() else (BASE_DIR / "output")
            p.mkdir(parents=True, exist_ok=True)

        # Ensure IMG and VIDEO subfolders exist when opening output root
        if p.name.lower() == "output":
            (p / "IMG").mkdir(parents=True, exist_ok=True)
            (p / "VIDEO").mkdir(parents=True, exist_ok=True)

        if sys.platform == "win32":
            if not _spawn_on_default_desktop(f'explorer.exe "{p}"', show_window=1):
                subprocess.Popen(f'explorer.exe "{p}"', shell=True)
        else:
            subprocess.Popen(["xdg-open", str(p)])
        return {"ok": True, "path": str(p)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# -------------------- ACCOUNTS (TAB 3) --------------------


@app.get("/api/accounts")
async def api_get_accounts():
    conn = get_connection()
    rows = [
        dict(r)
        for r in conn.execute(
            """
            SELECT a.*, p.raw_string AS proxy_raw, p.status AS proxy_status, p.host AS proxy_host, p.port AS proxy_port
            FROM accounts a
            LEFT JOIN proxies p ON p.id = a.proxy_id
            ORDER BY a.id ASC
            """
        ).fetchall()
    ]
    conn.close()
    settings = get_settings()
    return {
        "ok": True,
        "accounts": rows,
        "thread_config": {
            "max_concurrent_accounts": int(
                settings.get("max_concurrent_accounts", "20") or 20
            ),
            "global_max_threads": int(settings.get("global_max_threads", "25") or 25),
            "schedule_mode": settings.get("schedule_mode", "round_robin"),
        },
    }


@app.post("/api/accounts/add")
async def api_add_accounts(req: AccountAddReq):
    conn = get_connection()
    cur = conn.cursor()
    added_ids: List[int] = []

    if req.bulk_text and req.bulk_text.strip():
        # Hỗ trợ thêm hàng loạt định dạng: email|pass|proxy hoặc email|pass hoặc email
        lines = [ln.strip() for ln in req.bulk_text.splitlines() if ln.strip()]
        for ln in lines:
            parts = [x.strip() for x in ln.split("|")]
            email = parts[0] if len(parts) >= 1 else ""
            if not email:
                continue
            password = parts[1] if len(parts) >= 2 else ""
            proxy_str = parts[2] if len(parts) >= 3 else ""
            display_name = email.split("@")[0]

            proxy_id = None
            if proxy_str:
                parsed = parse_proxy_string(proxy_str)
                cur.execute(
                    """
                    INSERT INTO proxies (raw_string, protocol, host, port, username, password, status)
                    VALUES (?, ?, ?, ?, ?, ?, 'Chưa kiểm tra')
                    """,
                    (
                        parsed["raw_string"],
                        parsed["protocol"],
                        parsed["host"],
                        parsed["port"],
                        parsed["username"],
                        parsed["password"],
                    ),
                )
                proxy_id = cur.lastrowid

            cur.execute(
                """
                INSERT INTO accounts (
                    display_name, email, password, proxy_id,
                    image_threads, video_threads, is_enabled
                ) VALUES (?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    display_name,
                    email,
                    password,
                    proxy_id,
                    req.image_threads,
                    req.video_threads,
                ),
            )
            acc_id = cur.lastrowid
            prof_dir = get_account_profile_dir(acc_id)
            cur.execute(
                "UPDATE accounts SET profile_path = ? WHERE id = ?",
                (str(prof_dir), acc_id),
            )
            if proxy_id:
                cur.execute(
                    "UPDATE proxies SET assigned_account_id = ? WHERE id = ?",
                    (acc_id, proxy_id),
                )
            added_ids.append(acc_id)
    else:
        email = (req.email or "").strip()
        if not email:
            conn.close()
            raise HTTPException(status_code=400, detail="Email không được để trống")
        display_name = (req.display_name or "").strip() or email.split("@")[0]
        cur.execute(
            """
            INSERT INTO accounts (
                display_name, email, password, proxy_id,
                image_threads, video_threads, is_enabled
            ) VALUES (?, ?, ?, ?, ?, ?, 1)
            """,
            (
                display_name,
                email,
                req.password or "",
                req.proxy_id,
                req.image_threads,
                req.video_threads,
            ),
        )
        acc_id = cur.lastrowid
        prof_dir = get_account_profile_dir(acc_id)
        cur.execute(
            "UPDATE accounts SET profile_path = ? WHERE id = ?",
            (str(prof_dir), acc_id),
        )
        if req.proxy_id:
            cur.execute(
                "UPDATE proxies SET assigned_account_id = ? WHERE id = ?",
                (acc_id, req.proxy_id),
            )
        added_ids.append(acc_id)

    conn.commit()
    conn.close()
    return {"ok": True, "added_count": len(added_ids), "account_ids": added_ids}


@app.put("/api/accounts/{account_id}")
async def api_update_account(account_id: int, req: AccountUpdateReq):
    conn = get_connection()
    cur = conn.cursor()
    if req.display_name is not None:
        cur.execute(
            "UPDATE accounts SET display_name = ? WHERE id = ?",
            (req.display_name.strip(), account_id),
        )
    if req.is_enabled is not None:
        cur.execute(
            "UPDATE accounts SET is_enabled = ? WHERE id = ?",
            (1 if req.is_enabled else 0, account_id),
        )
    if req.image_threads is not None:
        cur.execute(
            "UPDATE accounts SET image_threads = ? WHERE id = ?",
            (max(1, req.image_threads), account_id),
        )
    if req.video_threads is not None:
        cur.execute(
            "UPDATE accounts SET video_threads = ? WHERE id = ?",
            (max(1, req.video_threads), account_id),
        )
    if req.proxy_id is not None:
        val = req.proxy_id if req.proxy_id > 0 else None
        cur.execute(
            "UPDATE accounts SET proxy_id = ? WHERE id = ?", (val, account_id)
        )
        if val:
            cur.execute(
                "UPDATE proxies SET assigned_account_id = ? WHERE id = ?",
                (account_id, val),
            )
    conn.commit()
    conn.close()
    return {"ok": True}


@app.delete("/api/accounts/{account_id}")
async def api_delete_account(account_id: int):
    await pw_engine.close_account_session(account_id)
    conn = get_connection()
    conn.execute(
        "UPDATE proxies SET assigned_account_id = NULL WHERE assigned_account_id = ?",
        (account_id,),
    )
    conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.post("/api/accounts/{account_id}/login")
async def api_login_account(account_id: int):
    """Mở Chrome hiển thị trực quan cho phép người dùng nhập OTP 6 số và tự động trích xuất Cookie."""
    res = await pw_engine.interactive_login(account_id)
    return res


@app.post("/api/accounts/{account_id}/check-cookie")
async def api_check_account_cookie(account_id: int):
    return await pw_engine.check_account_cookie_and_quota(account_id, check_quota=False)


@app.post("/api/accounts/{account_id}/check-quota")
async def api_check_account_quota(account_id: int):
    return await pw_engine.check_account_cookie_and_quota(account_id, check_quota=True)


@app.post("/api/accounts/batch-check-cookies")
async def api_batch_check_cookies():
    conn = get_connection()
    ids = [r["id"] for r in conn.execute("SELECT id FROM accounts").fetchall()]
    conn.close()
    results = []
    for aid in ids:
        results.append(
            await pw_engine.check_account_cookie_and_quota(aid, check_quota=False)
        )
    return {"ok": True, "results": results}


@app.post("/api/accounts/batch-check-quota")
async def api_batch_check_quota():
    conn = get_connection()
    ids = [r["id"] for r in conn.execute("SELECT id FROM accounts").fetchall()]
    conn.close()
    results = []
    for aid in ids:
        results.append(
            await pw_engine.check_account_cookie_and_quota(aid, check_quota=True)
        )
    return {"ok": True, "results": results}


@app.post("/api/accounts/thread-config")
async def api_save_thread_config(req: ThreadConfigReq):
    update_settings(
        {
            "max_concurrent_accounts": str(max(1, req.max_concurrent_accounts)),
            "global_max_threads": str(max(1, req.global_max_threads)),
            "schedule_mode": req.schedule_mode,
        }
    )
    return {"ok": True}


# -------------------- PROXIES (TAB 4) --------------------


@app.get("/api/proxies")
async def api_get_proxies():
    conn = get_connection()
    rows = [
        dict(r)
        for r in conn.execute(
            """
            SELECT p.*, a.email AS account_email, a.display_name AS account_name
            FROM proxies p
            LEFT JOIN accounts a ON a.id = p.assigned_account_id
            ORDER BY p.id ASC
            """
        ).fetchall()
    ]
    conn.close()
    return {"ok": True, "proxies": rows}


@app.post("/api/proxies/add")
async def api_add_proxies(req: ProxyBulkAddReq):
    lines = [ln.strip() for ln in req.raw_lines.splitlines() if ln.strip()]
    if not lines:
        raise HTTPException(status_code=400, detail="Danh sách proxy trống")
    conn = get_connection()
    cur = conn.cursor()
    added = 0
    for ln in lines:
        parsed = parse_proxy_string(ln, default_protocol=req.protocol)
        if not parsed["host"]:
            continue
        cur.execute(
            """
            INSERT INTO proxies (raw_string, protocol, host, port, username, password, status)
            VALUES (?, ?, ?, ?, ?, ?, 'Chưa kiểm tra')
            """,
            (
                parsed["raw_string"],
                parsed["protocol"],
                parsed["host"],
                parsed["port"],
                parsed["username"],
                parsed["password"],
            ),
        )
        added += 1
    conn.commit()
    conn.close()
    return {"ok": True, "added": added}


@app.post("/api/proxies/check")
async def api_check_proxies(req: ProxyCheckReq):
    conn = get_connection()
    if req.proxy_ids:
        placeholders = ",".join("?" for _ in req.proxy_ids)
        rows = [
            dict(r)
            for r in conn.execute(
                f"SELECT * FROM proxies WHERE id IN ({placeholders})", req.proxy_ids
            ).fetchall()
        ]
    else:
        rows = [dict(r) for r in conn.execute("SELECT * FROM proxies").fetchall()]
    conn.close()

    if not rows:
        return {"ok": True, "results": []}

    results = await asyncio.gather(*(test_single_proxy(r) for r in rows))
    return {"ok": True, "results": results}


@app.post("/api/proxies/auto-assign")
async def api_auto_assign_proxies():
    """Tự động gán các Proxy (ưu tiên Live hoặc chưa gán) vào danh sách Tài khoản."""
    conn = get_connection()
    cur = conn.cursor()
    accounts = [
        dict(r)
        for r in cur.execute("SELECT id, proxy_id FROM accounts ORDER BY id ASC").fetchall()
    ]
    proxies = [
        dict(r)
        for r in cur.execute(
            "SELECT id, status FROM proxies WHERE status != 'Dead' ORDER BY CASE WHEN status = 'Live' THEN 0 ELSE 1 END, id ASC"
        ).fetchall()
    ]
    if not proxies or not accounts:
        conn.close()
        return {"ok": False, "assigned": 0, "message": "Cần có cả Tài khoản và Proxy khả dụng"}

    cur.execute("UPDATE proxies SET assigned_account_id = NULL")
    assigned = 0
    for idx, acc in enumerate(accounts):
        p = proxies[idx % len(proxies)]
        cur.execute(
            "UPDATE accounts SET proxy_id = ? WHERE id = ?", (p["id"], acc["id"])
        )
        cur.execute(
            "UPDATE proxies SET assigned_account_id = ? WHERE id = ?",
            (acc["id"], p["id"]),
        )
        assigned += 1

    conn.commit()
    conn.close()
    return {"ok": True, "assigned": assigned}


@app.delete("/api/proxies/{proxy_id}")
async def api_delete_proxy(proxy_id: int):
    conn = get_connection()
    conn.execute("UPDATE accounts SET proxy_id = NULL WHERE proxy_id = ?", (proxy_id,))
    conn.execute("DELETE FROM proxies WHERE id = ?", (proxy_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.post("/api/proxies/clear-dead")
async def api_clear_dead_proxies():
    conn = get_connection()
    dead_ids = [
        r["id"]
        for r in conn.execute("SELECT id FROM proxies WHERE status = 'Dead'").fetchall()
    ]
    if dead_ids:
        placeholders = ",".join("?" for _ in dead_ids)
        conn.execute(
            f"UPDATE accounts SET proxy_id = NULL WHERE proxy_id IN ({placeholders})",
            dead_ids,
        )
        conn.execute(f"DELETE FROM proxies WHERE id IN ({placeholders})", dead_ids)
        conn.commit()
    conn.close()
    return {"ok": True, "deleted": len(dead_ids)}


# -------------------- SETTINGS (TAB 5) --------------------


@app.get("/api/settings")
async def api_get_settings():
    return {"ok": True, "settings": get_settings()}


@app.post("/api/settings")
async def api_save_settings(payload: Dict[str, Any]):
    updated = update_settings(payload)
    return {"ok": True, "settings": updated}


@app.post("/api/settings/reset-templates")
async def api_reset_templates():
    tpl_defaults = {
        k: v for k, v in DEFAULT_SETTINGS.items() if k.startswith("tpl_")
    }
    updated = update_settings(tpl_defaults)
    return {"ok": True, "settings": updated}


# -------------------- STATIC FRONTEND --------------------

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
async def serve_index():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


# ==================== DESKTOP RUNNER ====================


def start_uvicorn(host: str, port: int) -> None:
    uvicorn.run(app, host=host, port=port, log_level="warning")


def main() -> None:
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    init_db()
    host = "127.0.0.1"
    port = 18688
    url = f"http://{host}:{port}"

    no_open = "--no-open" in sys.argv or "--server-only" in sys.argv
    if not no_open:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()

    print(f"[Muse Studio] Server running at: {url}")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()


