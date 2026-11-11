# =====================================================================
# docs/ARCHITECTURE.md
# Kiến trúc Tiểu Vũ — local-first multimodal computer control.
# =====================================================================

## 1. Mục tiêu

Tiểu Vũ (mã `tieu-vu` / `GazeFlow`) giảm ≥ 70% thao tác bàn phím & chuột bằng
ba kênh đầu vào chạy **hoàn toàn cục bộ**:

| Kênh | Công nghệ | Độ trễ mục tiêu |
|---|---|---|
| Gaze | MediaPipe FaceMesh 478 + đa thức hiệu chuẩn + One Euro | < 40 ms |
| Voice | Vosk streaming + VAD + NLU rule + LLM fallback | < 600 ms |
| Gesture | MediaPipe Hands 21 landmark + state machine | < 50 ms |
| Snippet | pynput buffer 12 ký tự | < 20 ms |

## 2. Luồng dữ liệu

```
Camera ──► VisionEngine (thread riêng)
             │ VisionFrame {hands, face, image}
             ▼
     ┌───────┴───────────────┐
     ▼                       ▼
StateMachine (gesture)   GazeEstimator
   IDLE/GAZE/VOICE/VK/FOCUS   EyeTracker → OneEuro → DeadZone → CalibrationModel
     │                       │
     │                       ├── DwellClicker (R=40px, T=650ms)
     │                       ├── BlinkDetector (EAR < 0.2)
     │                       └── EdgeScrollEngine (10% mép, ramp 3→15 dòng/s)
     └──────────┬────────────┘
                ▼
        ActionEvent queue (bounded 256)
                ▼
        ActionWorker (thread) ──► MouseController / TextController /
                                  SystemController / WebAgent / UI
                ▼
          Telemetry (SQLite)
```

## 3. Ranh giới module

- `core/vision_engine.py` — chỉ đọc camera + MediaPipe, không gọi OS.
- `core/gaze_estimator.py` — toán học gaze, không side effect.
- `core/filters.py` — One Euro + dead-zone thuần.
- `core/click_engine.py`, `core/scroll_engine.py` — máy trạng thái thời gian.
- `core/state_machine.py` — trọng tài cử chỉ + mode độc quyền.
- `core/nlu.py` — rule trước, LLM sau (lazy load).
- `actions/*` — tác động OS, chỉ chạy trong ActionWorker.
- `ui/*` — tray/HUD/VK/calibration/donate, đều fail-safe nếu thiếu GUI.

## 4. Quyết định thiết kế

1. **Local-first**: không gửi frame/audio lên mạng; LLM fallback cũng chạy GGUF cục bộ.
2. **Một mode độc quyền**: `VOICE`/`VK`/`FOCUS` chặn gesture để tránh xung đột.
3. **Fail-safe từng lớp**: thiếu mediapipe/vosk/tkinter/pystray → log + degrade.
4. **Latency budget**: vision 30 FPS, queue bounded, action worker bất đồng bộ.
5. **Đo lường**: telemetry SQLite đếm action theo nguồn để chứng minh mục tiêu 70%.

## 5. Mở rộng

- L2CS-Net ONNX: đặt `models/l2cs_net.onnx`, bật trong `config.yaml` → fallback
  `onnxruntime` CPU; code tự phát hiện, không cần sửa.
- openWakeWord: thêm model vào `wake_word.model_paths`; không có thì Vosk
  phrase matching đảm nhiệm.
