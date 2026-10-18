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


def wrap_prompt(
    raw_prompt: str,
    task_type: str,
    aspect_ratio: str,
    has_ref_images: bool,
    settings: Dict[str, str],
) -> str:
    """
    Bộ bọc Prompt (Prompt Template Wrapper) theo 4 mẫu cấu hình trong Cài đặt:
    - Text-to-Image
    - Image-to-Image (Có ảnh tham chiếu)
    - Text-to-Video
    - Image-to-Video (Từ ảnh sang video)
    """
    prompt_clean = raw_prompt.strip()
    ratio = aspect_ratio.strip() if aspect_ratio else "16:9"
    count = settings.get("default_image_count", "1") or "1"
    t_type = (task_type or "video").lower().strip()

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
