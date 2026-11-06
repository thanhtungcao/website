"""Bot vào họp chạy ngay trên máy của bạn (miễn phí, không cần Recall.ai).

Mở một cửa sổ Edge/Chrome bằng Playwright, vào link Google Meet / Zoom / Microsoft Teams
với tên "Thư Ký AI", thu âm thanh cuộc họp ngay trong trang (WebRTC, WebAudio và thẻ
<audio>), gửi từng đoạn về hàng đợi chép lời giống chức năng ghi trực tiếp. Khi cuộc họp
kết thúc (hoặc người dùng bấm Rời họp) thì gọi `on_done` để tạo biên bản.

Cửa sổ bot hiển thị (BOT_HEADLESS=0) để người dùng có thể bấm giúp khi trang họp đổi
giao diện, có captcha, hoặc cần đăng nhập.

Chỉ bật trên máy cá nhân (LOCAL_BOT=1): bot mở trình duyệt trên chính máy chạy máy chủ.
"""
from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
import re
import tempfile
import threading
import time
import wave
from typing import Callable
from urllib.parse import parse_qs, urlparse

from . import config, live, store

log = logging.getLogger("thukyai.bot")

# ---------- Thu âm thanh trong trang họp ----------

CAPTURE_JS = r"""
(() => {
  if (window.__tkInstalled) return;
  window.__tkInstalled = true;
  const CHUNK_MS = __CHUNK_MS__;
  let ctx = null, dest = null, t0 = 0, rec = null, active = false;
  const seen = new WeakSet();
  function ensure() {
    if (ctx) return;
    ctx = new AudioContext();
    dest = ctx.createMediaStreamDestination();
    const keep = ctx.createConstantSource(), mute = ctx.createGain();   // giữ luồng ghi luôn có dữ liệu
    mute.gain.value = 0; keep.connect(mute); mute.connect(dest); keep.start();
  }
  function addStream(stream) {
    try {
      ensure();
      for (const tr of stream.getAudioTracks()) {
        if (seen.has(tr)) continue;
        seen.add(tr);
        ctx.createMediaStreamSource(new MediaStream([tr])).connect(dest);
      }
    } catch (e) { console.warn("[tk] addStream", e); }
  }
  // 1) Âm thanh WebRTC từ người khác (Google Meet, Teams)
  const PC = window.RTCPeerConnection;
  if (PC) {
    const Wrapped = function (...args) {
      const pc = new PC(...args);
      pc.addEventListener("track", (e) => { if (e.track.kind === "audio") addStream(e.streams[0] || new MediaStream([e.track])); });
      return pc;
    };
    Wrapped.prototype = PC.prototype;
    Object.setPrototypeOf(Wrapped, PC);
    window.RTCPeerConnection = Wrapped;
    if (window.webkitRTCPeerConnection) window.webkitRTCPeerConnection = Wrapped;
  }
  // 2) Âm thanh phát qua WebAudio ra loa (Zoom web client)
  const origConnect = AudioNode.prototype.connect;
  const taps = new WeakMap();
  AudioNode.prototype.connect = function (target, ...rest) {
    const r = origConnect.call(this, target, ...rest);
    try {
      if (target instanceof AudioDestinationNode && this.context !== ctx) {
        let tap = taps.get(this.context);
        if (!tap) { tap = this.context.createMediaStreamDestination(); taps.set(this.context, tap); addStream(tap.stream); }
        origConnect.call(this, tap);
      }
    } catch (e) {}
    return r;
  };
  // 3) Thẻ <audio>/<video> phát MediaStream
  const desc = Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype, "srcObject");
  if (desc && desc.set) {
    Object.defineProperty(HTMLMediaElement.prototype, "srcObject", {
      ...desc,
      set(v) { if (v instanceof MediaStream) addStream(v); return desc.set.call(this, v); },
    });
  }
  function cycle() {
    if (!active) return;
    const parts = [], off = (performance.now() - t0) / 1000;
    const r = new MediaRecorder(dest.stream, { mimeType: "audio/webm;codecs=opus", audioBitsPerSecond: 48000 });
    rec = r;
    r.ondataavailable = (e) => { if (e.data.size) parts.push(e.data); };
    r.onstop = async () => {
      const blob = new Blob(parts, { type: "audio/webm" });
      if (blob.size > 1500) {
        const b = new Uint8Array(await blob.arrayBuffer());
        let s = "";
        for (let i = 0; i < b.length; i += 0x8000) s += String.fromCharCode.apply(null, b.subarray(i, i + 0x8000));
        try { await window.tkChunk(btoa(s), off); } catch (e) { console.warn("[tk] send", e); }
      }
      if (active) cycle(); else if (window.__tkDone) window.__tkDone();
    };
    r.start();
    setTimeout(() => r.state !== "inactive" && r.stop(), CHUNK_MS);
  }
  window.__tkStart = () => { ensure(); if (ctx.state === "suspended") ctx.resume(); if (active) return; active = true; t0 = performance.now(); cycle(); };
  window.__tkStop = () => new Promise((res) => {
    active = false; window.__tkDone = res;
    if (rec && rec.state !== "inactive") rec.stop(); else res();
    setTimeout(res, 5000);
  });
})();
"""

