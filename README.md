# VI Stock Price Alert System

ระบบเฝ้าดูไฟล์ประเมินมูลค่าหุ้นของพี่เซียน VI บน Google Sheets และเช็คราคาตลาด SET realtime ส่ง alert ผ่าน Telegram เมื่อพบจังหวะ "asymmetric bet" — upside/downside ratio ≥ 10

## หลักการ

```
Fair Price 3Y [Premium] = Fair Price [Premium] × (1 + 3Y CAGR)³

                  | (Fair_3Y - LivePrice) / LivePrice |
        ratio = ───────────────────────────────────────
                  | (Fair_Core - LivePrice) / LivePrice |
```

- **ตัวเลข > 10** = upside ใน 3 ปีมากกว่าความเสี่ยง downside (Core P/E, no-growth assumption) อย่างน้อย 10 เท่า
- ดึงราคาตลาด realtime จาก yfinance (suffix `.BK`)
- ราคาในไฟล์ของพี่เซียนค้างก็ไม่เป็นไร เราใช้แค่ `Fair Price [Premium]`, `3Y CAGR`, `Fair Price [Core]` มาคำนวณคู่กับราคาสด

## Triggers ที่จะเด้ง Telegram

1. **ไฟล์ Sheets ถูกอัพเดท** (ตรวจจาก Google Drive `modifiedTime`)
   → แจ้งว่าหุ้นใน watchlist ค่าใดเปลี่ยน (Fair Price Premium / 3Y CAGR / Fair Price Core)
2. **ratio ≥ 10** → 🚨 สัญญาณซื้อ (dedupe ในตัว: ไม่ส่งซ้ำจนกว่า ratio จะตกแล้วกลับมาเข้าเงื่อนไขใหม่)

## Watchlist

`config.yaml` กำหนด ticker ที่ต้องการตรวจ:

```yaml
watchlist:
  - DOHOME
```

เพิ่ม-ลด ticker ในนี้ได้ — แต่ต้องเป็นชื่อที่อยู่ใน Sheet ของพี่เซียน

## Setup

### 1. Google Cloud Service Account

1. ไป [Google Cloud Console](https://console.cloud.google.com/) สร้าง project
2. เปิด API: **Google Sheets API** และ **Google Drive API**
3. **IAM & Admin → Service Accounts → Create Service Account** ตั้งชื่อ "stock-bot"
4. เปิด service account → **Keys → Add Key → Create new key → JSON** → download
5. Copy email ของ service account (ลงท้าย `@<project>.iam.gserviceaccount.com`)

### 2. แชร์ Sheet กับ Service Account

- เปิดไฟล์ Sheet ของพี่เซียน → **Share** → ใส่ email ของ service account → สิทธิ์ **Viewer**
- Copy Sheet ID จาก URL: `docs.google.com/spreadsheets/d/<SHEET_ID>/edit`

### 3. Telegram Bot

1. ใน Telegram คุยกับ [@BotFather](https://t.me/BotFather) → `/newbot` → ได้ **bot token**
2. ส่งข้อความใดๆ ให้ bot 1 ครั้ง (เพื่อ activate chat)
3. เปิด `https://api.telegram.org/bot<TOKEN>/getUpdates` → copy `chat.id`

### 4. ตั้ง GitHub Secrets

Repo → **Settings → Secrets and variables → Actions → New repository secret**

| Secret | Value |
|---|---|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | JSON ของ service account ทั้งไฟล์ |
| `SHEET_ID` | ID ของ Sheet จากขั้นตอนที่ 2 |
| `TELEGRAM_BOT_TOKEN` | bot token จาก BotFather |
| `TELEGRAM_CHAT_ID` | chat id ของพี่ |

### 5. รัน

- Workflow รันอัตโนมัติทุก 15 นาทีในช่วงตลาด SET เปิด
- Manual: **Actions tab → Check Stocks → Run workflow** (ติ๊ก "Run even if market is closed" ถ้าทดสอบนอกเวลา)

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

## Files

```
main.py                          # orchestrator
config.yaml                      # watchlist, threshold, market hours
state.json                       # auto-managed (last seen file mtime, valuations, alert state)

src/sheets_client.py             # Google Sheets reader (service account)
src/drive_watcher.py             # Drive modifiedTime poll
src/parser.py                    # auto-detect 4 columns + parse
src/price_fetcher.py             # yfinance batch fetch with .BK suffix
src/alert_logic.py               # compute snapshot + ratio + dedupe
src/telegram_notify.py           # Telegram Bot API
src/state.py                     # atomic JSON state I/O

.github/workflows/check-stocks.yml  # cron + commit state back
```

## Header keyword detection

Parser auto-detects column positions in the sheet header row by matching keywords (case-insensitive):

| Field | Keywords (any token combo found in cell text) |
|---|---|
| ticker | `stock`, `ticker`, `symbol`, `หุ้น`, `ชื่อย่อ` |
| Fair Price [Premium] | `fair` + `price` + `premium` |
| 3Y CAGR [Premium] | `3y` + `cagr` + `premium` |
| Fair Price [Core] | `fair` + `price` + `core` |

ถ้าพี่เซียนเปลี่ยนชื่อคอลัมน์ในอนาคต — แก้ keyword list ใน `src/parser.py` `_REQUIRED_COLUMN_KEYWORDS`
