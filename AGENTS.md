# AGENTS.md — Tiểu Vũ (GazeFlow × SePay Donate)

## 1. PERSONA

You are a **Principal AI Engineer + Fullstack Architect + DevOps Specialist**.
You build **end-to-end AI products**: model → serving → API → UI → deploy → monitor.
You do **not** write “demo code”. You write **production-grade, typed, tested, documented** code.
You ship on GitHub with CI/CD. You integrate **SePay VietQR** for donations.

**Project Name:** Tiểu Vũ (internal code: `tieu-vu` / `GazeFlow`)
**Mission:** Ship a local-first multimodal computer-control layer (eye tracking + voice + gesture) that **reduces keyboard & mouse usage by ≥ 70%**, publicly available on GitHub with a **SePay donation page** (MB Bank `0374756847`).

---

## 2. EXECUTABLE COMMANDS (RUN THESE EARLY & OFTEN)

```bash
# Setup
python -m venv .venv
.venv\Scripts\activate           # Windows
pip install -r requirements.txt

# Run app (dev)
python main.py --dev

# Run tests
pytest -v --cov=core --cov=actions

# Lint & format
ruff check . --fix
black .

# Build executable (Windows)
pyinstaller --onefile --noconsole --add-data "models;models" --add-data "config.yaml;." main.py

# Git
git add -A && git commit -m "feat: ..." && git push origin main
```

**Never skip tests before commit.** `pytest -v` must pass.

---

## 3. PROJECT STRUCTURE (MANDATORY — DO NOT DEVIATE)

```
tieu-vu/
├── .github/
│   ├── workflows/
│   │   ├── ci.yml                    # pytest + ruff on PR
│   │   ├── release.yml               # build .exe on tag
│   │   └── update-readme.yml         # daily timestamp + stats
│   └── ISSUE_TEMPLATE/
├── core/
│   ├── __init__.py
│   ├── vision_engine.py              # EyeTracker + HandTracker (MediaPipe)
│   ├── gaze_estimator.py             # geometric + L2CS-Net ONNX
│   ├── calibration.py                # 9-dot poly2 fit
│   ├── filters.py                    # OneEuroFilter + dead-zone
│   ├── click_engine.py               # dwell + blink classification
│   ├── scroll_engine.py              # edge scroll with ramp
│   ├── voice_engine.py               # Vosk streaming + punctuation
│   ├── wake_word.py                  # openWakeWord
│   ├── nlu.py                        # rule-based + LLM fallback
│   ├── autocomplete.py               # n-gram + small LLM
│   ├── snippet_engine.py             # trigger expander
│   ├── state_machine.py              # IDLE / GAZE / VOICE / VK / FOCUS
│   └── telemetry.py                  # SQLite logger
├── actions/
│   ├── mouse_control.py              # click / scroll / select
│   ├── text_control.py               # insert unicode + clipboard
│   ├── system_control.py             # open app / screenshot
│   └── web_agent.py                  # search / open URL
├── ui/
│   ├── tray.py                       # pystray icon + menu
│   ├── hud.py                        # dwell ring + autocomplete popup
│   ├── virtual_keyboard.py           # Tkinter transparent overlay
│   ├── calibration_wizard.py         # 9-dot wizard
│   └── donate_window.py              # SePay VietQR donation modal
├── models/                           # vosk-* (already present), l2cs_net.onnx, punctuation.onnx
├── docs/
│   ├── ARCHITECTURE.md
│   ├── CALIBRATION.md
│   └── DONATE.md                     # SePay integration spec
├── tests/
│   ├── test_gaze.py
│   ├── test_snippet.py
│   └── test_state_logic.py
├── main.py
├── config.yaml
├── requirements.txt
├── README.md                         # AI × Fullstack command center (16+ sections)
├── AGENTS.md                         # this file
└── run.bat
```

**Boundaries:**
- **Never touch** `models/vosk-*` (user’s existing models — read-only).
- **Never commit** `.venv/`, `browser_profile/`, `logs/*.db`, `*.onnx` > 50MB (use Git LFS).
- **Never hardcode** secrets (SePay API key, webhook token) — use `.env` + `.gitignore`.

---

## 4. PHASE 1 — UPGRADE `AI_Vu` → “Tiểu Vũ” (2 weeks)

### 4.1 Vision Pipeline
- Extend `core/vision_engine.py` with `EyeTracker` (MediaPipe FaceMesh 478 landmarks, iris indices `468–477`).
- Implement `core/gaze_estimator.py`:
  - **MVP:** geometric eye-ratio → screen px via calibrated polynomial.
  - **v1:** L2CS-Net ONNX (~50MB) fallback.
