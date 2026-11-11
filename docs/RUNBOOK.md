# RUNBOOK — Tạo video bài học hội thoại song ngữ

Hướng dẫn vận hành từng bước: cần chuẩn bị gì, chạy lệnh nào, kết quả nằm ở đâu, gặp lỗi thì xử lý ra sao.
Tài liệu chi tiết hơn: [01 hệ thống](01-system-documentation.md) · [02 đề xuất](02-upgrade-proposal.md) · [03 triển khai](03-phase-0-1-implementation.md).

---

## 1. Chuẩn bị (một lần cho mỗi máy)

| Hạng mục | Yêu cầu | Ghi chú |
|---|---|---|
| Python | 3.10 trở lên (đã kiểm thử với 3.12) | `python3 --version` |
| FFmpeg | Không cần cài riêng | Đi kèm thư viện `imageio-ffmpeg` |
| Font | `assets/fonts/Arial Unicode.ttf`, hoặc font khác có đủ chữ tiếng Việt và ký tự IPA | Font này có bản quyền nên **không có trong git**; phải tự chép vào |
| Internet | Bắt buộc khi dựng video | Edge TTS tạo giọng đọc; câu đã tạo được lưu trong `data/tts_cache/` |
| Git (nếu commit) | `user.name`, `user.email` | `git config user.name "…"` và `git config user.email "…"` |

```bash
cd /Users/teku.tran/Documents/000-Projects/video-creation-app
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp "/đường/dẫn/Arial Unicode.ttf" "assets/fonts/Arial Unicode.ttf"   # nếu chưa có
.venv/bin/python -m pytest -q                                        # kỳ vọng: tất cả passed
```

---

## 2. Chuẩn bị nội dung cho mỗi bài

1. **File Lesson JSON**: copy một bài trong `samples/lessons/` rồi sửa. Yêu cầu:
   - 2 nhân vật; nhân vật thứ nhất là người **đứng bên trái** ảnh.
   - 8–14 lượt thoại, mỗi lượt có câu `en` và bản dịch `vi`.
   - **Đúng 10** từ vựng. `dialogue_idx` là số thứ tự lượt thoại chứa từ đó, **đếm từ 0**.
   - Khoảng 5 bài tập thuộc các loại `multiple_choice` / `fill_blank` (chỗ trống ghi `____`) / `translate_vi_en` / `comprehension`.
   - Thuật ngữ tiếng Anh nằm giữa câu tiếng Việt thì **đặt trong ngoặc kép** để được đọc bằng giọng Anh.
2. **Ảnh minh hoạ** (tuỳ chọn nhưng nên có):
   - Ảnh dọc **9:16**. Mặt nhân vật ở **nửa trên**, nửa dưới để trống tương đối vì bong bóng chat nằm ở đó.
   - Đặt ảnh **cùng thư mục** với file JSON và khai báo `"scene_image": "<tên-file>.png"` trong `meta`.
   - Nếu mặt nhân vật bị cắt, chỉnh `"scene_focus_y"`: 0 giữ phần trên, 1 giữ phần dưới.
   - Ví dụ prompt tạo ảnh: `samples/lessons/hotel-checkin.prompt.txt`.
3. **Duyệt nội dung**: nhờ giáo viên hoặc biên tập viên đọc lại bản dịch, IPA và bài tập. App chỉ kiểm tra cấu trúc, không kiểm tra được chất lượng ngôn ngữ.

---

## 3. Cách A — Giao diện web

```bash
.venv/bin/streamlit run app.py        # mở http://localhost:8501 ; dừng bằng Ctrl+C
```
Vào trang **🎓 Video Bài Học**:
1. Chọn **Bài mẫu có sẵn**, hoặc **Upload file JSON**. Nếu JSON có khai báo ảnh thì upload kèm ảnh.
2. Xem kết quả kiểm tra. Lỗi đỏ phải sửa xong mới dựng được; cảnh báo vàng thì người duyệt xem lại.
3. Chọn giọng nhân vật, giọng người dẫn, 2 giọng đọc từ vựng, số lần đọc, kiểu hiển thị ảnh.
4. Bấm **🖼️ Tạo ảnh xem trước** để kiểm tra bố cục.
5. Bấm **🚀 Tạo Video Bài Học** (khoảng 1–3 phút). **Đừng đóng tab** trong lúc dựng.
6. Tải MP4, phụ đề EN/VI, thumbnail. Mở **🔊 Kịch bản giọng đọc** để kiểm tra phần nào đọc giọng Anh, phần nào giọng Việt.

---

## 4. Cách B — Dòng lệnh

```bash
# Chỉ kiểm tra (không dựng video)
.venv/bin/python -m core.render samples/lessons/hotel-checkin-a2.json --check

# Dựng video dọc 9:16 với cấu hình mặc định
.venv/bin/python -m core.render samples/lessons/hotel-checkout-a2.json

# Video ngắn hơn: đọc câu ví dụ 1 lần
.venv/bin/python -m core.render samples/lessons/laundry-a2.json --example-repeat 1

# Video ngang 16:9
.venv/bin/python -m core.render samples/lessons/hotel-checkout-a2.json --landscape

# Xem toàn bộ tuỳ chọn
.venv/bin/python -m core.render --help
```

