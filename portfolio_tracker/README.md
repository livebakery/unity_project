# Portfolio Tracker (subdirectory of `unity_project`)

Auto-snapshot ของพอร์ทหุ้นบน Google Sheets — ทุกวันศุกร์ 16:50 ICT จะ:
1. copy tab ล่าสุด → ตั้งชื่อใหม่เป็น DDMMYYYY ของวันนี้
2. อัพเดทคอลัมน์ **ราคาตลาด** (col G) จาก yfinance
3. คำนวณ **รวมตามราคาตลาด** + **%U.PL** ใหม่
4. ส่งสรุปเข้า Telegram

## หลักการ

- Source tab: หา worksheet ที่ชื่อเป็นรูปแบบ `DDMMYYYY` แล้ววันที่ล่าสุด
- Idempotent: ถ้า tab ของวันนี้มีอยู่แล้ว ไม่ทำอะไร
- Skip weekends (Sat/Sun) — เว้นแต่จะ manual trigger ด้วย `force_run=true`

## Setup

### 1. Share Google Sheet ให้ Service Account (Editor)
- เปิดไฟล์ portfolio → Share → paste email ของ service account
  (ตัวเดียวกับที่ใช้ VI Stock Alert ใน parent repo)
- Permission = **Editor** (ต้อง write ได้ ไม่ใช่แค่ Viewer)

### 2. GitHub Secret ที่ต้องเพิ่ม
ที่ Settings → Secrets and variables → Actions ของ `unity_project`:

| Secret | Value | Status |
|---|---|---|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | (มีอยู่แล้ว) | ✅ reuse |
| `TELEGRAM_BOT_TOKEN` | (มีอยู่แล้ว) | ✅ reuse |
| `TELEGRAM_CHAT_ID` | (มีอยู่แล้ว) | ✅ reuse |
| `PORTFOLIO_SHEET_ID` | `1dhcdI7JFCkVHTbbCpJWZYIaP7GOQ_rg5TMaNDIZqZco` | ➕ ต้องเพิ่มใหม่ |

หมายเหตุ: ใช้ secret name แยก (`PORTFOLIO_SHEET_ID`) ไม่ทับ `SHEET_ID`
ที่ workflow VI Stock Alert ใช้อยู่

### 3. Trigger รอบแรก
- Actions → **Weekly Portfolio Snapshot** → **Run workflow**
- ✅ ติ๊ก force_run ถ้าไม่ใช่วันศุกร์
- Verify: มี tab ใหม่ชื่อ DDMMYYYY วันนี้ + Telegram เด้ง summary

## Structure

```
portfolio_tracker/
├── main.py                 orchestrator
├── config.yaml             column layout, tab naming
├── README.md               this file
└── src/
    ├── sheets_ops.py       pick source, duplicate, apply prices
    ├── price_fetcher.py    yfinance batch + fallback fast_info
    └── telegram_notify.py  Telegram Bot sendMessage

Root-level shared:
├── requirements.txt        pip deps (VI + Portfolio share these)
└── .github/workflows/portfolio-snapshot.yml   Fri 16:50 ICT cron
```
