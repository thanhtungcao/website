# Thư Ký AI: agent họp trực tuyến

Phần mềm mã nguồn mở (giấy phép MIT), dùng miễn phí. Trang giới thiệu ở `/`, ứng dụng ở `/app`, quyền riêng tư ở `/privacy`.

Agent tham gia cuộc họp Zoom, Google Meet, Microsoft Teams (qua Recall.ai), hoặc nhận file transcript, rồi dùng Claude viết **biên bản họp tiếng Việt có cấu trúc**:

- Quyết định, việc cần làm (người phụ trách, hạn chót), vấn đề còn mở, rủi ro
- Mỗi ý kèm **mốc thời gian**; bấm vào là transcript nhảy tới đúng câu nói gốc
- Mục **"Cần kiểm tra lại"** đánh dấu tên riêng, con số, ngày tháng có thể bị nhận dạng sai
- Xuất **Word theo thể thức biên bản hành chính** (quốc hiệu, tiêu ngữ, bảng phân công, chữ ký) và Markdown
- Từ điển tổ chức (`GLOSSARY`) để sửa lỗi tên riêng

## Chạy thử

Cài đặt và cấu hình:

```bash
cd thu-ky-ai/agent
pip install -r requirements.txt
cp .env.example .env    # điền ANTHROPIC_API_KEY, tùy chọn RECALL_API_KEY
set -a; . ./.env; set +a
```

Tạo biên bản từ file mẫu bằng dòng lệnh:

```bash
python cli.py samples/hop-an-phat.vtt --docx bien-ban.docx --org "Công ty ABC"
```

Chạy giao diện web tại http://localhost:8000 (đặt `SECURE_COOKIES=0` khi chạy bằng http):

```bash
SECURE_COOKIES=0 uvicorn app.main:app --reload
```

Hoặc chạy bằng Docker:

```bash
docker build -t thu-ky-ai . && docker run -p 8000:8000 -e ANTHROPIC_API_KEY=... -v thukyai:/data thu-ky-ai
```

Chạy kiểm thử (không cần khóa API):

```bash
pip install -r requirements-asr.txt -r requirements-bot.txt
python -m pytest -q
```

## Dán link họp: Thư Ký AI tự vào họp và ghi (chạy trên máy, miễn phí)

Trong ứng dụng, dán link Google Meet / Zoom / Microsoft Teams vào mục **Mời Thư Ký AI vào cuộc họp**. Máy chủ mở một cửa sổ Edge/Chrome bằng Playwright, vào họp với tên "Thư Ký AI", thu âm thanh của cuộc họp ngay trong trang (WebRTC của Meet/Teams, WebAudio của Zoom web, thẻ `<audio>`), chép lời bằng faster-whisper, và tạo biên bản khi cuộc họp kết thúc (hoặc khi bấm **Rời họp**). Zoom được mở bằng web client (`app.zoom.us/wc/join/...`) nên không cần cài app.

- Chỉ bật khi `LOCAL_BOT=1` (script `chay-tren-may` bật sẵn): bot mở trình duyệt trên chính máy chạy máy chủ, nên không bật trên máy chủ công khai.
- Cài thêm: `pip install -r requirements-bot.txt`. Bot dùng Edge hoặc Chrome có sẵn; nếu không có, chạy `python -m playwright install chromium` hoặc đặt `BOT_BROWSER_PATH`.
- Các bước bấm "Tham gia" dựa trên giao diện tiếng Anh hiện tại của từng nền tảng và có thể hỏng khi họ đổi giao diện. Cửa sổ bot hiển thị (`BOT_HEADLESS=0`) để người dùng bấm giúp; phần thu âm vẫn hoạt động vì được gắn vào trang từ trước khi trang tải.
- Người chủ trì phải cho bot vào phòng. Bot chờ tối đa `BOT_ADMIT_TIMEOUT_MIN` phút (mặc định 10). Cuộc họp Google Meet của tổ chức có thể chặn khách không đăng nhập.
- Nếu đặt `RECALL_API_KEY`, ô dán link dùng Recall.ai thay cho bot chạy trên máy.

