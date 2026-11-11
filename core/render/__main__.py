"""Command-line entry point: validate and render a lesson video.

Usage examples::

    python -m core.render samples/lessons/hotel-checkin-a2.json
    python -m core.render lesson.json --check            # validate only
    python -m core.render lesson.json --landscape --example-repeat 1
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time

from config import DEFAULT_LOGO, LESSON_OUTPUT_DIR, VIDEO_RESOLUTIONS
from core.lesson import LessonLoadError, has_errors, load_lesson_file, validate_lesson
from core.render.config import RenderConfig

_STAGE_VI = {"tts": "Giọng đọc", "frames": "Khung hình", "audio": "Âm thanh", "encode": "Encode"}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m core.render",
        description="Kiểm tra và dựng video bài học từ một file Lesson JSON.",
    )
    p.add_argument("lesson", help="Đường dẫn file Lesson JSON (ảnh minh hoạ đặt cùng thư mục)")
    p.add_argument("--check", action="store_true", help="Chỉ kiểm tra, không dựng video")
    p.add_argument("--landscape", action="store_true", help="Video ngang 16:9 (mặc định dọc 9:16)")
    p.add_argument("--layout", choices=["fullscreen", "panel"], default="fullscreen",
                   help="Video dọc: ảnh toàn màn hình 9:16 hoặc khung phía trên (mặc định fullscreen)")
    p.add_argument("--word-repeat", type=int, default=2, metavar="N", help="Số lần đọc từ vựng (1–4, mặc định 2)")
    p.add_argument("--example-repeat", type=int, default=2, metavar="N",
                   help="Số lần đọc câu ví dụ (1–4, mặc định 2)")
    p.add_argument("--no-example-vi", action="store_true", help="Không đọc bản dịch tiếng Việt của câu ví dụ")
    p.add_argument("--no-vi", action="store_true", help="Tắt giọng đọc tiếng Việt (tiêu đề, nghĩa, giải thích)")
    p.add_argument("--think", type=int, default=0, metavar="SEC",
                   help="Thời gian suy nghĩ mỗi bài tập (0 = theo file)")
    p.add_argument("--fps", type=int, default=30, choices=[24, 25, 30])
    p.add_argument("--no-logo", action="store_true", help="Không chèn logo kênh")
    p.add_argument("--logo", metavar="PNG", help="Logo khác (PNG nền trong suốt); mặc định assets/brand/daily-dialogues-logo.png")
    p.add_argument("--logo-opacity", type=float, default=0.35, metavar="0-1", help="Độ hiển thị logo (mặc định 0.35)")
    p.add_argument("--name", help="Tên file video (mặc định: title_en)")
    p.add_argument("--output-root", default=LESSON_OUTPUT_DIR, help="Thư mục gốc chứa kết quả")
    return p


def config_from_args(args: argparse.Namespace) -> RenderConfig:
    for flag in ("word_repeat", "example_repeat"):
        if not 1 <= getattr(args, flag) <= 4:
            raise SystemExit(f"--{flag.replace('_', '-')} phải trong khoảng 1–4")
    size = VIDEO_RESOLUTIONS["16:9 (1920x1080)"] if args.landscape else VIDEO_RESOLUTIONS["9:16 (1080x1920)"]
    if not 0 <= args.logo_opacity <= 1:
        raise SystemExit("--logo-opacity phải trong khoảng 0–1")
    if args.logo and not os.path.isfile(args.logo):
        raise SystemExit(f"Không tìm thấy logo: {args.logo}")
    logo = None if args.no_logo else (args.logo or DEFAULT_LOGO)
    return RenderConfig(
        size=size,
        fps=args.fps,
        scene_layout=args.layout,
        word_repeat=args.word_repeat,
        example_repeat=args.example_repeat,
        read_example_vi=not args.no_example_vi,
        vi_narration=not args.no_vi,
        think_seconds=args.think or None,
        logo_path=logo,
        logo_opacity=args.logo_opacity,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.ERROR, format="%(levelname)s %(message)s")

    try:
        lesson = load_lesson_file(args.lesson)
    except FileNotFoundError:
        print(f"❌ Không tìm thấy file: {args.lesson}")
        return 2
    except LessonLoadError as exc:
        print("❌ File bài học không hợp lệ:")
        for e in exc.errors:
            print(f"   - {e}")
        return 2

    issues = validate_lesson(lesson)
    print(f"📘 {lesson.meta.title_en} — {lesson.meta.title_vi} "
          f"({len(lesson.dialogue)} lượt thoại, {len(lesson.vocabulary)} từ, {len(lesson.exercises)} bài tập)")
    for i in issues:
        print(f"   {'❌' if i.severity == 'error' else '⚠️ '} {i.path}: {i.message}")
    if has_errors(issues):
        print("❌ Có lỗi – sửa trước khi dựng video.")
        return 1
    print("✅ Kiểm tra đạt." + (f" ({len(issues)} cảnh báo cần người duyệt xem lại)" if issues else ""))
    if args.check:
        return 0

    from core.render.assemble import render_lesson_video  # heavy imports only when rendering

    started = time.monotonic()
    last: dict[str, int] = {}

    def progress(stage: str, done: int, total: int) -> None:
        pct = int(100 * done / max(1, total))
        if pct // 10 != last.get(stage, -1) or done == total:
            last[stage] = pct // 10
            print(f"   [{time.monotonic() - started:6.1f}s] {_STAGE_VI.get(stage, stage):<10} {done}/{total} ({pct}%)",
                  flush=True)

    result = render_lesson_video(lesson, config_from_args(args), video_name=args.name,
                                 output_root=args.output_root, progress_cb=progress)
    m, s = divmod(int(result.duration), 60)
    print(f"🎬 Video: {result.video_path}")
    print(f"   Thời lượng {m}:{s:02d} · dựng trong {time.monotonic() - started:.0f}s · thư mục: {result.lesson_dir}")
    if result.tts_fallbacks:
        print(f"⚠️  {len(result.tts_fallbacks)} câu dùng giọng dự phòng gTTS – xem manifest.json, cân nhắc dựng lại.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