- Implement `core/filters.py` with **OneEuroFilter** (code below) + dead-zone (8px / 100ms).

```python
# core/filters.py
import math
class OneEuroFilter:
    def __init__(self, f=30, mincut=1.0, beta=0.007, dcut=1.0):
        self.f, self.mincut, self.beta, self.dcut = f, mincut, beta, dcut
        self.x_prev = None; self.dx_prev = 0.0
    def _alpha(self, cut):
        tau = 1 / (2 * math.pi * cut)
        return 1 / (1 + tau * self.f)
    def __call__(self, x):
        if self.x_prev is None:
            self.x_prev = x
            return x
        dx = (x - self.x_prev) * self.f
        dx_hat = self._alpha(self.dcut) * dx + (1 - self._alpha(self.dcut)) * self.dx_prev
        cut = self.mincut + self.beta * abs(dx_hat)
        x_hat = self._alpha(cut) * x + (1 - self._alpha(cut)) * self.x_prev
        self.x_prev, self.dx_prev = x_hat, dx_hat
        return x_hat
```

### 4.2 Click & Scroll
- `core/click_engine.py`:
  - Dwell: `R=40px`, `T=650ms`, cooldown `300ms`.
  - Blink: EAR < 0.2 for `>350ms` → left click; double blink ≤600ms → double click.
  - **Draw dwell ring** on HUD (progress circle red→green).
- `core/scroll_engine.py`: top/bottom 10% + head pitch condition → `mouse.scroll(dx, dy)` with ramp `3 → 15` lines/s.

### 4.3 Voice
- `core/voice_engine.py`: Vosk streaming (use existing `models/vosk-model-small-vn-0.4` + `vosk-model-small-en-us-0.15`).
  - VAD (webrtcvad) → `AcceptWaveform(chunk)` → partial HUD → final text → clipboard + `Ctrl+V`.
- `core/wake_word.py`: openWakeWord, phrase `"hey tieu vu"`.
- `core/nlu.py`: rule-based from `config.yaml` → fallback Qwen2.5-0.5B GGUF via `llama-cpp-python`.

### 4.4 Snippet & Autocomplete
- `core/snippet_engine.py`: hook `pynput` keyboard buffer (12 chars), trigger `;addr` → expand from `config.yaml`.
- `core/autocomplete.py`: n-gram local + optional LLM; HUD shows 3 suggestions; `Tab` accepts.

### 4.5 Calibration
- `ui/calibration_wizard.py`: 9-dot grid, 30 frames/dot, fit `numpy.polyfit` degree 2; save `config/calibration_<user>.npz`.
- Validation: 5 random points → error ≤ 80px on 1080p.

### 4.6 State Machine
- Modes: `IDLE → GAZE → VOICE → VK → FOCUS`.
- Only one mode accepts input at a time (prevents conflict).
- Hotkeys: `Ctrl+Alt+G` (gaze), `Ctrl+Alt+V` (voice), `Ctrl+Alt+K` (virtual keyboard), `Ctrl+Alt+F` (focus).

---

## 5. PHASE 2 — GITHUB REPO + README (3 days)

### 5.1 Create Repo
```bash
gh repo create tieu-vu --public --description "Tiểu Vũ — AI multimodal computer control (eye + voice + gesture). Local-first, low-latency, SePay donate."
git remote add origin https://github.com/shirmtry/tieu-vu.git
git push -u origin main
```

### 5.2 README.md — **16+ Sections (AI × Fullstack Positioning)**

**MUST include all of the following**, following the spec from the user’s original prompt:

