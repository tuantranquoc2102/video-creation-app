# Giai đoạn 0 + 1 — Ghi chú triển khai

> Ngày: 2026-11-08 · Phạm vi: [02-upgrade-proposal.md](02-upgrade-proposal.md) §6, Giai đoạn 0 (củng cố nền tảng) và Giai đoạn 1 (video bài học 4 phần, **không dùng AI**).
> Trạng thái: đã triển khai và kiểm thử trên máy local (macOS, Python 3.12). **Chưa commit git, chưa qua review của người.**

---

## 1. Kết quả

| Hạng mục | Bằng chứng |
|---|---|
| Video bài học đủ 4 phần từ 1 file JSON | `samples/lessons/laundry-a2.json` → MP4 1080×1920, **4:53**, H.264 + AAC, dựng trong **43 giây** (TTS đã cache một phần) |
| Phụ đề EN + VI khớp audio | Ảnh trích từ MP4 tại t = 20 s, 100 s, 200 s, 205 s trùng với lượt thoại / thẻ từ / bài tập trong SRT |
| Test tự động | `pytest`: **53 passed** (bao gồm render end-to-end với TTS giả và smoke test mọi trang Streamlit) |
| App khởi động | `streamlit run app.py` → `/_stcore/health = ok`, không có lỗi trong log |

Thời lượng từng phần của video mẫu (`manifest.json`): Intro 8.6 s · Hội thoại 47.9 s · Từ vựng 130.4 s · Bài tập 89.3 s · Ôn tập 17.3 s.
Phần từ vựng chiếm gần một nửa thời lượng (đọc từ 2 lần + nghĩa tiếng Việt + câu ví dụ). Có thể rút ngắn bằng cách giảm "Số lần đọc mỗi từ vựng" xuống 1 hoặc tắt giọng đọc tiếng Việt.

---

## 2. Giai đoạn 0 — Các thay đổi nền tảng

Đối chiếu với bảng vấn đề trong [01-system-documentation.md §6](01-system-documentation.md):

| # | Vấn đề | Đã làm |
|---|---|---|
| 1 | requirements sai phiên bản MoviePy | `moviepy>=2.0,<3`, thêm `numpy`, `pydantic`; thêm `requirements-dev.txt` (pytest) |
| 2 | Tên file không được làm sạch | `core/utils.py`: `safe_filename`, `resolve_output_path` (giữ đường dẫn trong `output/`, **không ghi đè**, tự thêm hậu tố ` (2)`) |
| 3 | Lịch sử video mất khi reload | `core/storage.py`: SQLite `data/app.db`; `core/state.py` giữ nguyên API cũ |
| 4 | Câu tiếng Anh bị đọc bằng giọng Việt | Trang "Tạo Video": ngôn ngữ mặc định English, truyền giọng Edge en-US cho generator |
| 5 | Chế độ text ghi "Hoàn thành" giả | Bỏ nhánh demo; nút tạo video bị khoá kèm hướng dẫn |
| 6 | 2 speaker trùng giọng | Mặc định Andrew (nam) / Ava (nữ) |
| 7 | IPA bị `//…//` | `normalize_ipa` ở generator, preview, schema |
| 11 | Dashboard hiển thị số ngẫu nhiên, nút không điều hướng | Biểu đồ dùng dữ liệu thật; nút điều hướng thật (`ui/navigation.py`) |
| 12 | Bộ lọc độ phân giải sai | Lấy từ `VIDEO_RESOLUTIONS`, so khớp chính xác |
| 13 | Xoá video không xoá file; temp không dọn | Xoá record xoá luôn file (**chỉ khi file nằm trong `output/`**); generator dọn temp dir |
| 14 | MIME luôn là mp4 | `mime_for(fmt)` |
| 15 | HTML injection ở preview CSV | `html.escape` toàn bộ nội dung CSV |
| 16 | `print` debug | Chuyển sang `logging` |
| 17 | Không có git / test | `git init` + `.gitignore` (chưa commit); 53 test |

