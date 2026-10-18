import asyncio
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Set
import httpx

from backend.database import get_connection, get_settings
from backend.playwright_engine import PlaywrightEngine


class TaskOrchestrator:
    """
    Bộ điều phối tác vụ đa luồng 2 tầng (2-Tier Multi-Account x Multi-Tab Queue Engine):
    - Tầng 1: Giới hạn số tài khoản chạy đồng thời (max_concurrent_accounts, mặc định 20)
    - Tầng 2: Giới hạn số Tab trên từng tài khoản (image_threads = 5, video_threads = 5)
              và tổng số luồng toàn cục (global_max_threads = 25).
    """

    def __init__(self, pw_engine: PlaywrightEngine) -> None:
        self.pw_engine = pw_engine
        self._running_tasks: Dict[int, asyncio.Task] = {}
        self._cancel_events: Dict[int, asyncio.Event] = {}
        self._task_start_times: Dict[int, float] = {}
        self._account_running_img: Dict[int, int] = {}
        self._account_running_vid: Dict[int, int] = {}
        self._rr_index: int = 0
        self._lock = asyncio.Lock()
        self._dispatcher_task: Optional[asyncio.Task] = None
        self._is_dispatching = False

    def get_task_elapsed_seconds(self, task_id: int) -> int:
        start_ts = self._task_start_times.get(task_id)
        if not start_ts:
            return 0
        return max(0, int(time.time() - start_ts))

    def get_active_counts(self) -> Dict[str, int]:
        conn = get_connection()
        running_cnt = conn.execute(
            "SELECT COUNT(*) AS c FROM tasks WHERE status = 'running'"
        ).fetchone()["c"]
        completed_cnt = conn.execute(
            "SELECT COUNT(*) AS c FROM tasks WHERE status = 'completed'"
        ).fetchone()["c"]
        pending_cnt = conn.execute(
            "SELECT COUNT(*) AS c FROM tasks WHERE status = 'pending'"
        ).fetchone()["c"]
        failed_cnt = conn.execute(
            "SELECT COUNT(*) AS c FROM tasks WHERE status = 'failed'"
        ).fetchone()["c"]
        conn.close()
        return {
            "running": running_cnt,
            "completed": completed_cnt,
            "pending": pending_cnt,
            "failed": failed_cnt,
        }

    async def start_tasks(
        self,
        project_id: Optional[int] = None,
        task_ids: Optional[List[int]] = None,
        only_failed: bool = False,
    ) -> Dict[str, Any]:
        """
        Đưa các tác vụ được chọn (hoặc toàn bộ tác vụ chờ / lỗi trong dự án) vào hàng đợi chạy.
        """
        conn = get_connection()
        cur = conn.cursor()

        if task_ids:
            placeholders = ",".join("?" for _ in task_ids)
            if only_failed:
                cur.execute(
                    f"""
                    UPDATE tasks
                    SET status = 'pending', progress_percent = 0, status_message = 'Chờ chạy'
                    WHERE id IN ({placeholders}) AND status = 'failed'
                    """,
                    task_ids,
                )
            else:
                cur.execute(
                    f"""
                    UPDATE tasks
                    SET status = 'pending', progress_percent = 0, status_message = 'Chờ chạy'
                    WHERE id IN ({placeholders}) AND status IN ('pending', 'failed', 'stopped', 'completed')
                    """,
                    task_ids,
                )
        elif project_id is not None:
            if only_failed:
                cur.execute(
                    """
                    UPDATE tasks
                    SET status = 'pending', progress_percent = 0, status_message = 'Chờ chạy'
                    WHERE project_id = ? AND status = 'failed'
                    """,
                    (project_id,),
                )
            else:
                cur.execute(
                    """
                    UPDATE tasks
                    SET status = 'pending', progress_percent = 0, status_message = 'Chờ chạy'
                    WHERE project_id = ? AND status IN ('pending', 'stopped')
                    """,
                    (project_id,),
                )

        conn.commit()
        conn.close()

        await self._ensure_dispatcher()
        return {"ok": True, "message": "Đã kích hoạt bộ điều phối tác vụ"}

    async def stop_tasks(
        self,
        project_id: Optional[int] = None,
        task_ids: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        """
        Dừng các tác vụ đang chạy hoặc đang chờ.
        """
        conn = get_connection()
        cur = conn.cursor()

        target_ids: List[int] = []
        if task_ids:
            target_ids = [int(x) for x in task_ids]
        elif project_id is not None:
            rows = cur.execute(
                "SELECT id FROM tasks WHERE project_id = ? AND status IN ('running', 'pending')",
                (project_id,),
            ).fetchall()
            target_ids = [int(r["id"]) for r in rows]
        else:
            rows = cur.execute(
                "SELECT id FROM tasks WHERE status IN ('running', 'pending')"
            ).fetchall()
            target_ids = [int(r["id"]) for r in rows]

        for tid in target_ids:
            ev = self._cancel_events.get(tid)
            if ev:
                ev.set()

        if target_ids:
            placeholders = ",".join("?" for _ in target_ids)
            cur.execute(
                f"""
                UPDATE tasks
                SET status = 'failed', status_message = 'Đã dừng'
                WHERE id IN ({placeholders}) AND status IN ('running', 'pending')
                """,
                target_ids,
            )
            conn.commit()

        conn.close()
        return {"ok": True, "stopped_count": len(target_ids)}

    async def _ensure_dispatcher(self) -> None:
        if self._dispatcher_task is None or self._dispatcher_task.done():
            self._is_dispatching = True
            self._dispatcher_task = asyncio.create_task(self._dispatch_loop())

    async def _dispatch_loop(self) -> None:
        try:
            while self._is_dispatching:
                dispatched_any = await self._dispatch_step()
                if not dispatched_any and len(self._running_tasks) == 0:
                    # Kiểm tra còn task pending nào không
                    conn = get_connection()
                    pending_row = conn.execute(
                        "SELECT COUNT(*) AS c FROM tasks WHERE status = 'pending'"
                    ).fetchone()
                    conn.close()
                    if pending_row["c"] == 0:
                        break
                await asyncio.sleep(0.8)
        finally:
            self._is_dispatching = False

    async def _dispatch_step(self) -> bool:
        async with self._lock:
            settings = get_settings()
            max_concurrent_accounts = max(
                1, int(settings.get("max_concurrent_accounts", "20") or 20)
            )
            global_max_threads = max(
                1, int(settings.get("global_max_threads", "25") or 25)
            )

            current_total_threads = len(self._running_tasks)
            if current_total_threads >= global_max_threads:
                return False

            conn = get_connection()
            pending_tasks = [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT t.*, p.name AS project_name
                    FROM tasks t
                    JOIN projects p ON p.id = t.project_id
                    WHERE t.status = 'pending'
                    ORDER BY t.stt ASC, t.id ASC
                    LIMIT 50
                    """
                ).fetchall()
            ]
            if not pending_tasks:
                conn.close()
                return False

            enabled_accounts = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM accounts WHERE is_enabled = 1 ORDER BY id ASC"
                ).fetchall()
            ]
            conn.close()

            if not enabled_accounts:
                # Nếu chưa có tài khoản nào được bật, thông báo trên status_message của task
                conn = get_connection()
                conn.execute(
                    """
                    UPDATE tasks
                    SET status_message = 'Chưa có tài khoản hoạt động (Hãy thêm TK ở tab Tài khoản)'
                    WHERE status = 'pending'
                    """
                )
                conn.commit()
                conn.close()
                await asyncio.sleep(2.0)
                return False

            dispatched = False
            for task in pending_tasks:
                if len(self._running_tasks) >= global_max_threads:
                    break

                task_id = int(task["id"])
                if task_id in self._running_tasks:
                    continue

                is_image_task = (task.get("task_type") or "video").lower() == "image"
                chosen_acc = self._pick_available_account(
                    enabled_accounts,
                    is_image_task=is_image_task,
                    max_concurrent_accounts=max_concurrent_accounts,
                )
                if chosen_acc is None:
                    continue

                acc_id = int(chosen_acc["id"])
                if is_image_task:
                    self._account_running_img[acc_id] = (
                        self._account_running_img.get(acc_id, 0) + 1
                    )
                else:
                    self._account_running_vid[acc_id] = (
                        self._account_running_vid.get(acc_id, 0) + 1
                    )

                total_acc_running = self._account_running_img.get(
                    acc_id, 0
                ) + self._account_running_vid.get(acc_id, 0)

                conn = get_connection()
                conn.execute(
                    """
                    UPDATE tasks
                    SET status = 'running',
                        assigned_account_id = ?,
                        progress_percent = 2,
                        status_message = 'Đang khởi chạy...'
                    WHERE id = ?
                    """,
                    (acc_id, task_id),
                )
                conn.execute(
                    "UPDATE accounts SET running_tasks = ? WHERE id = ?",
                    (total_acc_running, acc_id),
                )
                conn.commit()
                conn.close()

                cancel_ev = asyncio.Event()
                self._cancel_events[task_id] = cancel_ev
                self._task_start_times[task_id] = time.time()

                bg_task = asyncio.create_task(
                    self._run_single_task(task, chosen_acc, settings, cancel_ev)
                )
                self._running_tasks[task_id] = bg_task
                dispatched = True

            return dispatched

    def _pick_available_account(
        self,
        accounts: List[Dict[str, Any]],
        is_image_task: bool,
        max_concurrent_accounts: int,
    ) -> Optional[Dict[str, Any]]:
        if not accounts:
            return None

        active_account_ids: Set[int] = set()
        for acc_id, cnt in self._account_running_img.items():
            if cnt > 0:
                active_account_ids.add(acc_id)
        for acc_id, cnt in self._account_running_vid.items():
            if cnt > 0:
                active_account_ids.add(acc_id)

        n = len(accounts)
        for offset in range(n):
            idx = (self._rr_index + offset) % n
            acc = accounts[idx]
            acc_id = int(acc["id"])

            # Kiểm tra giới hạn Tầng 1: max_concurrent_accounts
            if (
                acc_id not in active_account_ids
                and len(active_account_ids) >= max_concurrent_accounts
            ):
                continue

            # Kiểm tra giới hạn Tầng 2: image_threads / video_threads trên từng tài khoản
            if is_image_task:
                limit = max(1, int(acc.get("image_threads") or 5))
                current = self._account_running_img.get(acc_id, 0)
            else:
                limit = max(1, int(acc.get("video_threads") or 5))
                current = self._account_running_vid.get(acc_id, 0)

            if current < limit:
                self._rr_index = (idx + 1) % n
                return acc

        return None

    async def _run_single_task(
        self,
        task: Dict[str, Any],
        account: Dict[str, Any],
        settings: Dict[str, str],
        cancel_event: asyncio.Event,
    ) -> None:
        task_id = int(task["id"])
        acc_id = int(account["id"])
        is_image_task = (task.get("task_type") or "video").lower() == "image"

        proxy = None
        if account.get("proxy_id"):
            conn = get_connection()
            p_row = conn.execute(
                "SELECT * FROM proxies WHERE id = ?", (account["proxy_id"],)
            ).fetchone()
            conn.close()
            if p_row:
                proxy = dict(p_row)

        def update_progress(percent: int, message: str) -> None:
            try:
                conn = get_connection()
                conn.execute(
                    """
                    UPDATE tasks
                    SET progress_percent = ?, status_message = ?
                    WHERE id = ? AND status = 'running'
                    """,
                    (percent, message, task_id),
                )
                conn.commit()
                conn.close()
            except Exception:
                pass

        try:
            ok, msg, out_path, size_mb = await self.pw_engine.execute_task_on_tab(
                task=task,
                account=account,
                proxy=proxy,
                project_name=task.get("project_name") or "Mặc định",
                settings=settings,
                progress_callback=update_progress,
                cancel_event=cancel_event,
            )

            conn = get_connection()
            if ok:
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                conn.execute(
                    """
                    UPDATE tasks
                    SET status = 'completed',
                        progress_percent = 100,
                        status_message = ?,
                        output_file_path = ?,
                        file_size_mb = ?,
                        completed_at = ?
                    WHERE id = ?
                    """,
                    (msg, out_path, size_mb, now_str, task_id),
                )
                conn.execute(
                    "UPDATE accounts SET completed_tasks = completed_tasks + 1 WHERE id = ?",
                    (acc_id,),
                )
            else:
                conn.execute(
                    """
                    UPDATE tasks
                    SET status = 'failed',
                        status_message = ?
                    WHERE id = ?
                    """,
                    (msg, task_id),
                )
                conn.execute(
                    "UPDATE accounts SET failed_tasks = failed_tasks + 1 WHERE id = ?",
                    (acc_id,),
                )
            conn.commit()
            conn.close()
        except Exception as exc:
            conn = get_connection()
            conn.execute(
                "UPDATE tasks SET status = 'failed', status_message = ? WHERE id = ?",
                (f"Lỗi ngoại lệ: {exc}", task_id),
            )
            conn.execute(
                "UPDATE accounts SET failed_tasks = failed_tasks + 1 WHERE id = ?",
                (acc_id,),
            )
            conn.commit()
            conn.close()
        finally:
            async with self._lock:
                if is_image_task:
                    self._account_running_img[acc_id] = max(
                        0, self._account_running_img.get(acc_id, 1) - 1
                    )
                else:
                    self._account_running_vid[acc_id] = max(
                        0, self._account_running_vid.get(acc_id, 1) - 1
                    )
                total_acc_running = self._account_running_img.get(
                    acc_id, 0
                ) + self._account_running_vid.get(acc_id, 0)

                conn = get_connection()
                conn.execute(
                    "UPDATE accounts SET running_tasks = ? WHERE id = ?",
                    (total_acc_running, acc_id),
                )
                conn.commit()
                conn.close()

                self._running_tasks.pop(task_id, None)
                self._cancel_events.pop(task_id, None)
                self._task_start_times.pop(task_id, None)


async def test_single_proxy(proxy_row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Kiểm tra kết nối thực tế của 1 Proxy và đo độ trễ (latency_ms).
    """
    pid = int(proxy_row["id"])
    proto = (proxy_row.get("protocol") or "http").lower()
    host = proxy_row.get("host") or ""
    port = proxy_row.get("port") or 80
    user = proxy_row.get("username")
    pwd = proxy_row.get("password")

    if user and pwd:
        proxy_url = f"{proto}://{user}:{pwd}@{host}:{port}"
    else:
        proxy_url = f"{proto}://{host}:{port}"

    start_ts = time.perf_counter()
    status = "Dead"
    latency_ms = None

    try:
        async with httpx.AsyncClient(
            proxy=proxy_url, timeout=10.0, verify=False, follow_redirects=True
        ) as client:
            resp = await client.get("https://www.google.com/generate_204")
            if resp.status_code in (200, 204, 301, 302):
                status = "Live"
                latency_ms = int((time.perf_counter() - start_ts) * 1000)
    except Exception:
        status = "Dead"
        latency_ms = None

    conn = get_connection()
    conn.execute(
        "UPDATE proxies SET status = ?, latency_ms = ? WHERE id = ?",
        (status, latency_ms, pid),
    )
    conn.commit()
    conn.close()

    return {"id": pid, "status": status, "latency_ms": latency_ms}
