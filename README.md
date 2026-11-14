# 🎬 Video Creation App

Ứng dụng tạo video tự động từ nội dung text/CSV với Streamlit, MoviePy và Edge TTS.

## ✨ Tính năng chính

- **🎓 Video bài học song ngữ (mới)** — Từ 1 file Lesson JSON tạo video 4 phần: hội thoại song ngữ Anh–Việt (tô màu từ vựng) → 10 thẻ từ vựng (IPA, nghĩa, câu gốc) → bài tập tự nhớ (đếm ngược + đáp án) → ôn tập. Xuất kèm phụ đề EN/VI, thumbnail, manifest. Xem [docs/03](docs/03-phase-0-1-implementation.md)
- **🎞️ Video phân cảnh (mới)** — Upload 1 file JSON kịch bản chia theo phân cảnh, app hiện đúng số ô upload hình tương ứng (mỗi phân cảnh 1 hình). Review từng cảnh, chỉnh vị trí bubble chat và hướng mũi tên cho từng nhân vật; trong video mỗi lượt chỉ hiện bubble của người đang nói (tiếng Anh + tiếng Việt) rồi chuyển sang người tiếp theo. Xuất kèm phụ đề EN/VI, thumbnail; tải lại được JSON kèm bố cục bubble. Định dạng: file lesson theo phân cảnh (`lesson_id`, `meta`, `characters`, `scenes[].dialogue`…) — mẫu: `samples/scenes/job-interviews-b1.json`; mỗi ô upload kèm `setting_en` và `image_prompt` của cảnh
- **Video hội thoại 2 người** — Upload CSV với 2 speaker, tự động tạo video với bubble chat hoặc plain text, hiệu ứng bong bóng tail, per-speaker voice selection
- **Video từ vựng (Flashcard)** — Upload CSV từ vựng (english/ipa/vietnam/example/translate), tạo video flashcard
- **🔗 Ghép video** — Upload nhiều video, sắp xếp thứ tự, ghép thành 1 video (tự co giãn khác kích thước/FPS, bù im lặng cho clip không có tiếng); tùy chọn chèn logo ở giữa phía dưới (logo kênh mặc định hoặc upload, chỉnh kích thước/độ đậm/khoảng cách đáy)
- **🕸️ Crawl video kênh** — Nhập link kênh YouTube / TikTok (hoặc link từng video Facebook), lấy danh sách video kèm metadata (tiêu đề, mô tả, tag, ngày đăng, thời lượng, lượt xem/thích/bình luận, thumbnail…) và xuất CSV. Chỉ đọc metadata công khai qua `yt-dlp`, không tải video. Facebook: yt-dlp không liệt kê được toàn bộ video của một trang, chỉ hỗ trợ link từng video/reel
- **Text-to-Speech** — Hỗ trợ Edge TTS (13 giọng en-US nam/nữ) và gTTS
- **Tùy chỉnh hiển thị** — Font size, font color, padding top, bubble chat toggle, live preview trước khi tạo
- **Hình nền linh hoạt** — Màu đơn sắc, upload hình ảnh, hoặc chọn từ thư viện `assets/`
- **Dashboard** — Thống kê, hoạt động gần đây, biểu đồ 7 ngày
- **Quản lý video** — Lọc, sắp xếp, xem/tải lại, xóa (cả file), export CSV — lịch sử lưu bền vững trong SQLite

## 📁 Cấu trúc dự án

```
video-creation-app/
├── app.py                  # Entrypoint — Streamlit page config, routing
├── config.py               # Cấu hình trung tâm (fonts, resolutions, TTS, CSV types)
├── requirements.txt        # Dependencies
├── assets/
│   └── fonts/              # Font files (.ttf) — auto-discovered
├── core/                   # Backend (không phụ thuộc Streamlit)
│   ├── state.py            # API lịch sử video (ủy quyền cho storage)
│   ├── storage.py          # SQLite (data/app.db)
│   ├── utils.py            # Tên file an toàn, codec, MIME, IPA…
│   ├── tts_service.py      # gTTS + Edge TTS wrapper, cache + retry
│   ├── video_service.py    # CSV parsing, detect, business helpers
│   ├── video_join.py       # Ghép video + logo (ffmpeg 1 lượt)
│   ├── channel_crawler.py  # Crawl danh sách video kênh (yt-dlp) → CSV
│   ├── lesson/             # Lesson JSON: schema, validators, importers
│   ├── scene_video/        # Video phân cảnh: schema Story JSON + vẽ bubble/mũi tên + render
│   ├── render/             # Dựng video bài học bằng Pillow + MoviePy
│   │   └── segments/       # intro, dialogue, vocab, exercise, outro
│   └── generators/
│       ├── __init__.py     # Dispatcher theo CSV type
│       ├── dialogue.py     # Generator video hội thoại 2 người
│       └── vocabulary.py   # Generator video flashcard từ vựng
├── ui/                     # Frontend (Streamlit UI)
│   ├── router.py           # Route registry, sidebar mapping
│   ├── styles.py           # Global CSS / theme tokens
│   ├── components/
│   │   ├── sidebar.py      # Sidebar navigation
│   │   ├── page_header.py  # Reusable page header
│   │   ├── video_card.py   # Video item card
│   │   └── csv_preview.py  # CSV preview, auto-detect, sample format
│   └── views/
│       ├── dashboard.py    # Dashboard — metrics, chart, recent activity
│       ├── lesson_video.py # Trang tạo video bài học song ngữ
│       ├── scene_video.py     # Trang video phân cảnh (JSON + hình từng cảnh, chỉnh bubble)
│       ├── dialogue_video.py  # Trang tạo video hội thoại (dedicated)
│       ├── join_video.py      # Trang ghép video + logo
│       ├── crawl_channel.py   # Trang crawl video kênh + xuất CSV
│       ├── create_video.py    # Trang tạo video chung (text/txt/csv)
│       └── manage_videos.py   # Quản lý video — filter, delete, export
├── samples/lessons/        # Lesson JSON mẫu
├── tests/                  # pytest
├── docs/                   # Tài liệu hệ thống, đề xuất, ghi chú triển khai
├── data/                   # app.db, tts_cache/ (không commit)
└── output/                 # Video output (không commit)
```

