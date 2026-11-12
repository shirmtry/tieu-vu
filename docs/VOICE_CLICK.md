# Voice Click — điều khiển UI bằng giọng nói

Nói **"bấm nút Đăng nhập"** (hoặc "nhấn nút OK", "click Login") trong mode
`VOICE_CLICK`: Tiểu Vũ tìm phần tử trên màn hình rồi bấm vào tâm của nó.

## Cách hoạt động

```
Voice (Vosk/PhoWhisper)
   │  "bấm nút Đăng nhập"
   ▼
NLU rule-based  ──►  ActionEvent("click_target", {"target": "dang nhap"})
   │
   ▼  (ActionWorker — không block vision)
HybridFinder
   ├─ 1. UIA (Windows UI Automation)   → role + bbox, chính xác
   └─ 2. RapidOCR (fallback)           → bbox + fuzzy text, KHÔNG lưu text
   ▼
click_found()  → move_screen(tâm bbox) + left_click()
   ▼
TTS: "Đã bấm button."
```

- **UIA là finder chính.** Duyệt cây accessibility tối đa
  `voice_click.uia.max_depth` / `max_nodes`, so khớp tên bằng fuzzy
  (`rapidfuzz.token_sort_ratio`) sau khi bỏ dấu/gộp âm cuối.
- **OCR chỉ là fallback.** Chỉ chạy khi UIA không tìm thấy. Ảnh chụp nằm trong
  RAM (`mss`), không ghi xuống đĩa; text OCR không bao giờ được lưu vào
  `FoundElement` hay telemetry.
- **Không teencode, không LLM, không cloud.** Chỉ rule + fuzzy matching.

## Mode & hotkey

| Mục | Giá trị |
|---|---|
| Mode | `VOICE_CLICK` |
| Hotkey | `Ctrl+Alt+O` (toggle) |
| Gesture | Bị chặn (mode exclusivity) |
| Voice | Được phép |
| Gaze highlight | Được phép (HUD viền cyan) |

## Privacy

- Không ghi screenshot xuống đĩa.
- Không log tên element / transcript giọng nói.
- Telemetry cho `click_target` chỉ lưu `target_chars`; khi bấm thành công lưu
  `element_id`, `role`, `duration_ms`.

## Config

```yaml
voice_click:
  enabled: true
  uia:
    max_depth: 10
    max_nodes: 5000
    min_score: 70      # 0..100, càng cao càng khắt khe
  ocr_fallback:
    enabled: true
    min_conf: 0.6      # độ tin cậy OCR tối thiểu
    min_score: 70
  privacy:
    log_element_name: false
```

## Ví dụ lệnh

- "bấm nút Đăng nhập"
- "bấm vào nút OK"
- "nhấn nút Hủy"
- "click Login"
- "chọn nút Tiếp tục"

## Test

```bash
pytest -q tests/test_finder_uia.py tests/test_finder_ocr.py \
         tests/test_finder_hybrid.py tests/test_integration_voice_click.py
pytest -q --benchmark-only tests/test_perf_bench.py
```

Benchmark budgets: `find()` < 5 ms, `StateMachine.update()` < 0.1 ms.

## Troubleshooting

| Hiện tượng | Nguyên nhân / cách xử lý |
|---|---|
| "Không tìm thấy ..." | Element không lộ tên UIA và OCR không đọc được; thử nói đúng nhãn hiển thị |
| UIA không khả dụng | Thiếu `uiautomation`/`comtypes` (chỉ Windows) → chỉ còn OCR fallback |
| OCR không khả dụng | Thiếu `rapidocr-onnxruntime` hoặc `mss` → chỉ dùng UIA |
| Bấm sai vị trí | Tăng `voice_click.uia.min_score` để khắt khe hơn |