# ---------- Nhận diện nền tảng và link ----------

def detect(url: str) -> str:
    from .invite import platform_of
    return platform_of(url)


PLATFORM_NAMES = {"meet": "Google Meet", "zoom": "Zoom", "teams": "Microsoft Teams", "generic": "Trang họp"}


def join_url(url: str, platform: str) -> str:
    """Zoom: chuyển link /j/<id>?pwd=... sang web client để không phải cài app."""
    if platform != "zoom":
        return url
    u = urlparse(url)
    m = re.search(r"/(?:j|w|s|wc/join|wc)/(\d{9,12})", u.path)
    if not m:
        return url
    pwd = parse_qs(u.query).get("pwd", [""])[0]
    return f"https://app.zoom.us/wc/join/{m.group(1)}" + (f"?pwd={pwd}" if pwd else "")


# ---------- Thao tác vào họp theo từng nền tảng (giao diện tiếng Anh) ----------

def _rx(*words: str) -> re.Pattern:
    return re.compile("|".join(words), re.I)


async def _click(page, pattern: re.Pattern, role: str = "button", timeout: float = 4000) -> bool:
    for frame in page.frames:
        loc = frame.get_by_role(role, name=pattern).first
        try:
            await loc.click(timeout=timeout / max(len(page.frames), 1))
            return True
        except Exception:
            continue
    return False


async def _fill_name(page, name: str, selectors: list[str]) -> bool:
    for frame in page.frames:
        for sel in selectors:
            loc = frame.locator(sel).first
            try:
                if await loc.is_visible(timeout=500):
                    await loc.fill(name)
                    return True
            except Exception:
                continue
    return False


async def _any_visible(page, pattern: re.Pattern, role: str | None = "button") -> bool:
    for frame in page.frames:
        try:
            loc = frame.get_by_role(role, name=pattern).first if role else frame.get_by_text(pattern).first
            if await loc.is_visible(timeout=300):
                return True
        except Exception:
            continue
    return False


async def _join_meet(page, name: str, passcode: str = "") -> None:
    await _click(page, _rx(r"^got it$", r"^dismiss$"), timeout=2000)
    await _fill_name(page, name, ['input[aria-label="Your name"]', 'input[placeholder*="name" i]', 'input[type="text"]'])
    await _click(page, _rx(r"turn off microphone"), timeout=2000)
    await _click(page, _rx(r"turn off camera"), timeout=2000)
    await _click(page, _rx(r"^ask to join$", r"^join now$", r"^join$", r"^switch here$"), timeout=8000)


async def _join_teams(page, name: str, passcode: str = "") -> None:
    await _click(page, _rx(r"continue on this browser", r"join on the web instead", r"use the web app instead"), timeout=8000)
    await page.wait_for_timeout(3000)
    if passcode and await _fill_name(page, passcode, ['input[placeholder*="passcode" i]', 'input[aria-label*="passcode" i]']):
        await _click(page, _rx(r"^join meeting$", r"^join$", r"^continue$"), timeout=3000)
        await page.wait_for_timeout(3000)
    await _fill_name(page, name, ['input[data-tid="prejoin-display-name-input"]', 'input[placeholder*="name" i]'])
    await _click(page, _rx(r"^camera$"), role="switch", timeout=1500)
    await _click(page, _rx(r"^join now$", r"^join$"), timeout=8000)