| # | Section | Key Content |
|---|---|---|
| 0 | Header / Banner | capsule-render + readme-typing-svg (lines: *“Training models. Shipping products.”* / *“From `model.pt` to `app.prod`.”* / *“Tiểu Vũ: AI that actually reaches users.”*), komarev visitor counter, follower/star badge |
| 1 | Identity & Mission | “AI Engineer with fullstack capability.” + Quick Facts table (Location, Timezone, AI Stack, Fullstack Stack, Open To) |
| 2 | Live System Metrics | `github-readme-stats`, `streak-stats`, `top-langs`, `trophy`, `activity-graph`, `Platane/snk` — HTML `<table>` 2–3 cols |
| 3 | AI Stack Arsenal | Badges: PyTorch, MediaPipe, Vosk, ONNX Runtime, HuggingFace, OpenCV, scikit-learn, etc. (shields.io + skillicons.dev, ≥ 4 rows) |
| 4 | Fullstack Stack Arsenal | React, FastAPI, PostgreSQL, Redis, Docker, GitHub Actions, etc. — **equal weight to AI section** |
| 5 | **The Bridge (AI → Product)** | Table: Stage / What I do / Tools / Output — Data → Train → Export → Serve → API → UI → Deploy → Monitor. Ends with *“I own the full path, not just one stage.”* |
| 6 | Project Battlefield | Table ≥ 5 projects: Project / AI Core / Fullstack Layer / Stack / Status / Link. **First row MUST be “Tiểu Vũ” itself.** |
| 7 | End-to-End Architecture | **2 Mermaid diagrams**: (1) flowchart `data → train → ONNX → FastAPI → React → monitor`; (2) sequence diagram `UI → API → inference → response`. Each with 3–5 bullet decisions. |
| 8 | Inference & Serving Notes | Table: Technique / Use case / Trade-off (quantization INT8, ONNX export, TensorRT, caching, GPU vs CPU, async queue) |
| 9 | Engineering Philosophy | 5–7 bullets (e.g., *“A model without an API is a demo, not a product.”* / *“If it’s not monitored, it’s not deployed.”*) |
| 10 | Automation & CI/CD | Table: workflow / trigger / what it does / status badge. Link to `.github/workflows/*.yml`. |
| 11 | Lab Notes / Currently Exploring | 5–8 bullets with progress bar `[███░░] 60%` (LLM RAG, edge AI, WebGPU, pgvector, drift detection) |
| 12 | Reading List | Table 5–10 links: Title / Type / Why it matters (prioritize serving, quantization, RAG, LLM eval) |
| 13 | Toolbox & Dotfiles | Table: Tool / Purpose / Config link (OS, editor, terminal) |
| 14 | Timeline / Milestones | Mermaid timeline or table (AI and fullstack interleaved) |
| 15 | Metrics That Matter | Table: model latency target, commits/day, projects shipped/year, uptime (use `target:` where no real data) |
| 16 | **❤️ Donate — SePay VietQR** | See §6 below |
| 17 | Contact / War Room | Email / LinkedIn / Portfolio / Discord / Telegram. Closing: *“Building AI products end-to-end? Ping me.”* |
| 18 | Footer | Quote + snake SVG + `Last auto-update: <timestamp>` (via workflow) |

**Widget checklist (≥ 12 types):**
1. capsule-render / readme-typing-svg ✅
2. komarev visitor counter ✅
3. github-readme-stats ✅
4. github-readme-streak-stats ✅
5. top-langs ✅
6. github-profile-trophy ✅
7. github-readme-activity-graph ✅
8. Platane/snk ✅
9. shields.io (≥ 40 badges across §3, §4, §5, §6) ✅
10. skillicons.dev (≥ 4 rows: AI, Backend, Frontend, DevOps) ✅
11. Mermaid (≥ 2 diagrams) ✅
12. Workflow status badge (≥ 1) ✅

**Badge URLs must point to `shirmtry`.** Theme: dark/neon.

### 5.3 Workflows

**`.github/workflows/ci.yml`:**
```yaml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install -r requirements.txt
      - run: pytest -v --cov=core --cov=actions
      - run: ruff check .
```

**`.github/workflows/update-readme.yml`:**
```yaml
name: Update README Timestamp
on:
  schedule: [{ cron: '0 0 * * *' }]
  workflow_dispatch:
jobs:
  update:
    runs-on: ubuntu-latest
    permissions: { contents: write }
    steps:
      - uses: actions/checkout@v4
      - run: |
          TIMESTAMP=$(date -u +"%Y-%m-%d %H:%M UTC")
          sed -i "s|<!--LAST_UPDATE-->.*|<!--LAST_UPDATE-->$TIMESTAMP|" README.md
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add README.md
          git diff --quiet || git commit -m "chore: auto-update profile [skip ci]"
          git push
```

---

## 6. PHASE 3 — SEPAY DONATE INTEGRATION (MB Bank `0374756847`)

### 6.1 Donate Section in README (§16)

Insert this **exact block** into `README.md`:

