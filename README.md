# Muse Studio (AI Media & Video Automation)

Ứng dụng tự động hóa tạo ảnh và video 10 giây trên nền tảng **Meta Muse.ai** (`https://muse.ai/`) với kiến trúc **Playwright Persistent User Profile + Multi-Tab Context (2-Tier Concurrency)**, bộ xử lý ghép ảnh tham chiếu 3 chế độ và giao diện **Dark Mode 5 Tabs** (`#0B0D14` & `#6366F1`).

## Cấu trúc Thư mục Dự án

```text
Muse Studio/
├── app.py                      # Điểm khởi chạy chính (FastAPI Server + PyWebView Desktop UI)
├── requirements.txt            # Danh sách thư viện Python
├── run.bat                     # Script cài đặt & khởi chạy nhanh trên Windows
├── backend/
│   ├── __init__.py
│   ├── database.py             # SQLite3 Schema (projects, accounts, proxies, tasks, settings)
│   ├── matcher.py              # Bộ xử lý ghép ảnh tham chiếu (Ghép cặp, Dùng chung, Theo tên prompt) & Prompt Wrapper
│   ├── playwright_engine.py    # Playwright Persistent Profile, Interactive OTP Login, Off-screen Mode, Auto-Approve & Media Sniffer
│   └── orchestrator.py         # Bộ điều phối đa luồng 2 tầng (Multi-Account x Multi-Tab Queue Engine)
├── frontend/
│   ├── index.html              # Giao diện Dark Mode 5 Tabs (Studio, Thư viện, Tài khoản, Proxy, Cài đặt)
│   ├── css/
│   │   └── styles.css          # Tùy biến giao diện Dark Mode (#0B0D14) & Indigo/Violet (#6366F1)
│   └── js/
│       └── app.js              # Logic điều khiển Frontend, Polling tiến độ & Modal Video Player
├── tests/
│   └── test_core.py            # Bộ kiểm thử tự động Database, Matcher, Prompt Wrapper & API
├── .muse/                      # Tự động khởi tạo: chứa muse_studio.db và profiles/acc_{id}
└── output/                     # Thư mục xuất kết quả theo dự án: /output/{project_name}/{task_name}.mp4
```

## Cách Khởi Chạy

1. **Cách 1 (Khuyên dùng trên Windows):** Chạy trực tiếp file `run.bat`.
2. **Cách 2 (Chạy thủ công qua Terminal):**
   ```powershell
   pip install -r requirements.txt
   playwright install chromium
   python app.py
   ```
   *(Nếu muốn mở trực tiếp trên trình duyệt web thay vì cửa sổ PyWebView, chạy `python app.py --browser`)*