async def _join_zoom(page, name: str, passcode: str = "") -> None:
    await _click(page, _rx(r"^i agree$", r"^accept cookies$", r"^accept all cookies$"), timeout=2000)
    if passcode:
        await _fill_name(page, passcode, ["#input-for-pwd", 'input[placeholder*="passcode" i]', 'input[type="password"]'])
    await _fill_name(page, name, ["#input-for-name", 'input[placeholder*="name" i]'])
    await _click(page, _rx(r"^join$"), timeout=8000)


async def _after_join_zoom(page) -> None:
    await _click(page, _rx(r"join audio by computer", r"^join audio$"), timeout=1500)


JOINERS = {"meet": _join_meet, "teams": _join_teams, "zoom": _join_zoom}
IN_CALL = {
    "meet": _rx(r"leave call"),
    "teams": _rx(r"^leave$", r"hang ?up"),
    "zoom": _rx(r"^leave$", r"leave meeting"),
}
LOBBY = _rx(r"asking to be let in", r"someone in the meeting should let you in", r"host will let you in",
            r"waiting for the host", r"please wait", r"you'll join the call when someone lets you in")
ENDED = _rx(r"you've left the (meeting|call)", r"you left the meeting", r"the call (has )?ended", r"meeting (has been )?ended",
            r"removed from the meeting", r"you were removed", r"this meeting has been ended", r"you can't join this (video )?call",
            r"no one responded to your request", r"someone in the call denied your request", r"you've been removed")


# ---------- Bot ----------

