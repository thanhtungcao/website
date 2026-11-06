/* Thư Ký AI: lõi xử lý chạy trong trình duyệt (đọc transcript, prompt, xuất Markdown và Word). */
const TK = (() => {
  // ---------- Transcript ----------
  const CUE = /(\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{1,3}\s*-->\s*/;
  const VOICE = /^<v(?:\.[^ >]*)?\s+([^>]+)>([\s\S]*?)(?:<\/v>)?$/;
  const SPEAKER = /^(?:\[?(\d{1,2}:\d{2}(?::\d{2})?)\]?\s*[-–]?\s*)?([^:\n]{1,40}):\s*(.+)$/;

  function parseTs(v) {
    return v.trim().replace(",", ".").split(":").reduce((a, p) => a * 60 + parseFloat(p), 0);
  }
  function fmtTs(sec) {
    sec = Math.floor(sec);
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    const p = (n) => String(n).padStart(2, "0");
    return h ? `${h}:${p(m)}:${p(s)}` : `${p(m)}:${p(s)}`;
  }
  function parseCues(raw) {
    const out = [];
    for (const block of raw.replace(/\r\n/g, "\n").split(/\n\s*\n/)) {
      const lines = block.trim().split("\n").filter((l) => l.trim());
      const i = lines.findIndex((l) => CUE.test(l));
      if (i < 0) continue;
      const start = parseTs(lines[i].split("-->")[0]);
      const body = lines.slice(i + 1).join(" ").trim();
      if (!body) continue;
      let speaker = "Không rõ", text = body;
      const v = body.match(VOICE);
      if (v) { speaker = v[1].trim(); text = v[2].trim(); }
      else { const m = body.match(SPEAKER); if (m) { speaker = m[2].trim(); text = m[3].trim(); } }
      text = text.replace(/<\/?[^>]+>/g, "").trim();
      const last = out[out.length - 1];
      if (last && last.speaker === speaker && start - last.start < 30) last.text += " " + text;
      else out.push({ start, speaker, text });
    }
    return out;
  }
  function parsePlain(raw) {
    const out = [];
    let clock = 0;
    for (let line of raw.replace(/\r\n/g, "\n").split("\n")) {
      line = line.trim();
      if (!line) continue;
      const m = line.match(SPEAKER);
      if (m) {
        if (m[1]) clock = parseTs(m[1]);
        out.push({ start: clock, speaker: m[2].trim(), text: m[3].trim() });
      } else if (out.length) out[out.length - 1].text += " " + line;
      else out.push({ start: clock, speaker: "Không rõ", text: line });
      clock += 1;
    }
    return out;
  }
  function parseRecall(data) {
    if (!Array.isArray(data)) data = data.transcript || data.results || [];
    return data.filter((p) => (p.words || []).length).map((p) => {
      const ts = p.words[0].start_timestamp;
      return {
        start: Number(typeof ts === "object" && ts ? ts.relative || 0 : ts || 0),
        speaker: (p.participant && p.participant.name) || p.speaker || "Không rõ",
        text: p.words.map((w) => w.text || "").join(" ").trim(),
      };
    });
  }
  function parseTranscript(raw, filename = "") {
    const s = raw.replace(/^﻿/, "").trim();
    const name = filename.toLowerCase();
    if (name.endsWith(".json") || s.startsWith("[") || s.startsWith("{")) {
      try { return parseRecall(JSON.parse(s)); } catch (e) { /* không phải JSON */ }
    }
    if (s.startsWith("WEBVTT") || /\.(vtt|srt)$/.test(name) || CUE.test(s.slice(0, 500))) {
      const segs = parseCues(s);
      if (segs.length) return segs;
    }
    return parsePlain(s);
  }
  const toPromptText = (segs) => segs.map((s) => `[${fmtTs(s.start)}] ${s.speaker}: ${s.text}`).join("\n");

  // ---------- Prompt ----------
  const TYPES = { hanh_chinh: "Họp hành chính", ban_hang: "Gọi bán hàng", giao_ban: "Giao ban", mot_mot: "Họp 1:1", phong_van: "Phỏng vấn", khac: "Cuộc họp" };

  function buildPrompt(segs, { glossary = "", context = "" } = {}) {
    return `Bạn là thư ký cuộc họp chuyên nghiệp cho doanh nghiệp Việt Nam. Dưới đây là transcript một cuộc họp (có thể do máy nhận dạng giọng nói tạo ra, có lỗi chính tả, nói lẫn tiếng Anh). Hãy viết biên bản họp bằng tiếng Việt chuẩn mực, khách quan.

Nguyên tắc:
- Chỉ ghi điều thực sự có trong transcript. Không suy đoán quyết định, người phụ trách hay hạn chót; khi không rõ ghi "Chưa giao" hoặc "Chưa có".
- Mỗi ý kèm mốc thời gian lấy đúng từ transcript (dạng MM:SS hoặc H:MM:SS) để người đọc đối chiếu.
- Phân biệt điều đã được thống nhất (decisions) với điều mới đề xuất hoặc còn tranh luận (open_questions).
- Giữ thuật ngữ tiếng Anh thông dụng nơi công sở khi người họp dùng (deadline, KPI...), nhưng viết câu bằng tiếng Việt.
- Đưa vào "uncertain" mọi tên riêng, con số, số tiền, ngày tháng có dấu hiệu nhận dạng sai hoặc mâu thuẫn.
- Văn phong biên bản: câu trần thuật, ngắn gọn, không ngôi thứ nhất, không bình luận.
${glossary ? `\nTừ điển của tổ chức (dùng để sửa lỗi tên riêng, thuật ngữ): ${glossary}\n` : ""}${context ? `\nThông tin thêm về cuộc họp: ${context}\n` : ""}
<transcript>
${toPromptText(segs)}
</transcript>

Trả lời CHỈ bằng một đối tượng JSON, không có chữ nào khác, đúng cấu trúc:
{
  "title": "tên cuộc họp ngắn gọn, cụ thể",
  "meeting_type": "hanh_chinh | ban_hang | giao_ban | mot_mot | phong_van | khac",
  "purpose": "mục đích cuộc họp, một câu",
  "chair": "người chủ trì hoặc 'Chưa xác định'",
  "attendees": ["tên người tham dự"],
  "summary": [{"text": "nội dung chính, theo thứ tự", "timestamp": "MM:SS"}],
  "decisions": [{"text": "điều đã thống nhất", "timestamp": "MM:SS"}],
  "action_items": [{"task": "việc cần làm, bắt đầu bằng động từ", "owner": "người phụ trách hoặc 'Chưa giao'", "deadline": "dd/mm nếu được, hoặc như được nói, hoặc 'Chưa có'", "timestamp": "MM:SS"}],
  "open_questions": [{"text": "vấn đề còn bỏ ngỏ", "timestamp": "MM:SS"}],
  "risks": [{"text": "rủi ro được nêu", "timestamp": "MM:SS"}],
  "uncertain": [{"term": "từ cần kiểm tra", "reason": "vì sao", "timestamp": "MM:SS"}]
}`;
  }

  const str = (v, d = "") => (typeof v === "string" && v.trim() ? v.trim() : d);
  const arr = (v) => (Array.isArray(v) ? v : []);
  function normalize(m) {
    if (!m || typeof m !== "object") throw new Error("Kết quả không đúng định dạng biên bản.");
    const pts = (v) => arr(v).map((p) => ({ text: str(p && p.text), timestamp: str(p && p.timestamp, "00:00") })).filter((p) => p.text);
    return {
      title: str(m.title, "Cuộc họp"),
      meeting_type: TYPES[m.meeting_type] ? m.meeting_type : "khac",
      purpose: str(m.purpose, "Chưa xác định"),
      chair: str(m.chair, "Chưa xác định"),
      attendees: arr(m.attendees).map((a) => str(a)).filter(Boolean),
      summary: pts(m.summary),
      decisions: pts(m.decisions),
      action_items: arr(m.action_items).map((a) => ({
        task: str(a && a.task), owner: str(a && a.owner, "Chưa giao"),
        deadline: str(a && a.deadline, "Chưa có"), timestamp: str(a && a.timestamp, "00:00"),
      })).filter((a) => a.task),
      open_questions: pts(m.open_questions),
      risks: pts(m.risks),
      uncertain: arr(m.uncertain).map((u) => ({ term: str(u && u.term), reason: str(u && u.reason), timestamp: str(u && u.timestamp, "00:00") })).filter((u) => u.term),
    };
  }

  // ---------- Markdown ----------
  function toMarkdown(m, date = new Date()) {
    const d = date.toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit", year: "numeric" });
    const out = [`# BIÊN BẢN HỌP: ${m.title}`, "", `${TYPES[m.meeting_type]} · ${d}`, "",
      `**Mục đích:** ${m.purpose}`, `**Chủ trì:** ${m.chair}`, `**Thành phần tham dự:** ${m.attendees.join(", ") || "Chưa xác định"}`, ""];
    const pts = (title, items) => { if (!items.length) return; out.push(`## ${title}`, ...items.map((p) => `- ${p.text} \`[${p.timestamp}]\``), ""); };
    pts("Nội dung chính", m.summary);
    pts("Quyết định", m.decisions);
    if (m.action_items.length) {
      out.push("## Việc cần làm", "", "| Việc | Phụ trách | Hạn | Mốc |", "|---|---|---|---|",
        ...m.action_items.map((a) => `| ${a.task} | ${a.owner} | ${a.deadline} | ${a.timestamp} |`), "");
    }
    pts("Vấn đề còn mở", m.open_questions);
    pts("Rủi ro", m.risks);
    if (m.uncertain.length) out.push("## Cần kiểm tra lại", ...m.uncertain.map((u) => `- **${u.term}**: ${u.reason} \`[${u.timestamp}]\``), "");
    out.push("---", "_Biên bản do Thư Ký AI tạo. Kiểm tra lại trước khi sử dụng chính thức._");
    return out.join("\n");
  }

  // ---------- Word (.docx) không cần thư viện ----------
  const x = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  const FONT = '<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:cs="Times New Roman"/>';
  function run(text, { b, i, size = 26, color } = {}) {
    return `<w:r><w:rPr>${FONT}${b ? "<w:b/>" : ""}${i ? "<w:i/>" : ""}${color ? `<w:color w:val="${color}"/>` : ""}<w:sz w:val="${size}"/></w:rPr><w:t xml:space="preserve">${x(text)}</w:t></w:r>`;
  }
  function para(runs, { align, after = 80, underline } = {}) {
    return `<w:p><w:pPr>${align ? `<w:jc w:val="${align}"/>` : ""}<w:spacing w:after="${after}"/></w:pPr>${Array.isArray(runs) ? runs.join("") : runs}</w:p>`;
  }
  function table(rows, widths, borders) {
    const b = borders ? "single" : "nil";
    const bd = ["top", "left", "bottom", "right", "insideH", "insideV"].map((k) => `<w:${k} w:val="${b}" w:sz="4" w:space="0" w:color="000000"/>`).join("");
    const grid = widths.map((w) => `<w:gridCol w:w="${w}"/>`).join("");
    const trs = rows.map((cells) => `<w:tr>${cells.map((c, i) => `<w:tc><w:tcPr><w:tcW w:w="${widths[i]}" w:type="dxa"/></w:tcPr>${c}</w:tc>`).join("")}</w:tr>`).join("");
    return `<w:tbl><w:tblPr><w:tblW w:w="${widths.reduce((a, c) => a + c, 0)}" w:type="dxa"/><w:tblBorders>${bd}</w:tblBorders><w:tblCellMar><w:left w:w="80" w:type="dxa"/><w:right w:w="80" w:type="dxa"/></w:tblCellMar></w:tblPr><w:tblGrid>${grid}</w:tblGrid>${trs}</w:tbl>`;
  }

  function documentXml(m, { org = "", date = new Date() } = {}) {
    const dd = String(date.getDate()).padStart(2, "0"), mm = String(date.getMonth() + 1).padStart(2, "0"), yy = date.getFullYear();
    const c = "center";
    const body = [];
    body.push(table([
      [para(run((org || "TÊN CƠ QUAN, TỔ CHỨC").toUpperCase(), { b: 1, size: 24 }), { align: c }),
       para(run("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", { b: 1, size: 24 }), { align: c, after: 0 }) + para(run("Độc lập - Tự do - Hạnh phúc", { b: 1, size: 26 }), { align: c })],
      [para(run("Số:      /BB-...", { size: 26 }), { align: c }), para(run(`..., ngày ${dd} tháng ${mm} năm ${yy}`, { i: 1, size: 26 }), { align: c })],
    ], [3800, 5300], false));
    body.push(para("", { after: 120 }));
    body.push(para(run("BIÊN BẢN HỌP", { b: 1, size: 28 }), { align: c, after: 40 }));
    body.push(para(run(m.title, { b: 1 }), { align: c, after: 240 }));
    body.push(para([run("Thời gian: ", { b: 1 }), run(`ngày ${dd}/${mm}/${yy}`)]));
    body.push(para([run("Chủ trì: ", { b: 1 }), run(m.chair)]));
    body.push(para([run("Thành phần tham dự: ", { b: 1 }), run(m.attendees.join(", ") || "Chưa xác định")]));
    body.push(para([run("Mục đích: ", { b: 1 }), run(m.purpose)], { after: 200 }));
    const section = (title, items) => {
      if (!items.length) return;
      body.push(para(run(title, { b: 1 }), { after: 80 }));
      items.forEach((p, i) => body.push(para([run(`${i + 1}. ${p.text} `), run(`[${p.timestamp}]`, { size: 20, color: "2346C8" })])));
    };
    section("I. NỘI DUNG CUỘC HỌP", m.summary);
    section("II. KẾT LUẬN, QUYẾT ĐỊNH", m.decisions);
    if (m.action_items.length) {
      body.push(para(run("III. PHÂN CÔNG THỰC HIỆN", { b: 1 })));
      const cell = (t, o) => para(run(t, { size: 24, ...o }), { after: 0 });
      body.push(table([
        ["Nội dung công việc", "Người phụ trách", "Thời hạn", "Mốc"].map((h) => cell(h, { b: 1 })),
        ...m.action_items.map((a) => [cell(a.task), cell(a.owner), cell(a.deadline), cell(a.timestamp)]),
      ], [4300, 2200, 1600, 1000], true));
      body.push(para("", { after: 120 }));
    }
    section("IV. VẤN ĐỀ CÒN BỎ NGỎ", m.open_questions);
    section("V. RỦI RO", m.risks);
    body.push(para(run("Biên bản được lập trên cơ sở ghi âm cuộc họp, các mốc thời gian dẫn chiếu tới bản ghi gốc.", { i: 1, size: 24 }), { after: 320 }));
    const chair = m.chair !== "Chưa xác định" ? m.chair : "";
    const sign = (role, name) => para(run(role, { b: 1 }), { align: c, after: 0 }) + para(run("(Ký, ghi rõ họ tên)", { i: 1, size: 24 }), { align: c, after: 1200 }) + para(run(name, { b: 1 }), { align: c });
    body.push(table([[sign("THƯ KÝ", ""), sign("CHỦ TRÌ", chair)]], [4550, 4550], false));
    return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>${body.join("")}<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1701" w:header="709" w:footer="709" w:gutter="0"/></w:sectPr></w:body></w:document>`;
  }

  // Tệp ZIP không nén (STORE): đủ cho .docx.
  const CRC = (() => { const t = new Uint32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
  const crc32 = (b) => { let c = 0xffffffff; for (let i = 0; i < b.length; i++) c = CRC[(c ^ b[i]) & 0xff] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };
  function zip(files) {
    const enc = new TextEncoder(), parts = [], central = [];
    let offset = 0;
    for (const [name, content] of files) {
      const nb = enc.encode(name), data = typeof content === "string" ? enc.encode(content) : content, crc = crc32(data);
      const h = new DataView(new ArrayBuffer(30));
      h.setUint32(0, 0x04034b50, true); h.setUint16(4, 20, true); h.setUint16(6, 0x0800, true); h.setUint16(8, 0, true);
      h.setUint16(10, 0, true); h.setUint16(12, 0x21, true); h.setUint32(14, crc, true);
      h.setUint32(18, data.length, true); h.setUint32(22, data.length, true); h.setUint16(26, nb.length, true); h.setUint16(28, 0, true);
      parts.push(new Uint8Array(h.buffer), nb, data);
      const cd = new DataView(new ArrayBuffer(46));
      cd.setUint32(0, 0x02014b50, true); cd.setUint16(4, 20, true); cd.setUint16(6, 20, true); cd.setUint16(8, 0x0800, true);
      cd.setUint16(10, 0, true); cd.setUint16(12, 0, true); cd.setUint16(14, 0x21, true); cd.setUint32(16, crc, true);
      cd.setUint32(20, data.length, true); cd.setUint32(24, data.length, true); cd.setUint16(28, nb.length, true);
      cd.setUint32(42, offset, true);
      central.push(new Uint8Array(cd.buffer), nb);
      offset += 30 + nb.length + data.length;
    }
    const cdSize = central.reduce((a, p) => a + p.length, 0);
    const end = new DataView(new ArrayBuffer(22));
    end.setUint32(0, 0x06054b50, true); end.setUint16(8, files.length, true); end.setUint16(10, files.length, true);
    end.setUint32(12, cdSize, true); end.setUint32(16, offset, true);
    const all = [...parts, ...central, new Uint8Array(end.buffer)];
    const out = new Uint8Array(all.reduce((a, p) => a + p.length, 0));
    let o = 0; for (const p of all) { out.set(p, o); o += p.length; }
    return out;
  }
  function toDocx(m, opts) {
    return zip([
      ["[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'],
      ["_rels/.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'],
      ["word/document.xml", documentXml(m, opts)],
    ]);
  }

  return { parseTranscript, toPromptText, fmtTs, parseTs, buildPrompt, normalize, toMarkdown, toDocx, TYPES };
})();
if (typeof module !== "undefined") module.exports = TK;
