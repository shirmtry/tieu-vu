# =====================================================================
# actions/web_agent.py
# Tu dong hoa Web AI (tuy chon): dung Playwright mo trinh duyet (co the
# an), gui prompt len DeepSeek/ChatGPT web, cho phan hoi, trich innerText
# (van ban thuan) va nap vao clipboard plain text.
#
# Chay trong thread rieng voi hang doi prompt -> khong block vision/voice.
# Luu y: lan dau can dang nhap thu cong (headless=false), profile duoc luu
# lai trong user_data_dir cho cac lan sau.
# =====================================================================
from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Optional

from core.state_machine import ActionEvent

log = logging.getLogger(__name__)


class WebAgent(threading.Thread):
    def __init__(self, config: dict, text_controller,
                 event_queue: "Optional[queue.Queue[ActionEvent]]" = None):
        super().__init__(name="WebAgent", daemon=True)
        self.cfg = config.get("web_agent", {})
        self.enabled = bool(self.cfg.get("enabled", False))
        self.text = text_controller
        self.event_queue = event_queue
        # Hang doi tac vu: ("prompt", text) hoac ("email", "").
        self.prompt_queue: "queue.Queue[tuple]" = queue.Queue()
        self.stop_event = threading.Event()
        self.busy = False
        self.last_result: str = ""
        self._pw = None
        self._context = None
        self._page = None

    # ------------------------------------------------------------------
    def submit(self, prompt: str):
        """Day prompt noi vao hang doi (goi tu bat ky thread nao)."""
        if not self.enabled:
            log.warning("WebAgent chua bat (web_agent.enabled=false trong config).")
            return
        self.prompt_queue.put(("prompt", prompt))
        log.info("WebAgent nhan prompt: '%s'", prompt[:80])

    def submit_email(self):
        """Xu ly van ban trong clipboard bang AI (lenh 'xu ly email').

        Noi dung clipboard (email/web vua copy) se duoc gui kem prompt mau
        toi DeepSeek; ket qua tra ve nap lai vao clipboard plain text.
        """
        if not self.enabled:
            log.warning("WebAgent chua bat (web_agent.enabled=false trong config).")
            return
        self.prompt_queue.put(("email", ""))
        log.info("WebAgent nhan yeu cau xu ly clipboard (email).")

    def stop(self):
        self.stop_event.set()

    # ------------------------------------------------------------------
    def run(self):
        if not self.enabled:
            log.info("WebAgent bi tat trong config.")
            return
        while not self.stop_event.is_set():
            try:
                kind, payload = self.prompt_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            self.busy = True
            try:
                if kind == "email":
                    self._handle_email()
                else:
                    self._send_and_capture(payload)
            except Exception as exc:
                log.exception("WebAgent loi: %s", exc)
            finally:
                self.busy = False
        self._cleanup()
        log.info("WebAgent da dung.")

    # ------------------------------------------------------------------
    def _init_browser(self) -> bool:
        if self._page is not None:
            return True
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            log.error("Chua cai playwright. Chay: pip install playwright "
                      "&& playwright install chromium")
            return False
        try:
            self._pw = sync_playwright().start()
            browser_type = getattr(self._pw, self.cfg.get("browser", "chromium"))
            self._context = browser_type.launch_persistent_context(
                self.cfg.get("user_data_dir", "browser_profile"),
                headless=bool(self.cfg.get("headless", True)),
                viewport={"width": 1280, "height": 900},
                args=["--disable-blink-features=AutomationControlled"],
            )
            self._page = self._context.pages[0] if self._context.pages \
                else self._context.new_page()
            log.info("WebAgent: trinh duyet san sang.")
            return True
        except Exception as exc:
            log.exception("Khong khoi tao duoc trinh duyet: %s", exc)
            self._cleanup()
            return False

    # ------------------------------------------------------------------
    def _handle_email(self):
        """Lenh 'xu ly email': lay clipboard -> gui AI kem prompt mau."""
        content = self.text.get_clipboard_text().strip()
        if not content:
            log.warning("WebAgent: clipboard rong - hay copy email/web truoc "
                        "khi noi 'xu ly email'.")
            return
        template = self.cfg.get(
            "email_prompt",
            "Hãy trả lời email này một cách chuyên nghiệp, lịch sự, bằng tiếng "
            "Việt. Chỉ trả về nội dung email trả lời, không giải thích thêm.")
        prompt = f"{template}\n\n--- NỘI DUNG EMAIL ---\n{content}"
        log.info("WebAgent: xu ly email (%d ky tu clipboard).", len(content))
        self._send_and_capture(prompt)

    # ------------------------------------------------------------------
    def _send_and_capture(self, prompt: str):
        """Loi chung: mo trang -> dien prompt -> cho tra loi -> clipboard."""
        if not prompt or not self._init_browser():
            return
        page = self._page
        url = self.cfg.get("target_url", "https://chat.deepseek.com")
        prompt_sel = self.cfg.get("prompt_selector", "textarea#chat-input")
        resp_sel = self.cfg.get("response_selector", "div.ds-markdown")
        timeout = float(self.cfg.get("response_timeout_sec", 90))

        # Dieu huong neu chua o trang dich.
        if not page.url.startswith(url.split("?")[0]):
            page.goto(url, wait_until="domcontentloaded", timeout=60000)

        try:
            box = page.wait_for_selector(prompt_sel, timeout=20000)
        except Exception:
            log.error("Khong tim thay o nhap prompt '%s'. Co the can dang nhap "
                      "(dat headless=false va dang nhap thu cong lan dau).", prompt_sel)
            return

        # Dem so cau tra loi hien co de biet khi nao cau moi xuat hien.
        prev_count = page.locator(resp_sel).count()
        box.fill(prompt)
        box.press("Enter")
        log.info("WebAgent: da gui prompt, cho phan hoi...")

        answer = self._wait_response(page, resp_sel, prev_count, timeout)
        if not answer:
            log.warning("WebAgent: khong lay duoc phan hoi (timeout/loi selector).")
            return

        self.last_result = answer
        if self.text.set_clipboard_text(answer):
            log.info("WebAgent: da nap %d ky tu vao clipboard plain text.", len(answer))
        if self.event_queue is not None:
            self.event_queue.put(ActionEvent(
                "web_result", {"chars": len(answer)}, source="web"))

    # ------------------------------------------------------------------
    def _wait_response(self, page, resp_sel: str, prev_count: int,
                       timeout: float) -> str:
        """Cho cau tra loi moi on dinh (khong con duoc go them).

        Chien thuat: poll innerText cua cau tra loi cuoi cung; khi noi dung
        khong doi trong 2.5s lien tuc -> ket luan da sinh xong.
        """
        deadline = time.time() + timeout
        stable_since: Optional[float] = None
        last_text = ""
        while time.time() < deadline and not self.stop_event.is_set():
            try:
                loc = page.locator(resp_sel)
                count = loc.count()
                # Cho cau tra loi MOI xuat hien (them phan tu so voi luc gui).
                if count > prev_count:
                    text = loc.nth(count - 1).inner_text(timeout=2000)
                    now = time.time()
                    if text and text == last_text:
                        if stable_since is None:
                            stable_since = now
                        elif now - stable_since >= 2.5 and len(text) > 20:
                            return text.strip()
                    else:
                        stable_since = None
                        last_text = text
            except Exception:
                pass  # phan tu chua render xong, poll tiep
            time.sleep(0.5)
        return last_text.strip() if last_text else ""

    # ------------------------------------------------------------------
    def _cleanup(self):
        for obj_name in ("_context", "_pw"):
            obj = getattr(self, obj_name)
            try:
                if obj is not None:
                    obj.close() if obj_name == "_context" else obj.stop()
            except Exception:
                pass
            setattr(self, obj_name, None)
        self._page = None
