import os
import re
from pathlib import Path
from typing import Dict, List, Tuple

ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def collect_images_from_paths(paths: List[str]) -> List[str]:
    """
    Nhận danh sách đường dẫn (có thể là file ảnh lẻ hoặc thư mục)
    và trả về danh sách đường dẫn file ảnh hợp lệ đã được sắp xếp tự nhiên (natural sort).
    """
    collected: List[str] = []
    seen = set()

    def natural_key(text: str):
        return [int(c) if c.isdigit() else c.lower() for c in re.split(r"(\d+)", text)]

    for raw_path in paths:
        if not raw_path:
            continue
        p = Path(raw_path)
        if not p.exists():
            continue
        if p.is_file():
            if p.suffix.lower() in ALLOWED_IMAGE_EXTENSIONS:
                resolved = str(p.resolve())
                if resolved not in seen:
                    seen.add(resolved)
                    collected.append(resolved)
        elif p.is_dir():
            files_in_dir = []
            for child in p.iterdir():
                if child.is_file() and child.suffix.lower() in ALLOWED_IMAGE_EXTENSIONS:
                    files_in_dir.append(child)
            files_in_dir.sort(key=lambda x: natural_key(x.name))
            for f in files_in_dir:
                resolved = str(f.resolve())
                if resolved not in seen:
                    seen.add(resolved)
                    collected.append(resolved)

    return collected


def match_reference_images(
    prompts: List[str],
    image_paths: List[str],
    ref_mode: str = "pair",
) -> List[List[str]]:
    """
    Thực hiện ghép ảnh tham chiếu cho danh sách prompts theo 3 chế độ:
    1. 'pair' (Ghép cặp 1-1 Index Matching):
       Prompt dòng thứ i (0-indexed) tự động đính kèm file ảnh thứ i trong danh sách.
    2. 'shared' (Dùng chung - Shared Reference):
       Toàn bộ các prompt đều đính kèm chung danh sách file ảnh đã chọn.
    3. 'by_name' (Theo tên prompt - Smart Filename Matching):
       Quét toàn bộ tên file (stem không tính đuôi mở rộng .png, .jpg, .jpeg, .webp)
       trong danh sách/thư mục ảnh tham chiếu đã chọn.
       Kiểm tra nội dung chuỗi văn bản của từng prompt (không phân biệt hoa thường):
       Nếu trong prompt có xuất hiện tên của file ảnh nào, tự động lấy tất cả các ảnh khớp.
    """
    valid_images = collect_images_from_paths(image_paths)
    results: List[List[str]] = []

    if not valid_images:
        return [[] for _ in prompts]

    mode = (ref_mode or "pair").lower().strip()

    if mode == "pair":
        for idx, _ in enumerate(prompts):
            if idx < len(valid_images):
                results.append([valid_images[idx]])
            else:
                results.append([])

    elif mode == "shared":
        for _ in prompts:
            results.append(list(valid_images))

    elif mode == "by_name":
        # Chuẩn bị danh sách (stem_lower, full_path, pos_in_prompt)
        # Sắp xếp stem dài trước để tránh trường hợp tên ngắn là tập con của tên dài nếu cần,
        # nhưng ở đây ta kiểm tra độc lập và sắp xếp kết quả theo vị trí xuất hiện trong prompt.
        stem_entries: List[Tuple[str, str]] = []
        for img_path in valid_images:
            stem = Path(img_path).stem.strip()
            if stem:
                stem_entries.append((stem.lower(), img_path))

        for prompt_text in prompts:
            prompt_lower = prompt_text.lower()
            matched_with_pos: List[Tuple[int, str]] = []
            seen_paths = set()

            for stem_lower, full_path in stem_entries:
                # Tìm kiếm tên file (không phân biệt hoa thường)
                # Sử dụng boundary linh hoạt để khớp chính xác cụm tên file như anh_so_1, charA, v.v.
                pattern = r"(?<![a-z0-9_])" + re.escape(stem_lower) + r"(?![a-z0-9_])"
                match = re.search(pattern, prompt_lower)
                if not match and stem_lower in prompt_lower:
                    # Fallback substring match nếu tên file có ký tự đặc biệt hoặc viết dính
                    pos = prompt_lower.find(stem_lower)
                    if pos != -1 and full_path not in seen_paths:
                        seen_paths.add(full_path)
                        matched_with_pos.append((pos, full_path))
                elif match and full_path not in seen_paths:
                    seen_paths.add(full_path)
                    matched_with_pos.append((match.start(), full_path))

            # Sắp xếp ảnh theo thứ tự xuất hiện trong câu prompt
            matched_with_pos.sort(key=lambda x: x[0])
            results.append([p for _, p in matched_with_pos])

    else:
        for _ in prompts:
            results.append([])

    return results