## 🚀 Cài đặt & Chạy

### Yêu cầu

- Python 3.10+
- Không cần cài FFmpeg riêng (MoviePy 2 dùng bản đi kèm `imageio-ffmpeg`)
- Kết nối Internet cho Edge TTS (giọng đọc được cache trong `data/tts_cache/`)

### Cài đặt

```bash
cd video-creation-app
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
```

### Font (bắt buộc cho tiếng Việt & IPA)

Hai font **Arial Unicode** và **Arial Rounded Bold** có bản quyền thương mại nên **không được commit**
(đã nằm trong `.gitignore`). Sao chép thủ công vào `assets/fonts/`:

```bash
cp "/path/to/Arial Unicode.ttf" "assets/fonts/Arial Unicode.ttf"
```

Có thể dùng bất kỳ font `.ttf/.otf` nào hỗ trợ đủ tiếng Việt và ký tự IPA (vd. font OFL như Noto Sans).
App tự phát hiện font trong `assets/fonts/`; trang Video Bài Học sẽ báo lỗi nếu font thiếu ký tự.
Repo chỉ kèm `BungeeOutline-Regular.ttf` (SIL OFL).

### Chạy

```bash
.venv/bin/streamlit run app.py
```

Mở trình duyệt tại `http://localhost:8501`

### Dựng video từ dòng lệnh

```bash
.venv/bin/python -m core.render samples/lessons/hotel-checkout-a2.json          # dựng video
.venv/bin/python -m core.render samples/lessons/hotel-checkin-a2.json --check   # chỉ kiểm tra
```

Hướng dẫn vận hành đầy đủ: **[docs/RUNBOOK.md](docs/RUNBOOK.md)**

### Test

```bash
.venv/bin/python -m pytest -q
```

## 📦 Dependencies

| Package | Mục đích |
|---------|----------|
| `streamlit` >= 1.30.0 | UI framework |
| `pandas` >= 2.0.0 | CSV parsing |
| `moviepy` >= 2.0, < 3 | Video composition & export |
| `numpy` | Trộn âm thanh, frame |
| `pydantic` >= 2.5 | Schema Lesson JSON |
| `Pillow` >= 10.0.0 | Image processing (bubble, circle tail) |
| `edge-tts` >= 7.0.0 | Microsoft Edge TTS (primary) |
| `gTTS` >= 2.3.0 | Google TTS (fallback) |

## 📝 Định dạng CSV

### Dialogue (Hội thoại 2 người)

Separator: `;`

```csv
speaker 1;speaker 2
I couldn't sleep well last night.;The bedroom was definitely too hot.
I am so exhausted this morning.;Did you stay up late on your phone again?
Maybe it was that late afternoon coffee.;
```

### Vocabulary (Từ vựng)

Separator: `;`

```csv
english;ipa;vietnam;example;translate
abandon;/əˈbændən/;từ bỏ;They had to abandon the project.;Họ phải từ bỏ dự án.
```

## 🎙️ TTS Engines

- **Edge TTS** (mặc định) — 13 giọng en-US (nam & nữ), chọn riêng cho từng speaker
- **gTTS** — Google TTS, hỗ trợ nhiều ngôn ngữ (vi, en, ja, zh, ko)

## 🎨 Video Options

- **Độ phân giải**: 16:9 (1920×1080), 9:16 (1080×1920)
- **FPS**: 15–60 (mặc định 30)
- **Định dạng**: MP4, AVI, MOV, WEBM
- **Font**: Auto-discover từ `assets/fonts/`
- **Bubble chat**: Toggle on/off, với hiệu ứng 3 bong bóng tail
- **Padding top**: Điều chỉnh vị trí text/bubble (0–80%)