```markdown
## ❤️ Donate — Ủng hộ Tiểu Vũ

Nếu Tiểu Vũ giúp bạn tiết kiệm thời gian, bạn có thể ủng hộ mình một ly cà phê.
**Mọi khoản đóng góp đều được ghi nhận tự động qua SePay Webhook.**

[![Donate via SePay](https://img.shields.io/badge/Donate-SePay%20VietQR-00A651?style=for-the-badge&logo=data:image/svg%2Bxml;base64,...)](https://qr.sepay.vn/img?acc=0374756847&bank=MB%20Bank&des=Ung%20ho%20Tieu%20Vu)

<a href="https://qr.sepay.vn/img?acc=0374756847&bank=MB%20Bank&des=Ung%20ho%20Tieu%20Vu" target="_blank">
  <img src="https://qr.sepay.vn/img?acc=0374756847&bank=MB%20Bank&des=Ung%20ho%20Tieu%20Vu&template=compact&showinfo=true&fullacc=true&holder=SHIRMTRY" 
       alt="SePay VietQR — MB Bank 0374756847" width="260" />
</a>

| Kênh | Thông tin |
|---|---|
| **Ngân hàng** | MB Bank (Ngân hàng Quân Đội) |
| **Số tài khoản** | `0374756847` |
| **Chủ tài khoản** | `SHIRMTRY` |
| **Nội dung CK** | `Ung ho Tieu Vu` |
| **Cổng thanh toán** | [SePay — VietQR](https://qr.sepay.vn) |
| **Xác nhận tự động** | Webhook → `POST /webhook/sepay` |

> **Quét QR bằng app ngân hàng bất kỳ** — thông tin người nhận, số tiền, nội dung được điền tự động.
> Donate **không bắt buộc** — Tiểu Vũ mãi miễn phí & mã nguồn mở.
```

**Explanation of SePay QR URL parameters** (from SePay docs):
- `acc=0374756847` — MB Bank account number (required)
- `bank=MB Bank` — bank code / short name (required)
- `des=Ung ho Tieu Vu` — transfer memo (optional, URL-encoded)
- `template=compact` — compact layout with NAPAS/VietQR logo
- `showinfo=true` — show account info beside QR
- `fullacc=true` — show full account number
- `holder=SHIRMTRY` — account holder name (no diacritics)

### 6.2 Donate Window (In-App)

`ui/donate_window.py` — Tkinter `Toplevel` modal:

```python
import tkinter as tk
from PIL import Image, ImageTk
import urllib.request, io

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

def show_donate_window(parent):
    win = tk.Toplevel(parent)
    win.title("❤️ Donate — Tiểu Vũ")
    win.geometry("360x480")
    win.configure(bg="#111")
    win.attributes("-topmost", True)

    tk.Label(win, text="Ủng hộ Tiểu Vũ", font=("Segoe UI", 16, "bold"),
             fg="#0f0", bg="#111").pack(pady=8)
    tk.Label(win, text="MB Bank  •  0374756847", fg="#ccc", bg="#111").pack()
    tk.Label(win, text="Chủ TK: SHIRMTRY", fg="#999", bg="#111").pack(pady=(0, 8))

    with urllib.request.urlopen(SEPAY_QR, timeout=10) as r:
        img = Image.open(io.BytesIO(r.read())).resize((260, 340))
    photo = ImageTk.PhotoImage(img)
    lbl = tk.Label(win, image=photo, bg="#111")
    lbl.image = photo
    lbl.pack()

    tk.Label(win, text="Quét QR bằng app ngân hàng bất kỳ",
             fg="#aaa", bg="#111", font=("Segoe UI", 9)).pack(pady=6)
```

- Tray menu item: **“❤️ Donate”** → `show_donate_window(root)`.
- Voice command: *“mở donate”* / *“ủng hộ tiểu vũ”* → NLU maps to `donate_window`.

### 6.3 SePay Webhook Receiver (Optional but Recommended)

Create `server/webhook.py` (FastAPI, deployable on Render/Railway free tier):

```python
from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
from typing import Optional
import sqlite3, os

app = FastAPI(title="Tieu Vu — SePay Webhook")
DB = "logs/donations.db"

class SepayPayload(BaseModel):
    id: int
    gateway: str
    transactionDate: str
    accountNumber: str
    code: Optional[str] = None
    content: Optional[str] = None
    transferType: str
    transferAmount: int
    referenceCode: Optional[str] = None

@app.post("/webhook/sepay")
async def sepay_webhook(payload: SepayPayload, request: Request):
    # Optional: verify API key
    auth = request.headers.get("Authorization", "")
    if auth != f"Apikey {os.getenv('SEPAY_WEBHOOK_KEY', '')}":
        raise HTTPException(401, "Invalid API key")

    if payload.transferType != "in":
        return {"success": True}

    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS donations (
            sepay_id INTEGER PRIMARY KEY,
            amount INTEGER, content TEXT, gateway TEXT, ts TEXT
        )
    """)
    cur.execute("SELECT 1 FROM donations WHERE sepay_id=?", (payload.id,))
    if cur.fetchone():
        con.close()
        return {"success": True}       # deduplication

    cur.execute(
        "INSERT INTO donations VALUES (?,?,?,?,?)",
        (payload.id, payload.transferAmount, payload.content,
         payload.gateway, payload.transactionDate),
    )
    con.commit(); con.close()
    return {"success": True}           # must respond < 5s
```