def filter_prompt_for_chain_clip(
    raw_prompt: str, chain_index: int, clip_duration: int = 10
) -> str:
    """
    Khi người dùng nhập kịch bản dài (VD: 30s có chia mốc 0–3s, 3–6s, 6–9s, 9–15s, 15–20s, 20–25s, 25–30s),
    hàm này tự động lọc để mỗi phân cảnh Clip #i (VD: Clip 3 = 20s–30s) CHỈ giữ lại đúng các mốc thời gian
    thuộc khung [win_start, win_end] của Clip đó cùng phần mô tả bối cảnh/nhân vật chung.
    Nhờ vậy Clip #3 (20s–30s) không bị lặp lại mệnh lệnh tấn công/va chạm của giây 0–15s gây xung đột với ảnh frame cuối của Clip #2.
    Đồng thời loại bỏ các từ khóa nhạy cảm trong Negative Prompt (blood, gore, injuries) dễ làm bộ lọc Image-to-Video của Muse từ chối.
    """
    if not raw_prompt or chain_index <= 0:
        return raw_prompt

    win_start = (chain_index - 1) * clip_duration
    win_end = chain_index * clip_duration

    # Tách theo dấu phân cách đoạn ' — ' hoặc xuống dòng
    parts = re.split(r"\s+—\s+|\r?\n", raw_prompt)
    time_header_re = re.compile(
        r"(?:^|\b)(?:#+\s*|\*\*\s*)?(?<!/)(\d{1,3})\s*(?:–|—|-|to)\s*(\d{1,3})\s*(?:seconds?|secs?)\b",
        re.IGNORECASE,
    )
    major_section_re = re.compile(
        r"^(?:#+\s*\d+\.|#+\s*[A-Z]|\*\*(?:CAMERA|PHYSICS|AUDIO|NATURAL|REALISTIC|FINAL|SCENE|ENVIRONMENT|NEGATIVE)|Negative\s+Prompt|\([A-Z][a-z]+\s+)",
        re.IGNORECASE,
    )
    # Các mục tóm tắt toàn bộ 30s (chứa mệnh lệnh tấn công/đá hậu của giây 0-15s) cần lược bỏ ở Clip #2, #3+ để không xung đột với frame cuối
    global_summary_section_re = re.compile(
        r"^(?:#+\s*[78]\.\s*(?:CRITICAL\s+MOTION|FINAL\s+QUALITY)|\*\*FINAL\s+OBJECTIVE|\*\*Camera\s+geography)",
        re.IGNORECASE,
    )
    resume_section_re = re.compile(
        r"^(?:#+\s*[23456]\.|Negative\s+Prompt|\([A-Z][a-z]+\s+)",
        re.IGNORECASE,
    )

    has_any_time_block = any(time_header_re.search(p) for p in parts)
    filtered_parts: List[str] = []
    in_time_block = False
    keep_current_time_block = True
    in_skipped_summary = False

    if has_any_time_block:
        for p in parts:
            p_strip = p.strip()
            if not p_strip:
                continue

            if chain_index >= 2 and global_summary_section_re.search(p_strip):
                in_skipped_summary = True
                in_time_block = False
                continue

            if in_skipped_summary:
                if time_header_re.search(p_strip) or resume_section_re.search(p_strip):
                    in_skipped_summary = False
                else:
                    continue

            m_time = time_header_re.search(p_strip)
            if m_time:
                t0 = int(m_time.group(1))
                t1 = int(m_time.group(2))
                if t1 > t0 and t1 <= 180:
                    in_time_block = True
                    # Giữ lại mốc thời gian nếu giao nhau với cửa sổ [win_start, win_end] của Clip này
                    keep_current_time_block = (t0 < win_end) and (t1 > win_start)
                    if keep_current_time_block:
                        filtered_parts.append(p_strip)
                    continue

            if in_time_block and major_section_re.search(p_strip):
                in_time_block = False
                keep_current_time_block = True

            if not in_time_block or keep_current_time_block:
                filtered_parts.append(p_strip)
    else:
        filtered_parts = [p.strip() for p in parts if p.strip()]

    result = " — ".join(filtered_parts)

    # Đổi 'Create a 30-second' thành 'Create a 10-second' để Muse không cố nhồi toàn bộ 30s vào 1 clip 10s
    result = re.sub(
        r"\bCreate\s+a\s+\d{2,3}-second\b",
        f"Create a 10-second (segment {win_start}s-{win_end}s)",
        result,
        flags=re.IGNORECASE,
    )
    result = re.sub(
        r"\bCOMPLETE\s+\d{2,3}-SECOND\s+ACTION\s+SEQUENCE\b",
        f"ACTION SEQUENCE FOR SEGMENT {win_start}s–{win_end}s",
        result,
        flags=re.IGNORECASE,
    )

    # Làm sạch các từ khóa nhạy cảm trong Negative Prompt dễ kích hoạt bộ lọc an toàn Image-to-Video của Muse
    result = re.sub(
        r"\b(?:animal\s+injuries|injuries|blood|gore|violent|violence)\s*,?\s*",
        "",
        result,
        flags=re.IGNORECASE,
    )
    return result