class MeetBot:
    def __init__(self, mid: str, url: str, platform: str, hint: str, on_done: Callable[[str, bool], None], passcode: str = ""):
        self.mid, self.url, self.platform, self.hint, self.on_done = mid, url, platform, hint, on_done
        self.passcode = passcode
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._thread, name=f"tk-bot-{mid}", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def _status(self, status: str, error: str | None = None) -> None:
        store.update(self.mid, status=status, error=error)

    def _thread(self) -> None:
        finished = False
        try:
            finished = asyncio.run(self._run())
        except Exception as e:
            log.exception("Bot lỗi (%s)", self.mid)
            self._status("error", f"Bot gặp lỗi: {e}")
        finally:
            _bots.pop(self.mid, None)
        self.on_done(self.mid, finished)  # False: không vào được họp hoặc lỗi

    async def _on_chunk(self, b64: str, offset: float) -> None:
        live.add_chunk(self.mid, base64.b64decode(b64), ".webm", float(offset) + self.offset_base, "system", self.hint)

    async def _launch(self, p):
        args = ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                f"--use-file-for-fake-audio-capture={_silence_wav()}",
                "--autoplay-policy=no-user-gesture-required",
                "--disable-background-timer-throttling", "--disable-renderer-backgrounding",
                "--disable-backgrounding-occluded-windows", "--lang=en-US"]
        opts = dict(headless=config.BOT_HEADLESS, args=args)
        if config.BOT_BROWSER_PATH:
            return await p.chromium.launch(executable_path=config.BOT_BROWSER_PATH, **opts)
        errors = []
        for channel in ("msedge", "chrome", None):
            try:
                return await p.chromium.launch(channel=channel, **opts) if channel else await p.chromium.launch(**opts)
            except Exception as e:
                errors.append(f"{channel or 'chromium'}: {str(e).splitlines()[0]}")
        raise RuntimeError("Không mở được trình duyệt cho bot. Cài Microsoft Edge hoặc Google Chrome, "
                           "hoặc chạy: python -m playwright install chromium. (" + "; ".join(errors) + ")")

    async def _run(self) -> bool:
        from playwright.async_api import async_playwright
        self.offset_base = 0.0
        async with async_playwright() as p:
            browser = await self._launch(p)
            try:
                ctx = await browser.new_context(locale="en-US", viewport={"width": 1280, "height": 800},
                                                permissions=["microphone", "camera"])
                await ctx.expose_function("tkChunk", self._on_chunk)
                await ctx.add_init_script(CAPTURE_JS.replace("__CHUNK_MS__", str(config.BOT_CHUNK_SECONDS * 1000)))
                page = await ctx.new_page()
                self._status("joining")
                await page.goto(join_url(self.url, self.platform), wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(4000)
                joiner = JOINERS.get(self.platform)
                if joiner:
                    try:
                        await joiner(page, config.BOT_NAME, self.passcode)
                    except Exception:
                        log.warning("Không tự bấm vào họp được, chờ người dùng thao tác", exc_info=True)

                # Chờ được cho vào phòng họp
                deadline = time.time() + config.BOT_ADMIT_TIMEOUT_MIN * 60
                while not await self._in_call(page):
                    if self.stop_event.is_set() or page.is_closed():
                        self._status("error", "Đã hủy trước khi vào được cuộc họp.")
                        return False
                    if await _any_visible(page, ENDED, role=None):
                        self._status("error", "Không vào được cuộc họp: người chủ trì từ chối, link sai hoặc cuộc họp đã kết thúc.")
                        return False
                    if time.time() > deadline:
                        self._status("error", f"Chờ quá {config.BOT_ADMIT_TIMEOUT_MIN} phút mà chưa được cho vào. "
                                              "Hãy cho 'Thư Ký AI' vào phòng (admit) rồi thử lại.")
                        return False
                    self._status("waiting" if await _any_visible(page, LOBBY, role=None) else "joining")
                    await page.wait_for_timeout(3000)

                if self.platform == "zoom":
                    await _after_join_zoom(page)
                self._status("recording")
                started = time.time()
                missing = 0
                while True:
                    for frame in page.frames:
                        try:
                            await frame.evaluate("window.__tkStart && window.__tkStart()")
                        except Exception:
                            pass
                    if self.stop_event.is_set() or page.is_closed():
                        break
                    if await _any_visible(page, ENDED, role=None):
                        break
                    missing = 0 if await self._in_call(page) else missing + 1
                    if missing >= 4:          # không còn nút Rời họp khoảng 20 giây: cuộc họp đã kết thúc
                        break
                    if time.time() - started > config.MAX_LIVE_HOURS * 3600:
                        break
                    await page.wait_for_timeout(5000)

                self._status("finishing")
                if not page.is_closed():
                    for frame in page.frames:
                        try:
                            await frame.evaluate("window.__tkStop ? window.__tkStop() : null")
                        except Exception:
                            pass
                    await _click(page, IN_CALL.get(self.platform, _rx(r"^leave")), timeout=2000)
                await asyncio.sleep(1)
                return True
            finally:
                await browser.close()

    async def _in_call(self, page) -> bool:
        if page.is_closed():
            return False
        if self.platform == "generic":
            return True
        return await _any_visible(page, IN_CALL[self.platform])


_bots: dict[str, MeetBot] = {}
_silence_path: str | None = None


def _silence_wav() -> str:
    """Micro giả của bot phát im lặng (thay vì tiếng bíp mặc định của Chrome)."""
    global _silence_path
    if _silence_path and os.path.exists(_silence_path):
        return _silence_path
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 16000)
    fd, path = tempfile.mkstemp(suffix=".wav", prefix="tk-silence-")
    with os.fdopen(fd, "wb") as f:
        f.write(buf.getvalue())
    _silence_path = path
    return path


def unavailable_reason() -> str:
    """Chuỗi rỗng nếu bot dùng được; nếu không thì lý do và cách bật."""
    if not config.LOCAL_BOT:
        return ("Bot tự vào họp chỉ chạy khi mở Thư Ký AI trên máy của bạn bằng chay-tren-may.bat "
                "(hoặc đặt LOCAL_BOT=1).")
    try:
        import playwright  # noqa: F401
    except ImportError:
        return "Thiếu thư viện bot. Chạy lại chay-tren-may.bat, hoặc: pip install -r requirements-bot.txt"
    return ""


def available() -> bool:
    return not unavailable_reason()


def active_count() -> int:
    return len(_bots)


def start(mid: str, url: str, platform: str, hint: str, on_done: Callable[[str, bool], None], passcode: str = "") -> None:
    bot = MeetBot(mid, url, platform, hint, on_done, passcode)
    _bots[mid] = bot
    bot.start()


def stop(mid: str) -> bool:
    bot = _bots.get(mid)
    if not bot:
        return False
    bot.stop_event.set()
    return True
