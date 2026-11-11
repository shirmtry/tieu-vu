# =====================================================================
# docs/DONATE.md
# Tích hợp SePay VietQR — donate cho Tiểu Vũ (MB Bank 0374756847).
# =====================================================================

## 1. Thông tin nhận tiền

| Kênh | Thông tin |
|---|---|
| Ngân hàng | MB Bank (Ngân hàng Quân Đội) |
| Số tài khoản | `0374756847` |
| Chủ tài khoản | `SHIRMTRY` |
| Nội dung CK | `Ung ho Tieu Vu` |
| Cổng | SePay — VietQR (`https://qr.sepay.vn`) |

### URL QR

```
https://qr.sepay.vn/img?acc=0374756847&bank=MB%20Bank&des=Ung%20ho%20Tieu%20Vu&template=compact&showinfo=true&fullacc=true&holder=SHIRMTRY
```

| Param | Bắt buộc | Giá trị |
|---|---|---|
| `acc` | ✅ | `0374756847` |
| `bank` | ✅ | `MB Bank` (fallback `MB`) |
| `des` | ❌ | `Ung ho Tieu Vu` |
| `amount` | ❌ | bỏ trống (linh hoạt) |
| `template` | ❌ | `compact` |
| `showinfo` | ❌ | `true` |
| `fullacc` | ❌ | `true` |
| `holder` | ❌ | `SHIRMTRY` |

## 2. Đăng ký webhook (nhận thông báo tự động)

1. Đăng nhập [my.sepay.vn](https://my.sepay.vn) → liên kết tài khoản MB Bank `0374756847`.
2. Vào **WebHooks → + Add webhooks**:
   - URL: `https://<your-app>.onrender.com/webhook/sepay`
   - Authentication: `Api_Key` → copy key.
   - Events: `In_only`.
3. Đặt biến môi trường trên server: `SEPAY_WEBHOOK_KEY=<key vừa copy>`.
   Tuyệt đối không commit key — dùng GitHub Secrets / dashboard Render.
4. (Tuỳ chọn) `TIEU_VU_DONATIONS_DB=/data/donations.db` nếu dùng persistent disk.

## 3. Deploy FastAPI

```bash
# Local
uvicorn server.webhook:app --host 0.0.0.0 --port 8000

# Render / Railway: start command
uvicorn server.webhook:app --host 0.0.0.0 --port $PORT
```

Hoặc Cloudflare Tunnel khi chạy local:

```bash
cloudflared tunnel --url http://localhost:8000
```

## 4. Kiểm thử end-to-end

1. Chuyển khoản thử **10.000 VND** với nội dung `Ung ho Tieu Vu`.
2. Webhook phải trả `{"success": true}` trong **≤ 5 giây**.
3. Kiểm tra DB:

```bash
python - <<'PY'
import sqlite3
print(sqlite3.connect("logs/donations.db").execute(
    "SELECT sepay_id, amount, content FROM donations").fetchall())
PY
```

## 5. Badge thống kê (tuỳ chọn)

Sau khi deploy, thêm vào README:

```markdown
![Donations](https://img.shields.io/endpoint?url=https://<your-app>.onrender.com/stats/donations)
```

`GET /stats/donations` trả JSON shields.io endpoint với tổng số giao dịch + số tiền.

## 6. Bảo mật

- Webhook key chỉ nằm trong env; `.env` đã bị `.gitignore`.
- Dedup theo `sepay_id` (idempotent khi SePay retry).
- Chỉ ghi `transferType == "in"`; giao dịch ra bị bỏ qua.
