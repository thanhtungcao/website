# Thư Ký AI: bản chạy ngay trên claude.ai

Bản này không cần máy chủ hay khóa API. Trang chạy trên claude.ai và gọi Claude bằng chính tài khoản Claude của người dùng, nên chủ trang không tốn phí.

- Tải lên hoặc dán transcript (.vtt, .srt, .txt, JSON Recall.ai), hoặc dùng cuộc họp mẫu
- Biên bản có quyết định, việc cần làm, vấn đề còn mở, rủi ro, mục cần kiểm tra lại; mỗi ý có mốc thời gian liên kết tới transcript
- Tải Word theo thể thức biên bản hành chính (tự tạo file .docx trong trình duyệt, không cần thư viện) và Markdown
- Lịch sử biên bản lưu riêng cho từng người, người khác (kể cả chủ trang) không đọc được

Sửa `page.html` hoặc `core.js`, rồi chạy `python build.py` để tạo lại `thu-ky-ai.html`.
