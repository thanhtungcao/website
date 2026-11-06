"""Ghép core.js và transcript mẫu vào page.html thành thu-ky-ai.html (bản chạy trên claude.ai)."""
import json
from pathlib import Path

here = Path(__file__).parent
page = (here / "page.html").read_text(encoding="utf-8")
core = (here / "core.js").read_text(encoding="utf-8").replace('if (typeof module !== "undefined") module.exports = TK;', "")
vtt = (here.parent / "agent" / "samples" / "hop-an-phat.vtt").read_text(encoding="utf-8")
page = page.replace("/*CORE*/", core).replace('/*SAMPLE*/""', json.dumps(vtt, ensure_ascii=False).replace("</", "<\\/"))
(here / "thu-ky-ai.html").write_text(page, encoding="utf-8")
print("Đã tạo thu-ky-ai.html")
