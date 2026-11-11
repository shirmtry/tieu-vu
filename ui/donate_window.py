# =====================================================================
# ui/donate_window.py
# Modal Tkinter hien VietQR SePay (MB Bank 0374756847, chủ TK SHIRMTRY).
# Tai QR qua https://qr.sepay.vn/img; loi mang -> van hien thong tin CK
# va nut mo link QR bang trinh duyet.
# =====================================================================
from __future__ import annotations

import io
import logging
import threading
import tkinter as tk
import urllib.request
import webbrowser
from typing import Optional

log = logging.getLogger(__name__)

SEPAY_QR = (
    "https://qr.sepay.vn/img"
    "?acc=0374756847"
    "&bank=MB%20Bank"
    "&des=Ung%20ho%20Tieu%20Vu"
    "&template=compact"
    "&showinfo=true"
    "&fullacc=true"
    "&holder=SHIRMTRY"
)


def show_donate_window(parent: Optional[tk.Misc] = None,
                       qr_url: str = SEPAY_QR) -> tk.Toplevel:
    """Mo cua so donate (modal, topmost). Tra ve Toplevel de test/close."""
    root = parent if parent is not None else tk.Tk()
    win = tk.Toplevel(root)
    win.title("❤️ Donate — Tiểu Vũ")
    win.geometry("360x520")
    win.configure(bg="#111")
    win.attributes("-topmost", True)

    tk.Label(win, text="Ủng hộ Tiểu Vũ", font=("Segoe UI", 16, "bold"),
             fg="#0f0", bg="#111").pack(pady=8)
    tk.Label(win, text="MB Bank  •  0374756847", fg="#ccc", bg="#111").pack()
    tk.Label(win, text="Chủ TK: SHIRMTRY", fg="#999", bg="#111").pack(pady=(0, 8))

    holder = tk.Label(win, text="Đang tải VietQR...", fg="#888", bg="#111")
    holder.pack(expand=True)

    def load():
        try:
            with urllib.request.urlopen(qr_url, timeout=10) as r:
                data = r.read()
            from PIL import Image, ImageTk

            img = Image.open(io.BytesIO(data)).resize((260, 340))
            photo = ImageTk.PhotoImage(img)
            holder.configure(image=photo, text="")
            holder.image = photo  # type: ignore[attr-defined]
        except Exception as exc:
            log.warning("Khong tai duoc QR SePay: %s", exc)
            if holder.winfo_exists():
                holder.configure(
                    text="Không tải được QR.\nBấm nút bên dưới để mở trên web.",
                    fg="#f66", wraplength=300)

    threading.Thread(target=load, daemon=True).start()

    tk.Label(win, text="Quét QR bằng app ngân hàng bất kỳ",
             fg="#aaa", bg="#111", font=("Segoe UI", 9)).pack(pady=6)
    tk.Button(win, text="Mở VietQR trên web", bg="#0a3", fg="white",
              relief="flat", command=lambda: webbrowser.open(qr_url)
              ).pack(pady=(0, 10), ipadx=10, ipady=4)
    return win