## Ghi trực tiếp: nghe loa, tự chép lời, tạo biên bản

Trong ứng dụng (`/app`), mục **Ghi cuộc họp trực tiếp**:

1. Chọn nguồn: **Âm thanh từ loa** (tiếng mọi người trong cuộc họp) và/hoặc **Micro của tôi**.
2. Bấm **Bắt đầu ghi**. Trình duyệt hỏi chia sẻ: chọn tab Google Meet/Zoom/Teams trên web, hoặc **Toàn màn hình** (Windows) khi họp bằng app, và **tích ô Chia sẻ âm thanh**.
3. Lời nói được chép lại sau mỗi khoảng 20 giây và hiện ngay trên màn hình.
4. Bấm **Kết thúc và tạo biên bản**: máy chủ chép nốt phần cuối rồi Claude viết biên bản.

Cách hoạt động: trình duyệt ghi âm loa và micro thành hai luồng riêng, cắt đoạn 20 giây, gửi lên máy chủ. Máy chủ chép lời bằng [faster-whisper](https://github.com/SYSTRAN/faster-whisper) chạy ngay trên máy (miễn phí, âm thanh không gửi ra ngoài, file âm thanh bị xóa ngay sau khi chép). Lời từ loa ghi là "Người tham dự", lời từ micro là "Tôi"; Claude suy ra tên người nói từ ngữ cảnh khi có thể.

**Cách chạy dễ nhất là trên chính máy tính bạn dùng để họp:**

```bash
./chay-tren-may.sh        # macOS / Linux
chay-tren-may.bat         # Windows
```

| Biến | Mặc định | Ghi chú |
|---|---|---|
| `ASR_MODEL` | `small` | `medium` chính xác hơn; có GPU thì dùng `large-v3-turbo` với `ASR_DEVICE=cuda ASR_COMPUTE_TYPE=float16` |
| `ASR_ENABLED` | `1` | Đặt `0` để tắt ghi trực tiếp |
| `MAX_LIVE_HOURS` | `4` | Độ dài tối đa một buổi ghi |

Lưu ý:
- Dùng Chrome hoặc Edge. Chia sẻ âm thanh hệ thống khi chọn **Toàn màn hình** có trên Windows và ChromeOS. Trên macOS, Chrome chỉ chia sẻ được âm thanh **của một tab**: họp bằng Meet/Zoom/Teams trên trình duyệt thì chọn tab đó; họp bằng app Zoom/Teams trên Mac thì cần thiết bị âm thanh ảo như BlackHole rồi chọn nó làm micro.
- Nên đeo tai nghe, nếu không micro sẽ thu lại tiếng loa và lời bị lặp.
- Giữ tab ứng dụng mở trong suốt buổi ghi.
- Model `small` cần khoảng 1 GB RAM và chép lời nhanh hơn thời gian thực trên CPU phổ thông. Gói free của Render (512 MB) không đủ; khi tự triển khai bằng Docker, build với `--build-arg WITH_ASR=1`.

## Cách khác: tải transcript hoặc mời bot

| Cách | Cần gì | Ghi chú |
|---|---|---|
| **Tải transcript lên** | Chỉ `ANTHROPIC_API_KEY` | Zoom, Teams, Google Meet đều xuất được transcript `.vtt`. Hỗ trợ `.vtt`, `.srt`, `.txt` dạng `Tên: nội dung`, JSON của Recall.ai |
| **Mời bot vào họp** | Thêm `RECALL_API_KEY` | Bot do [Recall.ai](https://www.recall.ai) vận hành vào họp, ghi âm, nhận dạng tiếng Việt, phân biệt người nói. Bot gửi tin nhắn thông báo đang ghi khi tham gia |

Với bot, đặt webhook trong bảng điều khiển Recall.ai trỏ tới `https://<máy-chủ>/api/webhooks/recall`. Nếu không có webhook, giao diện tự hỏi trạng thái bot mỗi 10 giây.

## Triển khai công khai, miễn phí

Repo có sẵn `render.yaml` ở thư mục gốc để triển khai lên [Render](https://render.com) bằng Blueprint: New → Blueprint → chọn repo → nhập `ANTHROPIC_API_KEY`. Gói free của Render ngủ sau 15 phút không có truy cập và không có ổ đĩa bền: biên bản mất khi dịch vụ khởi động lại. Muốn giữ biên bản, gắn một persistent disk tại `/data` và đặt `DB_PATH=/data/thukyai.db`.

Các cơ chế bảo vệ khi mở cho mọi người dùng:

| Cơ chế | Biến môi trường | Mặc định |
|---|---|---|
| Mỗi trình duyệt chỉ thấy cuộc họp của mình (cookie ẩn danh) | | luôn bật |
| Số biên bản miễn phí mỗi người mỗi ngày (theo trình duyệt và IP) | `FREE_DAILY_LIMIT` | 5 |
| Trần chung cả hệ thống mỗi ngày, chặn chi phí bất thường | `GLOBAL_DAILY_LIMIT` | 200 |
| Tự xóa cuộc họp cũ | `RETENTION_DAYS` | 30 |
| Giới hạn file tải lên / độ dài transcript | `MAX_UPLOAD_BYTES`, `MAX_TRANSCRIPT_CHARS` | 2 MB / 300.000 ký tự |
| Xác thực chữ ký webhook Recall.ai | `RECALL_WEBHOOK_SECRET` | tắt nếu để trống |

Người dùng có thể nhập **khóa Claude API riêng** trong mục Cài đặt: khóa lưu trong trình duyệt, gửi kèm từng yêu cầu, máy chủ không lưu, và không tính vào hạn mức. Nếu không đặt `ANTHROPIC_API_KEY` trên máy chủ, mọi người phải dùng khóa riêng, nên chủ bản cài đặt không tốn phí API.

Lượt bị lỗi được hoàn lại. Chi phí tối đa mỗi ngày của chủ bản cài đặt xấp xỉ `GLOBAL_DAILY_LIMIT` × chi phí một biên bản.

## Kiến trúc

```
app/
  transcript.py  đọc VTT / SRT / text / Recall JSON về danh sách Segment
  minutes.py     gọi Claude (structured output) -> Minutes (pydantic)
  render.py      Markdown và Word theo thể thức NĐ 30/2020
  recall.py      tạo bot, đọc trạng thái, tải transcript từ Recall.ai
  store.py       SQLite
  asr.py         chép lời bằng faster-whisper
  live.py        hàng đợi chép lời cho buổi ghi trực tiếp
  meetbot.py     bot vào họp chạy trên máy (Playwright), thu âm thanh trong trang họp
  webhook.py     xác thực chữ ký webhook (Svix)
  main.py        FastAPI: API, webhook, hạn mức, không gian làm việc ẩn danh
  static/        landing.html, index.html (ứng dụng), privacy.html
cli.py           dùng không cần máy chủ
```

Mô hình mặc định: `claude-opus-5-5` (đổi bằng biến `THUKY_MODEL`), effort `high`, bật `fallbacks: "default"` để yêu cầu bị từ chối được chuyển sang mô hình dự phòng.

## Cần làm tiếp trước khi bán

- Đối chiếu `app/recall.py` với tài liệu Recall.ai hiện hành (tên trường, mã ngôn ngữ `vi`, định dạng webhook) và chạy thử với một cuộc họp thật
- Đăng nhập người dùng, không gian làm việc theo nhóm
- Gửi biên bản qua email, nhắc việc qua Zalo, đồng bộ Google Calendar để bot tự vào họp
- Chuyển SQLite sang Postgres, chạy tác vụ nền bằng hàng đợi khi có nhiều người dùng
