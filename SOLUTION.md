# SOLUTION — Tiểu Vũ → Voice-Driven AI Coder Assistant

Tài liệu này tóm tắt thay đổi kiến trúc của bản nâng cấp "AI coder mode"
(6 phase), cách cài dependency và các điểm cần biết khi vận hành.

---

## 1. Trước / Sau

### Trước

```
Voice (Vosk) ──► NLU rule-based ──► ActionEvent ──► action_queue ──► ActionWorker
                    └─ Qwen2.5-0.5B GGUF (fallback, yếu)              │
                                                                      ▼
                                     Mouse / System / Text / Web controllers
```

- Không có TTS.
- Không có coding action.
- Mode: IDLE / GAZE / VOICE / VK / FOCUS.

### Sau

```
Mic ──► Vosk (wake-word, streaming)
          │ wake
          ▼
        buffer PCM ──► PhoWhisper-small (transcribe) ──► transcript
                                                          │
              ┌───────────────────────────────────────────┤
              ▼                                           ▼
     Mode.CODE? ──► CoderNLU (Ollama qwen2.5-coder)   NLU rule-based
              │            │ tool_calls                   │
              └────────────┴──────────► ActionEvent ──► action_queue ──► ActionWorker
                                                                          │
                        ┌───────────────┬─────────────────┬───────────────┤
                        ▼               ▼                 ▼               ▼
                   CoderActions   VieNeu TTS      controllers cũ    delegate thread
                   (file/cmd/git)  (speak)        (gaze/gesture)    OpenCode/Aider
```

Nguyên tắc giữ nguyên:

- **Single action queue, one owner**: mọi action mới vẫn đi qua `ActionEvent`
  → `action_queue` → `ActionWorker`.
- **Mode exclusivity**: thêm `Mode.CODE`; chỉ một mode nhận input tại một thời
  điểm. CODE nhận voice, khóa gesture/gaze.
- **Fail-safe optional deps**: PhoWhisper, VieNeu, Ollama, OpenCode/Aider đều
  lazy-import; thiếu thì degrade, không crash.
- **Local-first**: không có cloud LLM. Thiếu Ollama → fallback rule-based.

---

## 2. Thay đổi theo phase

| Phase | Nội dung | File chính |
|---|---|---|
| 1 | Hybrid STT: Vosk wake + PhoWhisper transcribe buffer | `core/voice/stt_phowhisper.py`, `core/voice_engine.py` |
| 2 | TTS tiếng Việt (VieNeu → pyttsx3), action `speak`, câu trả lời NLU | `core/voice/tts_vieneu.py`, `core/nlu.py`, `main.py` |
| 3 | Coder NLU qua Ollama tool-calling (6 tool) | `core/coder_tools.py`, `core/nlu_coder.py` |
| 4 | Coding actions + async (không block ActionWorker) | `actions/coder_actions.py`, `main.py` |
| 5 | `Mode.CODE` + hotkey `Ctrl+Alt+C` + routing voice | `core/state_machine.py`, `core/voice_engine.py`, `main.py` |
| 6 | Delegate OpenCode / Aider + integration test | `core/coder_backend.py`, `tests/test_integration_coder.py` |

### Coder tools

`create_file`, `run_command`, `git_commit`, `search_code`, `explain_code`,
`delegate_to_coder`.

### An toàn

- Mọi path được resolve và phải nằm trong `coder.workspace_root`
  (`core/coder_tools.resolve_workspace_path`). Chặn `../` và absolute path
  ngoài workspace.
- `run_command` chỉ chạy executable trong `coder.allowed_commands`; chặn toán
  tử shell (`&&`, `|`, `;`, `>`, ...).
- Task dài (`run_command`, `explain_code`, `delegate_to_coder`) chạy thread
  riêng, kết quả đẩy lại queue dưới dạng `ActionEvent("speak")`.
- ActionWorker không bao giờ bị block bởi subprocess.

---

## 3. Config mới (`config.yaml`)