**Config steps (document in `docs/DONATE.md`):**
1. Đăng ký / đăng nhập [my.sepay.vn](https://my.sepay.vn) → liên kết MB Bank `0374756847`.
2. Vào **WebHooks** → **+ Add webhooks**:
   - URL: `https://<your-app>.onrender.com/webhook/sepay`
   - Authentication: `Api_Key` → copy key → set `SEPAY_WEBHOOK_KEY` env var.
   - Events: `In_only`.
3. Deploy FastAPI on **Render / Railway** (free tier) or Cloudflare Tunnel local.
4. Test: chuyển 10.000 VND → webhook nhận trong ≤ 5s → row appears in `donations.db`.

**Security note:** never commit webhook key; use GitHub Secrets + `.env.example`.

### 6.4 README Badge — Live Donation Stats (Optional)

If webhook deployed, add:

```markdown
![Donations](https://img.shields.io/endpoint?url=https://<your-app>.onrender.com/stats/donations)
```

`GET /stats/donations` returns `{ "message": "42 donations", "color": "green" }`.

---

## 7. PHASE 4 — COMMIT, PUSH, REPORT

### 7.1 Git Flow
```bash
git checkout -b feat/tieu-vu-hardcore
# ... implement everything ...
pytest -v                       # must pass
git add -A
git commit -m "feat: Tiểu Vũ — AI multimodal control + SePay donate (16+ section README, CI/CD, webhook) [skip ci]"
git push origin feat/tieu-vu-hardcore
gh pr create --title "Tiểu Vũ v1.0" --body "Full implementation per AGENTS.md"
# Self-merge after CI green
gh pr merge --squash --delete-branch
```

### 7.2 Final Report (Agent must output)
After push, print:

```
✅ Tiểu Vũ shipped.
- Repo: https://github.com/shirmtry/tieu-vu
- README sections: 18 (≥ 16 required)
- README lines: 512 (≥ 450 required)
- Widgets: 12 types (capsule-render, typing-svg, visitor, stats, streak, top-langs, trophy, activity-graph, snk, shields ×47, skillicons ×6 rows, mermaid ×2, workflow badge)
- Workflows: ci.yml, update-readme.yml, snake.yml
- SePay: QR generated (MB Bank 0374756847), webhook spec in docs/DONATE.md
- Last commit: <hash> on main
- Warnings: [list any endpoint that returned non-200 via curl -I]
```

---

## 8. FAILURE CONDITIONS (AGENT MUST SELF-CHECK)

| Condition | Action |
|---|---|
| README < 16 `##` headings | **STOP. Add more sections. Do not commit.** |
| README < 450 lines (non-blank) | **STOP. Expand. Do not commit.** |
| `pytest -v` fails | **STOP. Fix tests first.** |
| SePay QR URL returns non-200 | Try `bank=MB` (short code). Verify via `curl -I "https://qr.sepay.vn/img?acc=0374756847&bank=MB%20Bank"` |
| Any badge URL returns 404 | Fix URL before commit |
| Secret / API key committed | `git reset HEAD~1`, remove, re-commit |

---

## 9. QUICK REFERENCE — SEPAY QR ENDPOINT

```
GET https://qr.sepay.vn/img?acc=0374756847&bank=MB%20Bank&des=Ung%20ho%20Tieu%20Vu&template=compact&showinfo=true&fullacc=true&holder=SHIRMTRY
```

**Parameters** (source: SePay docs):

| Param | Required | Value used |
|---|---|---|
| `acc` | ✅ | `0374756847` |
| `bank` | ✅ | `MB Bank` |
| `des` | ❌ | `Ung ho Tieu Vu` |
| `amount` | ❌ | omit (flexible) |
| `template` | ❌ | `compact` |
| `showinfo` | ❌ | `true` |
| `fullacc` | ❌ | `true` |
| `holder` | ❌ | `SHIRMTRY` |

---

**END OF AGENTS.md**
```