**Lỗi phát hiện thêm trong lúc triển khai (đã sửa):**
- **Font mặc định không hiển thị được tiếng Việt.** `DEFAULT_FONT` lấy font đầu tiên theo thứ tự alphabet là *Arial Rounded Bold*. Kiểm tra bằng code cho thấy font này thiếu hầu hết chữ có dấu (ạ, ầ, ấ, ệ, ư, ơ, đ…) và ký tự IPA. Nay mặc định là *Arial Unicode* (đủ cả hai bộ ký tự), áp dụng cho cả các trang cũ. Trang Video Bài Học còn tự kiểm tra font và chặn tạo video nếu thiếu glyph.
- **Xuất WebM luôn lỗi**: codec âm thanh `aac` không hợp lệ trong WebM. Nay dùng bảng codec theo định dạng (`codecs_for`).

**Chưa xử lý (cần quyết định):**
- #8: edge-tts/gTTS là endpoint không chính thức. Đã giảm rủi ro bằng cache + retry + fallback (§3.4), nhưng chưa giải quyết tận gốc.
- #9: giấy phép font Arial. Phải xác nhận trước khi dùng thương mại.
- #10: các tuỳ chọn "Tốc độ đọc" / "Kiểu chữ" ở trang "Tạo Video" vẫn chưa có tác dụng.
- Ảnh nền upload ở các trang cũ vẫn được lưu vào temp mà không dọn.

---

## 3. Giai đoạn 1 — Video bài học

### 3.1 Cấu trúc mới

```
core/lesson/      schema.py (Pydantic), validators.py, text.py, importers.py
core/render/      config.py, canvas.py (Pillow), timeline.py, subtitles.py, assemble.py
  segments/       common.py, intro.py, dialogue.py, vocab.py, exercise.py, outro.py
ui/views/lesson_video.py     Trang "🎓 Video Bài Học"
ui/navigation.py             Điều hướng bằng code (tránh import vòng)
samples/lessons/laundry-a2.json
tests/                       53 test (pytest)
```

### 3.2 Lesson JSON

Xem file mẫu `samples/lessons/laundry-a2.json`. Tóm tắt:

| Trường | Bắt buộc | Ghi chú |
|---|---|---|
| `lesson_id` | ✔ | `a-z0-9-`, dùng làm tên thư mục output |
| `meta.topic, level, title_en, title_vi` | ✔ | `level` ∈ A1…C2 |
| `meta.learning_goal_vi` | | Hiển thị và đọc ở Intro |
| `characters[2]` | ✔ | `id`, `name`, `gender` (female/male), `voice` (tuỳ chọn, Edge voice id) |
| `dialogue[]` | ✔ | `speaker` (id nhân vật), `en`, `vi` |
| `vocabulary[]` | ✔ (đúng 10) | `word`, `ipa` (không cần `/`), `pos`, `meaning_vi`, `dialogue_idx` (lượt thoại chứa từ, tính từ 0); `forms` cho dạng bất quy tắc (vd. `paid`); `example_en/vi` mặc định lấy câu thoại |
| `exercises[]` | | `type` ∈ `multiple_choice`, `fill_blank` (prompt có `____`), `translate_vi_en`, `comprehension`; `options` 2–4; `answer`; `explanation_vi`; `think_seconds` 2–15 |

Schema chặn trường lạ (`extra="forbid"`) để phát hiện lỗi gõ tên trường.

### 3.3 Kiểm tra tự động (`validate_lesson`)
- **Lỗi** (chặn tạo video): sai số lượng từ vựng; từ trùng; từ không xuất hiện trong lượt thoại được tham chiếu (có nhận dạng biến thể như costs, removing, stopped, carried); speaker không tồn tại; số lượt thoại ngoài khoảng 4–24; đáp án không nằm trong lựa chọn; bài điền từ thiếu `____`; bài dịch thiếu `prompt_vi`…
- **Cảnh báo** (người duyệt xem lại): câu dài quá mức theo level (A2: tối đa 12 từ/câu); bản dịch không có dấu; hai nhân vật cùng giọng; câu hỏi có thể lộ đáp án; một nhân vật nói 2 lượt liên tiếp…