```yaml
voice:
  stt:
    engine: "hybrid"                 # vosk | phowhisper | hybrid
    phowhisper_model: "models/phowhisper-small"
    phowhisper_device: "cpu"         # cpu | cuda
    phowhisper_compute_type: "int8"
  tts:
    engine: "vieneu"                 # vieneu | pyttsx3 | none
    vieneu_voice: "models/vieneu-voice"
    rate: 1.0

nlu:
  coder:
    enabled: true
    model: "qwen2.5-coder:7b"
    ollama_url: "http://localhost:11434"
    timeout_sec: 30

coder:
  workspace_root: "."
  allowed_commands: ["pytest", "git", "pip", "python", "node", "npm"]
  command_timeout_sec: 300
  backend: "opencode"                # opencode | aider | none
  opencode_path: "opencode"
  aider_path: "aider"
```

`workspace_root: "."` được resolve theo thư mục chạy app. Chạy `main.py` từ
root repo để giới hạn đúng workspace.

---

## 4. Cài đặt dependency (đều optional)

```bash
# 1) PhoWhisper-small → CTranslate2 (faster-whisper)
pip install faster-whisper transformers ctranslate2
ct2-transformers-converter \
  --model vinai/PhoWhisper-small \
  --output_dir models/phowhisper-small \
  --quantization int8
```

```bash
# 2) VieNeu-TTS (nếu package không cài được, pyttsx3 sẽ được dùng)
pip install vieneu
# hoặc fallback voice hệ thống:
pip install pyttsx3
```

```bash
# 3) Coder NLU local
ollama pull qwen2.5-coder:7b
# kiểm tra: curl http://localhost:11434/api/tags
```

```bash
# 4) Delegate backend (chọn một)
npm i -g opencode-ai
# hoặc
pip install aider-chat
```

Thiếu bất kỳ mục nào:

- Thiếu PhoWhisper → Vosk vẫn transcribe như cũ.
- Thiếu VieNeu/pyttsx3 → không nói, chỉ log; phần còn lại chạy bình thường.
- Thiếu Ollama → CoderNLU trả `None`, quay về NLU rule-based.
- Thiếu OpenCode/Aider → `delegate_to_coder` speak hướng dẫn cài.

---

## 5. Sử dụng

1. Chạy `python main.py --dev`.
2. Nhấn `Ctrl+Alt+C` để vào **CODE mode** (nhấn lại để thoát).
3. Nói wake word (mặc định "trợ lý"), rồi ra lệnh:

| Câu nói | Action |
|---|---|
| "tạo file hello.py với print('hello')" | `create_file` |
| "chạy pytest" | `run_command` (async, speak kết quả) |
| "commit với message fix auth" | `git_commit` |
| "tìm hàm login" | `search_code` |
| "giải thích file core/nlu.py" | `explain_code` + TTS |
| "refactor file auth.py thành async" | `delegate_to_coder` → OpenCode/Aider |

Ngoài CODE mode, voice dùng NLU rule-based như cũ. "mở youtube" vừa mở trang
vừa được TTS xác nhận.

---

## 6. Breaking changes

**Không có breaking change về API/hành vi cũ.**

- 66 test cũ vẫn xanh; bổ sung 62 test mới (tổng 128).
- `Mode.CODE` là giá trị enum mới; các mode cũ giữ nguyên.
- `NLU.parse()` vẫn trả `List[Intent]`; rule có `response` sẽ sinh thêm
  `Intent("speak")` ở cuối.
- `ActionDispatcher` thêm tham số keyword `tts`, `coder` (mặc định `None`).

---

## 7. Kiểm thử

```bash
pytest -v                 # toàn bộ
ruff check .              # lint (CI gate)
```

Các test mới mock toàn bộ external (faster-whisper, Ollama HTTP, subprocess,
mic) nên chạy offline, không phụ thuộc model hay mạng.

---

## 8. Hạn chế đã biết

- Chất lượng PhoWhisper/VieNeu/Ollama phụ thuộc model thật; test chỉ xác nhận
  hợp đồng interface và fallback.
- `qwen2.5-coder:7b` cần ~5 GB RAM; máy yếu có thể dùng
  `qwen2.5-coder:3b` (sửa `nlu.coder.model`).
- CoderNLU được bật mặc định; nếu Ollama không chạy, lệnh không hiểu sẽ chờ
  tối đa `timeout_sec` trước khi bỏ cuộc. Có thể đặt `enabled: false` để tắt.
- Delegate stream log từng dòng; TTS chỉ đọc kết quả cuối để tránh nhiễu.