def wrap_prompt(
    raw_prompt: str,
    task_type: str,
    aspect_ratio: str,
    has_ref_images: bool,
    settings: Dict[str, str],
    character_lock_text: str = "",
    chain_group_id: str = "",
    chain_index: int = 0,
) -> str:
    """
    Bộ bọc Prompt (Prompt Template Wrapper) theo 4 mẫu cấu hình trong Cài đặt:
    - Text-to-Image
    - Image-to-Image (Có ảnh tham chiếu)
    - Text-to-Video
    - Image-to-Video (Từ ảnh sang video)
    Kết hợp khóa Đồng bộ Nhân vật (Character Consistency Lock) & Chuỗi Video Dài (Multi-Clip Continuity).
    """
    prompt_clean = raw_prompt.strip()
    if chain_group_id and chain_index > 0 and (task_type or "video").lower().strip() != "image":
        prompt_clean = filter_prompt_for_chain_clip(prompt_clean, chain_index)
    ratio = aspect_ratio.strip() if aspect_ratio else "16:9"
    count = settings.get("default_image_count", "1") or "1"
    t_type = (task_type or "video").lower().strip()

    extra_directives: List[str] = []
    char_lock = (character_lock_text or "").strip()
    if char_lock:
        extra_directives.append(
            f"[CHARACTER CONSISTENCY LOCK — Keep exact facial identity, hairstyle, and outfit 100% unchanged across all clips: {char_lock}]."
        )
    elif has_ref_images:
        extra_directives.append(
            "[CHARACTER CONSISTENCY LOCK — Strictly preserve the exact facial features, hair, and outfit from the attached reference image(s)]."
        )

    if chain_group_id and t_type != "image":
        if chain_index > 1:
            extra_directives.append(
                f"[SEAMLESS CONTINUATION CLIP #{chain_index}: Use the attached last-frame image from the previous clip as the exact starting frame and pose, while keeping the character identity locked. Continue the action smoothly, and cut mid-motion at the end. AUDIO: natural ambient sound effects only, strictly NO background music and NO voiceover]."
            )
        else:
            extra_directives.append(
                "[MULTI-CLIP SEQUENCE CLIP #1: End this 10s clip mid-motion (walking, turning, or camera pan — do NOT end on a static pose) for seamless stitching. AUDIO: natural ambient sound effects only, strictly NO background music and NO voiceover]."
            )

    if extra_directives:
        prompt_clean = f"{' '.join(extra_directives)} Scene action: {prompt_clean}"

    if t_type == "image":
        if has_ref_images:
            tpl = settings.get(
                "tpl_image_to_image",
                "Create {count} image(s) with aspect ratio {ratio}, using the attached image(s) as reference (keep the subject, face and style). Do not ask follow-up questions, just generate. {prompt}",
            )
        else:
            tpl = settings.get(
                "tpl_text_to_image",
                "Create {count} image(s) with aspect ratio {ratio}. Do not ask follow-up questions, just generate the image(s) directly. {prompt}",
            )
    elif t_type == "img2vid":
        tpl = settings.get(
            "tpl_image_to_video",
            "Create a video with aspect ratio {ratio} from the attached image (image-to-video). Do not ask follow-up questions, just generate the video directly. {prompt}",
        )
    else:
        # task_type == 'video'
        if has_ref_images:
            tpl = settings.get(
                "tpl_image_to_video",
                "Create a video with aspect ratio {ratio} from the attached image (image-to-video). Do not ask follow-up questions, just generate the video directly. {prompt}",
            )
        else:
            tpl = settings.get(
                "tpl_text_to_video",
                "Create a video with aspect ratio {ratio}. Do not ask follow-up questions, just generate the video directly. {prompt}",
            )

    try:
        return tpl.format(count=count, ratio=ratio, prompt=prompt_clean)
    except Exception:
        # Phòng trường hợp người dùng sửa template sai cú pháp ngoặc nhọn
        return (
            tpl.replace("{count}", str(count))
            .replace("{ratio}", str(ratio))
            .replace("{prompt}", prompt_clean)
        )