| Tuỳ chọn | Ý nghĩa | Mặc định |
|---|---|---|
| `--check` | Chỉ kiểm tra bài | — |
| `--landscape` | Video ngang 1920×1080 | dọc 1080×1920 |
| `--layout fullscreen\|panel` | Video dọc: ảnh toàn màn hình hoặc khung phía trên | `fullscreen` |
| `--word-repeat N` | Số lần đọc từ vựng (luân phiên 2 giọng) | 2 |
| `--example-repeat N` | Số lần đọc câu ví dụ (luân phiên 2 giọng) | 2 |
| `--no-example-vi` | Không đọc bản dịch tiếng Việt của câu ví dụ | đọc |
| `--no-vi` | Tắt giọng tiếng Việt (tiêu đề, nghĩa, giải thích) | bật |
| `--think SEC` | Thời gian suy nghĩ mỗi bài tập | theo file |
| `--fps 24\|25\|30` | Số khung hình/giây | 30 |
| `--no-logo` | Không chèn logo kênh | có logo |
| `--logo PNG` | Dùng logo khác (PNG nền trong suốt) | `assets/brand/daily-dialogues-logo.png` |
| `--logo-opacity 0–1` | Độ hiển thị của logo | 0.35 |
| `--name "…"` | Tên file video | `title_en` |

Mã thoát: `0` = thành công · `1` = bài học có lỗi · `2` = không đọc được file.

---

## 5. Kết quả

```
output/lessons/<lesson_id>/
├── <Tiêu đề>.mp4         video H.264/AAC
├── subtitles.en.srt      phụ đề tiếng Anh
├── subtitles.vi.srt      phụ đề tiếng Việt
├── thumbnail.png         ảnh bìa (khung Intro)
├── lesson.json + ảnh     đủ để dựng lại video
└── manifest.json         mốc thời gian từng phần, kịch bản giọng đọc, các câu dùng giọng dự phòng, cấu hình
```
Video dựng từ giao diện web được ghi vào lịch sử ở trang **📂 Quản lý Video** (lưu trong `data/app.db`).

Tham khảo thời gian (máy Mac M-series, giọng đọc đã có trong cache): một bài 10 từ khoảng 6,5–7,5 phút video, dựng trong khoảng 60–90 giây.

---

## 6. Xử lý sự cố

| Hiện tượng | Nguyên nhân / cách xử lý |
|---|---|
| `Không tìm thấy ảnh '…'` | Đặt ảnh cùng thư mục với JSON, tên file khớp với `scene_image` (hoặc upload ảnh trên giao diện) |
| `Font … không hiển thị được các ký tự` | Chép `Arial Unicode.ttf` (hoặc font có đủ chữ tiếng Việt và IPA) vào `assets/fonts/` |
| `Từ 'x' không xuất hiện trong lượt thoại …` | Sửa `dialogue_idx`, hoặc thêm dạng bất quy tắc vào `"forms": ["paid"]` |
| Bước "Giọng đọc" chậm, hoặc báo dùng giọng dự phòng gTTS | Dịch vụ Edge TTS miễn phí đôi khi lỗi theo đợt. Đợi vài phút rồi dựng lại; câu đã tạo được giữ trong cache |
| Tính năng mới (vd. logo) không xuất hiện khi dựng video trên giao diện web | App đang chạy code cũ trong bộ nhớ. **Khởi động lại app** (`Ctrl+C` rồi `.venv/bin/streamlit run app.py`) sau mỗi lần cập nhật code. Kiểm tra trong `manifest.json` → `render_config` |
| Bong bóng thoại che mặt nhân vật | Ảnh nhân vật đang được đưa vào qua ô "Ảnh nền". Hãy khai báo `"scene_image": "<tên-file>.png"` trong `meta` của JSON (ảnh đặt cùng thư mục với JSON); khi đó ảnh hiển thị 9:16 và chat nằm ở phía dưới |
| `ModuleNotFoundError` | Đang chạy nhầm Python; dùng `.venv/bin/python` hoặc `.venv/bin/streamlit` |
| Muốn xoá cache giọng đọc | Xoá thư mục `data/tts_cache/`; lần dựng sau sẽ tạo lại |

---

## 7. Lưu ý trước khi xuất bản
- Nội dung bài và ảnh do AI tạo cần **người duyệt**. Khi đăng, tuân thủ quy định công bố nội dung AI của từng nền tảng.
- Edge TTS và gTTS là dịch vụ **không chính thức**; điều khoản dùng thương mại cần được xác nhận.
- Font Arial có **bản quyền thương mại**; khi phân phối, cân nhắc chuyển sang font OFL (ví dụ Noto Sans, Be Vietnam Pro).
