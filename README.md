# Stock Price Alert System

ระบบเฝ้าดูไฟล์ประเมินมูลค่าหุ้นของพี่เซียน VI บน Google Sheets แล้วเปรียบเทียบกับราคาตลาด SET realtime ส่ง alert ผ่าน Telegram เมื่อ:

1. **ไฟล์ถูกอัพเดท** → แจ้ง diff ของ fair value
2. **ราคาตลาด ≤ fair value** ที่ 3 ระดับ:
   - 🟡 Level 1 — ราคาแตะ fair (discount ≥ 0%)
   - 🟠 Level 2 — ส่วนลด ≥ 10%
   - 🔴 Level 3 — ส่วนลด ≥ 15% (deep value)

ทำงานบน GitHub Actions cron (ฟรี ไม่ต้องดูแล server) ตรวจทุก 15 นาทีในช่วงตลาดเปิด

## Setup

### 1. Google Cloud Service Account

1. ไปที่ [Google Cloud Console](https://console.cloud.google.com/) สร้าง project
2. เปิด API:
   - Google Sheets API
   - Google Drive API
3. **IAM & Admin → Service Accounts → Create Service Account**
4. ที่ service account ที่สร้าง → **Keys → Add Key → Create new key → JSON** → download
5. Copy email ของ service account (ลงท้าย `@<project>.iam.gserviceaccount.com`)

### 2. แชร์ Sheet กับ Service Account

- เปิดไฟล์ Sheet ของพี่เซียน (ที่พี่ถูกแชร์มา)
- กด **Share** → ใส่ email ของ service account → สิทธิ์ **Viewer** ก็พอ
- Copy Sheet ID จาก URL: `docs.google.com/spreadsheets/d/<SHEET_ID>/edit`

### 3. Telegram Bot

1. ใน Telegram คุยกับ [@BotFather](https://t.me/BotFather)
2. `/newbot` → ตั้งชื่อ → ได้ **bot token**
3. ส่งข้อความใดๆ ให้ bot ของตัวเอง 1 ครั้ง (เพื่อ activate chat)
4. เปิด `https://api.telegram.org/bot<TOKEN>/getUpdates` ในเบราว์เซอร์ → copy `chat.id`

### 4. ตั้ง GitHub Secrets

ที่ repo: **Settings → Secrets and variables → Actions → New repository secret**

| Secret | Value |
|---|---|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | ทั้ง JSON ของ service account (paste เนื้อหาทั้งไฟล์) |
| `SHEET_ID` | ID ของ Sheet จากขั้นตอนที่ 2 |
| `TELEGRAM_BOT_TOKEN` | bot token จาก BotFather |
| `TELEGRAM_CHAT_ID` | chat id ของพี่ |

### 5. รัน

- Push code → workflow รันอัตโนมัติทุก 15 นาทีในช่วงตลาด SET เปิด
- Manual trigger: **Actions tab → Check Stocks → Run workflow** (ติ๊ก "Run even if market is closed" ถ้าทดสอบนอกเวลา)

## Local Test

```bash
pip install -r requirements.txt

export GOOGLE_SERVICE_ACCOUNT_JSON="$(cat service-account.json)"
export SHEET_ID="..."
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="..."
export FORCE_RUN=1   # bypass market-hours gate

python main.py
```

## Configuration (`config.yaml`)

```yaml
thresholds:
  level_1_pct: 0    # alert when price <= fair value
  level_2_pct: 10   # alert when discount >= 10%
  level_3_pct: 15   # alert when discount >= 15%

market_hours_ict:
  morning:   { start: "09:55", end: "12:30" }
  afternoon: { start: "14:30", end: "16:45" }

header_keywords:
  ticker:     ["ticker", "symbol", "หุ้น", "ชื่อย่อ", "code"]
  fair_value: ["fair", "target", "มูลค่า", "ประเมิน", "intrinsic"]

worksheet_name: null   # null = first worksheet
ticker_suffix: ".BK"   # SET stocks on Yahoo Finance
```

ปรับ keyword ใน `header_keywords` ได้ ถ้าพี่เซียนใช้ชื่อคอลัมน์ผิดจาก default

## Files

```
.github/workflows/check-stocks.yml    # cron + commit state
src/sheets_client.py                  # Google Sheets API
src/drive_watcher.py                  # Drive modifiedTime
src/parser.py                         # auto-detect headers
src/price_fetcher.py                  # yfinance batch
src/alert_logic.py                    # 3-level dedupe
src/telegram_notify.py                # Telegram Bot API
src/state.py                          # state.json I/O
main.py                               # orchestrator
config.yaml                           # thresholds, hours, keywords
state.json                            # auto-generated, committed by workflow
```

## Dedupe Logic

Alert ตัวเดียวกันจะไม่ถูกส่งซ้ำเรื่อยๆ — `state.json` เก็บ `last_alert_levels` ของแต่ละ ticker แล้วยิง alert เฉพาะตอน level **เพิ่มขึ้น** (1→2, 2→3) ถ้าราคากลับขึ้นแล้วลงอีกครั้ง level ใน state จะ reset → fire ใหม่ได้

เมื่อพี่เซียนอัพเดท fair value (ผ่าน Drive `modifiedTime`) → reset alert level ของหุ้นที่ค่าเปลี่ยน เพื่อให้ alert รอบใหม่ทำงานบน fair value ใหม่