### 3.4 Dựng video
- **Frame vẽ bằng Pillow** thay cho TextClip: tô màu từ vựng trong câu thoại, hiển thị đúng tiếng Việt/IPA, tự co chữ cho vừa khung. Vẽ toàn bộ khung hình mất khoảng 1 s.
- **Bố cục**: dọc 9:16 (chừa vùng an toàn phía dưới cho giao diện Shorts/Reels/TikTok) và ngang 16:9 (hai cột cho thẻ từ vựng và bài tập).
- **Bài tập**: câu hỏi → đếm ngược (mỗi giây một khung, có tiếng tích) → đáp án đúng tô xanh kèm giải thích.
- **Âm thanh**: trộn tất cả câu thoại thành một track WAV bằng numpy + ffmpeg đi kèm, rồi ghép vào video. Frame được lưu PNG và nạp dần khi encode nên bộ nhớ không tăng theo độ dài video.
- **TTS**: cache theo hash (văn bản + giọng) trong `data/tts_cache/`, nên dựng lại video không gọi lại dịch vụ. Mỗi câu được thử lại tối đa 5 lần.
  - **Đã quan sát thực tế:** Edge TTS miễn phí lỗi ngắt quãng (`NoAudioReceived`) với khoảng 20–30% request trong một đợt thử. Gửi lại đúng câu đó ít phút sau thì thành công.
  - Vì vậy, nếu một câu vẫn lỗi sau 5 lần, câu đó được đọc bằng **gTTS** (giọng khác) để video vẫn dựng xong. Danh sách các câu này được ghi vào `manifest.json` và hiển thị trên UI để người duyệt nghe lại.
- **Đầu ra** trong `output/lessons/<lesson_id>/`: `<tên>.mp4`, `subtitles.en.srt`, `subtitles.vi.srt`, `thumbnail.png`, `lesson.json`, `manifest.json` (mốc thời gian từng phần, cấu hình render, các câu dùng fallback).

### 3.5 Trang "🎓 Video Bài Học"
Chọn bài mẫu hoặc upload JSON → xem kết quả kiểm tra → xem nội dung song ngữ / từ vựng / bài tập → cài đặt (độ phân giải, FPS, màu/ảnh nền, font, giọng từng nhân vật, giọng dẫn EN/VI, tuỳ chọn đọc tiếng Việt, số lần đọc từ, thời gian suy nghĩ) → **xem trước khung hình thật** → tạo video → xem trực tiếp, tải MP4/SRT/thumbnail. Kết quả được lưu vào lịch sử (SQLite) và hiện ở trang Quản lý Video.

---

