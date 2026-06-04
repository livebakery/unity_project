# ⚽ Football Matching App

แอปจับคู่คนเตะบอล / หาก๊วน ในกรุงเทพฯ — รวมนัดเตะแยกโซน-เขต + แผนที่สนาม

> 📄 สเปคฉบับเต็ม: [`docs/spec.md`](docs/spec.md)

## หัวใจของแอป
วางข้อความโพสต์จาก Facebook/LINE → **AI (Claude) แตกเป็น field** (วันเวลา, สนาม, เขต, จำนวนที่ขาด, ตำแหน่ง, ราคา, ติดต่อ) → ค้นหา/filter ตามเขต-ระดับ + ดูตำแหน่งสนามบน Google Maps

## Tech stack
- **Next.js 15** (App Router, TypeScript) — เว็บ + เผื่อฝังเป็น LINE LIFF
- **Prisma + Postgres (Supabase)** — `Match` / `Venue`
- **Anthropic SDK** — parser (structured outputs + prompt caching) → `src/lib/anthropic.ts`
- **Google Maps** — แผนที่ + geocoding ชื่อสนาม

## โครงไฟล์
```
football-matching/
├── docs/spec.md                 # เอกสารสเปค
├── prisma/schema.prisma         # data model
├── src/lib/
│   ├── anthropic.ts             # AI parser (Claude)
│   ├── districts.ts             # 50 เขต กทม. + โซน
│   ├── db.ts                    # Prisma client
│   └── types.ts
├── src/app/
│   ├── page.tsx                 # หน้า list + filter
│   ├── create/page.tsx          # วางข้อความ → parse → แก้ → โพสต์
│   ├── map/page.tsx             # Google Map สนาม
│   └── api/
│       ├── parse/route.ts       # POST วางข้อความ → ParsedMatch
│       └── matches/route.ts     # GET list (filter) / POST สร้างนัด
└── src/components/              # MatchCard, Filters
```

## เริ่มใช้งาน (local)
```bash
cd football-matching
npm install
cp .env.example .env          # ใส่ ANTHROPIC_API_KEY, DATABASE_URL, Google Maps keys
npm run db:push               # สร้างตารางบน Postgres
npm run dev                   # http://localhost:3000
```

ต้องมี:
- **ANTHROPIC_API_KEY** — สำหรับ parser (ตั้ง `PARSE_MODEL=claude-haiku-4-5` ได้ถ้าอยากประหยัด)
- **DATABASE_URL / DIRECT_URL** — Postgres (Supabase free tier ได้)
- **Google Maps keys** — browser key (แผนที่) + server key (geocoding)

## สถานะ
Phase 1 (MVP) prototype — list/filter, AI parse, สร้างนัด, แผนที่สนาม
ดู roadmap + cold-start strategy ใน [`docs/spec.md`](docs/spec.md)

> หมายเหตุ: โปรเจคนี้ตั้งใจให้ย้ายไป repo `football-matching-app` แยกภายหลังได้
> — ทุกอย่างอยู่ในโฟลเดอร์เดียว ย้ายด้วย `git subtree split` หรือก๊อปโฟลเดอร์ได้เลย
