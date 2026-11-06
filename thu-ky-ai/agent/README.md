# Thư Ký AI: agent họp trực tuyến

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

Chạy giao diện web tại http://localhost:8000:

```bash
uvicorn app.main:app --reload
```

Chạy kiểm thử (không cần khóa API):

```bash
python -m pytest -q
```

## Hai cách đưa cuộc họp vào

| Cách | Cần gì | Ghi chú |
|---|---|---|
| **Tải transcript lên** | Chỉ `ANTHROPIC_API_KEY` | Zoom, Teams, Google Meet đều xuất được transcript `.vtt`. Hỗ trợ `.vtt`, `.srt`, `.txt` dạng `Tên: nội dung`, JSON của Recall.ai |
| **Mời bot vào họp** | Thêm `RECALL_API_KEY` | Bot do [Recall.ai](https://www.recall.ai) vận hành vào họp, ghi âm, nhận dạng tiếng Việt, phân biệt người nói. Bot gửi tin nhắn thông báo đang ghi khi tham gia |

Với bot, đặt webhook trong bảng điều khiển Recall.ai trỏ tới `https://<máy-chủ>/api/webhooks/recall`. Nếu không có webhook, giao diện tự hỏi trạng thái bot mỗi 10 giây.

## Kiến trúc

```
app/
  transcript.py  đọc VTT / SRT / text / Recall JSON về danh sách Segment
  minutes.py     gọi Claude (structured output) -> Minutes (pydantic)
  render.py      Markdown và Word theo thể thức NĐ 30/2020
  recall.py      tạo bot, đọc trạng thái, tải transcript từ Recall.ai
  store.py       SQLite
  main.py        FastAPI: API + webhook + giao diện
  static/        giao diện một trang
cli.py           dùng không cần máy chủ
```

Mô hình mặc định: `claude-opus-5-5` (đổi bằng biến `THUKY_MODEL`), effort `high`, bật `fallbacks: "default"` để yêu cầu bị từ chối được chuyển sang mô hình dự phòng.

## Cần làm tiếp trước khi bán

- Đối chiếu `app/recall.py` với tài liệu Recall.ai hiện hành (tên trường, mã ngôn ngữ `vi`, định dạng webhook) và chạy thử với một cuộc họp thật
- Xác thực chữ ký webhook (Recall dùng Svix), đăng nhập người dùng, phân quyền theo nhóm
- Gửi biên bản qua email, nhắc việc qua Zalo, đồng bộ Google Calendar để bot tự vào họp
- Chuyển SQLite sang Postgres, chạy tác vụ nền bằng hàng đợi khi có nhiều người dùng
