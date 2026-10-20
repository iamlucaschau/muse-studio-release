import json
from pathlib import Path
from fastapi.testclient import TestClient

from backend.database import init_db, get_settings, parse_proxy_string
from backend.matcher import match_reference_images, wrap_prompt
from app import app


def test_all():
    init_db()
    settings = get_settings()

    # 1. Kiểm tra 4 mẫu Prompt Wrapper
    p_t2i = wrap_prompt("A cat on Mars", "image", "16:9", False, settings)
    assert "Create 1 image(s) with aspect ratio 16:9" in p_t2i
    assert "A cat on Mars" in p_t2i

    p_i2i = wrap_prompt("Keep style", "image", "1:1", True, settings)
    assert "using the attached image(s) as reference" in p_i2i

    p_t2v = wrap_prompt("Cyberpunk city", "video", "16:9", False, settings)
    assert "Create a video with aspect ratio 16:9." in p_t2v

    p_i2v = wrap_prompt("Animate character", "img2vid", "9:16", True, settings)
    assert "(image-to-video)" in p_i2v

    # 2. Kiểm tra 3 chế độ ghép ảnh tham chiếu (pair, shared, by_name)
    tmp_dir = Path(".muse/test_refs")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    img1 = tmp_dir / "anh_so_1.png"
    img2 = tmp_dir / "anh_so_2.jpg"
    img1.write_bytes(b"fake_png_1")
    img2.write_bytes(b"fake_jpg_2")

    prompts = [
        "Cho nhân vật anh_so_1 đi bộ dưới mưa cùng anh_so_2",
        "Cảnh riêng của ANH_SO_2 trên phố",
        "Cảnh phong cảnh không có nhân vật",
    ]

    # Chế độ 1: Ghép cặp (pair)
    pair_res = match_reference_images(prompts, [str(img1), str(img2)], "pair")
    assert len(pair_res[0]) == 1 and Path(pair_res[0][0]).name == "anh_so_1.png"
    assert len(pair_res[1]) == 1 and Path(pair_res[1][0]).name == "anh_so_2.jpg"
    assert len(pair_res[2]) == 0

    # Chế độ 2: Dùng chung (shared)
    shared_res = match_reference_images(prompts, [str(img1), str(img2)], "shared")
    assert all(len(r) == 2 for r in shared_res)

    # Chế độ 3: Theo tên prompt (by_name)
    byname_res = match_reference_images(prompts, [str(tmp_dir)], "by_name")
    assert [Path(p).name for p in byname_res[0]] == ["anh_so_1.png", "anh_so_2.jpg"]
    assert [Path(p).name for p in byname_res[1]] == ["anh_so_2.jpg"]
    assert byname_res[2] == []

    # 3. Kiểm tra API Endpoints
    client = TestClient(app)
    st = client.get("/api/state").json()
    assert "projects" in st and len(st["projects"]) >= 1
    proj_id = st["active_project_id"]

    # Tạo task mới
    create_res = client.post(
        "/api/tasks/create",
        json={
            "project_id": proj_id,
            "prompts": prompts,
            "task_type": "video",
            "aspect_ratio": "16:9",
            "ref_mode": "by_name",
            "image_paths": [str(tmp_dir)],
            "auto_start": False,
        },
    ).json()
    assert create_res["ok"] is True
    assert create_res["created_count"] == 3
    task_ids = create_res.get("task_ids", [])

    # Kiểm tra chỉnh sửa Prompt của Task (Upgrade #7)
    if task_ids:
        edit_res = client.put(
            f"/api/tasks/{task_ids[0]}/prompt",
            json={"prompt_text": "Prompt đã được chỉnh sửa mới"},
        ).json()
        assert edit_res["ok"] is True

    # Thêm tài khoản bulk email|pass|proxy
    acc_res = client.post(
        "/api/accounts/add",
        json={
            "bulk_text": "demo1@gmail.com|pass123|127.0.0.1:8080:user:pass\ndemo2@gmail.com|pass456",
            "image_threads": 5,
            "video_threads": 5,
        },
    ).json()
    assert acc_res["ok"] is True

    # Dọn dẹp dữ liệu test để không ảnh hưởng DB thực tế của người dùng
    from backend.database import get_connection
    conn = get_connection()
    if task_ids:
        placeholders = ",".join("?" for _ in task_ids)
        conn.execute(f"DELETE FROM tasks WHERE id IN ({placeholders})", task_ids)
    conn.execute("DELETE FROM tasks WHERE prompt_text IN (?, ?, ?)", tuple(prompts))
    conn.execute("DELETE FROM accounts WHERE email IN ('demo1@gmail.com', 'demo2@gmail.com')")
    conn.execute("DELETE FROM proxies WHERE raw_string LIKE '127.0.0.1:8080%'")
    conn.commit()
    conn.close()

    print("ALL CORE TESTS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    test_all()