## 4. Cách chạy

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/streamlit run app.py          # mở http://localhost:8501 → 🎓 Video Bài Học
.venv/bin/python -m pytest -q           # 53 test, ~8 giây, không cần mạng
```
Không cần cài FFmpeg riêng: MoviePy 2 dùng bản ffmpeg đi kèm `imageio-ffmpeg`.

---

## 5. Giới hạn đã biết & rủi ro

| Hạng mục | Mô tả | Đề xuất |
|---|---|---|
| Dựng video chạy đồng bộ trong Streamlit | Đóng tab trình duyệt trong lúc dựng sẽ mất tiến trình | Worker nền ở Giai đoạn 3 |
| TTS không chính thức | Có thể lỗi hoặc bị chặn; điều khoản sử dụng thương mại chưa xác nhận | Quyết định nhà cung cấp TTS (câu hỏi mở §1.3 của bản đề xuất) |
| Nhận dạng từ trong câu | Chỉ nhận biến thể có quy tắc; cụm động từ bị tách ("pick them up") không nhận ra | Khai báo trong `forms` hoặc chọn câu chứa nguyên cụm |
| IPA | Do người viết nhập; code chỉ kiểm tra là không rỗng | Đối chiếu từ điển ở Giai đoạn 2 |
| Nội dung bài mẫu | Hội thoại, bản dịch, IPA do tôi (AI) soạn | **Cần giáo viên/biên tập viên duyệt** trước khi xuất bản |
| Độ dài video mẫu 4:53 | Dài hơn ước lượng 3–4 phút trong bản đề xuất | Giảm `word_repeat`, tắt đọc nghĩa tiếng Việt, hoặc dùng ít bài tập hơn |

---

## 6. Bước tiếp theo đề xuất
1. Review code và nội dung bài mẫu, sau đó tạo commit đầu tiên (repo mới chỉ `git init`, chưa có commit).
2. Viết thêm 2–3 bài JSON thật để thử độ dài, nhịp độ và giao diện với người xem mục tiêu.
3. Chốt nhà cung cấp TTS và font có giấy phép.
4. Giai đoạn 2: sinh Lesson JSON bằng LLM, dùng chính `validate_lesson` làm cổng kiểm tra.

---

## 7. Lần điều chỉnh 2 (theo phản hồi ngày 2026-11-08)

### 7.1 Yêu cầu
1. Phần từ vựng: từ tiếng Anh đọc **2 lần bằng 2 giọng khác nhau**. Câu ví dụ cũng đọc 2 lần, sau đó đọc **bản dịch tiếng Việt**.
2. Ở mọi phần có cả tiếng Anh lẫn tiếng Việt: phần tiếng Anh đọc bằng giọng Anh, phần tiếng Việt bằng giọng Việt. Trước đây có chỗ giọng Anh đọc cả tiếng Việt.
3. Thêm **hình minh hoạ**, dùng ảnh mẫu người dùng cung cấp (`samples/lessons/Gemini_Generated_Image_gww702gww702gww7.png`).

### 7.2 Đã làm
**Thứ tự đọc mỗi thẻ từ vựng** (cấu hình trong `RenderConfig` và trên UI):
`từ` (giọng 1) → `từ` (giọng 2) → nghĩa tiếng Việt → `câu ví dụ` (giọng 1) → `câu ví dụ` (giọng 2) → bản dịch tiếng Việt của câu ví dụ.
Mặc định: giọng 1 = Jenny, giọng 2 = Guy (en-US). Có thể chọn lại giọng, số lần đọc từ (1–4), số lần đọc câu ví dụ (1–4), và bật/tắt đọc bản dịch.

**Tự tách ngôn ngữ để chọn giọng** (`core/lesson/text.py::split_by_language`). Mỗi câu được tách thành các đoạn EN/VI theo quy tắc cố định, không dùng AI:
- Từ có dấu tiếng Việt → VI.
- Từ không dấu được xét trong từng cụm. Cụm được ngăn bởi ngoặc kép, `=`, `:`, ngoặc đơn, gạch ngang.
  - Từ trông giống âm tiết tiếng Việt, đứng cạnh tiếng Việt → VI (vd. `Bao nhiêu`, `cho sinh viên`).
  - Một từ ngoại lai đơn lẻ nằm trong câu tiếng Việt → VI (vd. `đặt taxi`, `Anna nói`, `mở minibar`).
  - Còn lại → EN.
- Số theo ngôn ngữ của từ đứng cạnh (vd. `Room 512` → EN, `Phòng 512` → VI).
- **Hướng dẫn cho người soạn bài:** muốn một thuật ngữ tiếng Anh chắc chắn được đọc bằng giọng Anh, hãy đặt nó trong ngoặc kép, vd. `"discount" nghĩa là gì?`.
- Áp dụng cho: intro, tiêu đề phần, hội thoại, nghĩa từ, câu ví dụ, câu hỏi (đọc cả `prompt_en` và `prompt_vi`), đáp án, giải thích, ôn tập.
- Mỗi lần dựng ghi **kịch bản giọng đọc** (thời điểm · giọng · nội dung của từng đoạn) vào `manifest.json` và hiển thị trên UI, để người duyệt kiểm tra mà không cần nghe hết video.

**Hình minh hoạ**:
- Schema mới: `meta.scene_image` (ảnh cảnh hội thoại), `meta.scene_focus_y` (điểm lấy nét khi phải cắt ảnh), `vocabulary[].image` (ảnh riêng cho từng từ, tuỳ chọn). Đường dẫn tính tương đối so với file JSON và bị chặn nếu trỏ ra ngoài thư mục bài học.
- Intro: dọc → ảnh chiếm khoảng 52% phía trên, chữ bên dưới. Ngang → hiện nguyên ảnh dạng thẻ bên trái, chữ bên phải.
- Hội thoại: dọc → khung ảnh phía trên, bong bóng chat bên dưới. Ngang → ảnh cột trái, chat cột phải.
- Các khung còn lại dùng ảnh cảnh làm nền (làm mờ và tối); có thể tắt trên UI.
- Thẻ từ vựng hiện ảnh riêng của từ nếu có.
- Upload JSON có tham chiếu ảnh → UI yêu cầu upload kèm ảnh. Ảnh được kiểm tra: tồn tại, mở được, nằm trong thư mục bài học.
- Ảnh được copy vào `output/lessons/<id>/` cạnh `lesson.json`, để thư mục kết quả tự đủ để dựng lại.
- Bài mẫu mới **`samples/lessons/hotel-checkout-a2.json`** (Trả phòng khách sạn, A2, 11 lượt thoại, 10 từ, 5 bài tập) được soạn khớp với ảnh mẫu: Anna (khách, bên trái) và Mark (lễ tân, bên phải).

### 7.3 Kiểm thử
- 74 test pass. Có 21 test mới cho: tách ngôn ngữ (11 trường hợp lấy từ bài thật), thứ tự và giọng đọc phần từ vựng, kiểm tra "không đoạn tiếng Việt nào bị giọng Anh đọc" trên toàn bộ phần bài tập, ảnh thiếu / ảnh trỏ ra ngoài thư mục / file không phải ảnh, và vẽ khung có ảnh ở cả 2 hướng.

### 7.4 Lưu ý
- **Ảnh mẫu do AI tạo** (tên file "Gemini", góc dưới phải có dấu "ai"). Ở khung hội thoại và intro dọc, ảnh bị cắt theo khung nên dấu này có thể bị cắt mất. Ở intro ngang, ảnh hiện nguyên vẹn. Tôi không chủ động xoá dấu. Khi đăng lên YouTube/TikTok cần tuân thủ quy định công bố nội dung do AI tạo của từng nền tảng.
- Nội dung bài hotel do tôi (AI) soạn → **cần giáo viên/biên tập viên duyệt**.
- Thời lượng tăng vì mỗi từ được đọc nhiều hơn (xem kết quả dựng thực tế ở §7.5). Có thể giảm số lần đọc trên UI.

### 7.5 Kết quả dựng thực tế (Edge TTS thật, 2026-11-08)

| Bài | Thời lượng | Thời gian dựng | Intro | Hội thoại | Từ vựng | Bài tập | Ôn tập | Đoạn đọc | Lỗi định tuyến giọng | Fallback gTTS |
|---|---|---|---|---|---|---|---|---|---|---|
| hotel-checkout-a2 | **7:18** | 88 s | 9.5 s | 48.2 s | 246.8 s | 116.6 s | 17.4 s | 110 | **0** | 0 |
| laundry-a2 | **7:29** | 78 s | 8.6 s | 47.9 s | 261.0 s | 114.5 s | 17.3 s | 109 | **0** | 0 |

- Cả hai file: H.264 High 1080×1920 30 fps + AAC stereo; mean −25 dB, peak −4.3/−4.8 dB (không clip).
- Ảnh trích từ MP4 khớp với kịch bản giọng đọc: t = 75 s là thẻ "check out", t = 323 s là đáp án "B. hóa đơn".
- **Thời lượng tăng từ 4:53 lên khoảng 7:20**. Nguyên nhân: mỗi thẻ từ vựng giờ mất khoảng 25 s (từ ×2 + nghĩa + câu ví dụ ×2 + bản dịch), và câu hỏi bài tập đọc cả bản tiếng Việt. Nếu cần video ngắn hơn: đặt số lần đọc câu ví dụ = 1 (giảm khoảng 70 s), hoặc dùng 6–8 từ/bài.

**Sự cố trong lúc chạy và cách xử lý:**
- Lần dựng đầu tiên bị treo hơn 25 phút: endpoint Edge TTS miễn phí đứng hoặc từ chối request theo từng đợt, kèm timeout mặc định dài. Khi thử lại đúng các câu bị lỗi thì thành công 4/4, tức là lỗi ngẫu nhiên phía dịch vụ, không do nội dung.
- Đã sửa:
  - Giới hạn cứng 25 s cho mỗi lần gọi; xoá file tạm khi lỗi (trước đó còn sót 22 file rỗng trong cache).
  - Giảm còn 4 lần thử lại, sau đó dùng gTTS cho riêng câu đó.
  - **Tạo trước toàn bộ giọng đọc song song (4 luồng)** với tiến độ "Tạo giọng đọc x/y" trên UI. Bước TTS chỉ còn khoảng 16 s cho khoảng 100 câu.

### 7.6 Hiển thị hình minh hoạ theo tỉ lệ 9:16 (2026-11-09)
- Thêm `RenderConfig.scene_layout` (UI: "Hiển thị hình minh hoạ (video dọc)"):
  - `fullscreen` (**mặc định**): Intro và Hội thoại dùng ảnh **toàn khung 9:16**. Bong bóng chat nằm phía dưới trên một lớp nền tối mờ dần, giữ nhìn thấy mặt nhân vật; mỗi lần hiện câu thoại hiện tại và tối đa 1 câu trước. Tiêu đề bài trên header nằm trong một nhãn (pill) tối để dễ đọc trên nền ảnh sáng.
  - `panel`: kiểu cũ, ảnh nằm trong khung phía trên khung chat.
- Video ngang 16:9: ảnh luôn hiển thị dạng **thẻ đúng tỉ lệ 9:16** bên trái (Intro và Hội thoại).
- Ảnh mẫu 768×1408 có tỉ lệ khoảng 0,545, gần với 9:16 = 0,5625, nên mỗi bên chỉ bị cắt khoảng 1,5% chiều ngang.
- Đã dựng lại `hotel-checkout-a2`: 7:18, 81 s, 0 fallback. Test: 76 pass (thêm 2 test cho bố cục 9:16).

### 7.7 Logo kênh (2026-11-09)
- Logo "Daily Dialogues English" (`assets/brand/daily-dialogues-logo.png`, PNG 801×801 nền trong suốt) được chèn **ở giữa, phía dưới** mọi khung hình (kể cả thumbnail), với độ hiển thị mặc định 35%.
- Video dọc: logo rộng khoảng 130 px, cách mép dưới 3,5%, nằm dưới vùng nội dung (khung nội dung kết thúc ở 80% chiều cao), nên không che chữ.
- Video ngang: logo nhỏ hơn (khoảng 97 px); vùng nội dung tự thu lại, kết thúc ở 86% chiều cao, để chừa chỗ cho logo.
- Lưu ý: trên YouTube Shorts / TikTok, phần dưới màn hình có thể bị giao diện của ứng dụng (tên kênh, chú thích) che một phần logo.
- Tuỳ chỉnh: trên UI (bật/tắt, độ mờ 10–80%, kích thước 6–20%, upload logo khác) và CLI (`--no-logo`, `--logo`, `--logo-opacity`).
- Test: thêm 4 test (logo nằm giữa, ở phía dưới, không đè lên nội dung, đủ mờ; tắt được; cờ CLI).

### 7.8 Phần ôn tập đọc chậm lại (2026-11-09)
- Trước đây: cả 10 từ được đọc trong **một** câu TTS ("express, cost, per, …"), khoảng 6 giây, nghe dồn dập.
- Nay: **mỗi từ được đọc riêng**, sau mỗi từ **nghỉ 1 giây** để người xem nhắc lại (`RenderConfig.recap_pause`). Trên màn hình, **dòng của từ đang đọc được tô sáng** (nền tím, viền vàng). Phụ đề hiện từ tiếng Anh và nghĩa tiếng Việt.
- Đo trên video `laundry-a2`: khoảng 2,9 giây/từ. Phần ôn tập dài 37,6 giây (trước đây 17,3 giây); cả video 7:49.
