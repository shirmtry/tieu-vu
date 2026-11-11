# =====================================================================
# docs/CALIBRATION.md
# Hướng dẫn hiệu chuẩn 9 điểm cho gaze tracking.
# =====================================================================

## 1. Khi nào cần hiệu chuẩn

- Lần đầu chạy, hoặc đổi vị trí camera / ghế ngồi / độ cao màn hình.
- Khi con trỏ gaze lệch hệ thống > 80 px.

## 2. Quy trình

1. Ngồi cách camera 50–70 cm, giữ đầu tương đối thẳng.
2. Chạy app, chọn **🎯 Hiệu chuẩn gaze** trên tray (hoặc `python main.py --calibrate`).
3. Nhìn lần lượt 9 chấm xanh; mỗi chấm thu **30 frame** (~1 giây).
4. Hệ thống fit đa thức bậc 2: `[1, h, v, h·v, h², v²] → (x, y)` bằng `numpy.linalg.lstsq`.
5. Kiểm chứng 5 mẫu ngẫu nhiên; sai số tối đa cho phép **80 px @1080p**.
6. Kết quả lưu tại `config/calibration_<user>.npz`.

## 3. Cấu trúc file

```python
np.load("config/calibration_default.npz")
# coeffs_x, coeffs_y : vector 6 hệ số
# screen_w, screen_h : độ phân giải lúc hiệu chuẩn
# rms_error_px, n_samples
```

## 4. Mẹo giảm sai số

- Tắt đèn ngược sáng; đeo kính giữ nguyên khi hiệu chuẩn và khi dùng.
- Giữ `gaze.smoothing: true` và dead-zone mặc định (8 px / 100 ms).
- Nếu RMS > 40 px, hiệu chuẩn lại ở vị trí ngồi thoải mái nhất.
