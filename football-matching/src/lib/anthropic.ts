import Anthropic from "@anthropic-ai/sdk";
import { BKK_DISTRICTS } from "./districts";
import type { ParsedMatch } from "./types";

const client = new Anthropic(); // reads ANTHROPIC_API_KEY from env

// Default to the most capable model. Set PARSE_MODEL=claude-haiku-4-5 in .env
// for cheaper/faster parsing if extraction quality holds up for your posts.
const MODEL = process.env.PARSE_MODEL || "claude-opus-4-8";

// Frozen system prompt — keep byte-stable so prompt caching keeps a warm prefix
// across requests (spec/cost note: caches only kick in above the model's minimum
// prefix size; harmless if the prompt is short, big win once examples are added).
const SYSTEM_PROMPT = `คุณคือตัวช่วยแยกข้อมูลจากโพสต์ "หาคนเตะบอล / หาทีม / หาก๊วน" ภาษาไทยที่คนแปะมาจาก Facebook หรือ LINE
หน้าที่: อ่านข้อความแล้วดึงข้อมูลออกมาเป็น field ตาม schema ที่กำหนด

กติกาการแยก:
- วันเวลา: ตีความวันที่เป็นรูปแบบ ISO (YYYY-MM-DD) และเวลาเป็น 24 ชั่วโมง (HH:MM) ถ้าระบุแค่ "คืนนี้/พรุ่งนี้/เย็นนี้" ให้เดาวันที่จากบริบทเท่าที่ทำได้ ถ้าไม่รู้ให้เป็น null
- district: ต้องเป็นชื่อ "เขต" ของกรุงเทพฯ เท่านั้น (เช่น บางกะปิ, ห้วยขวาง) ถ้าโพสต์บอกแค่ชื่อสนามให้พยายามอนุมานเขตจากชื่อสนามที่รู้จัก ถ้าไม่แน่ใจให้เป็น null
- matchType: ประเภทสนาม 5, 7 หรือ 11 คน ถ้าไม่ระบุให้เป็น null
- playersNeeded: จำนวนคนที่ยัง "ขาด/ต้องการเติม" (ไม่ใช่จำนวนคนทั้งหมด)
- positionsNeeded: ตำแหน่งที่ต้องการ เช่น ["GK"], ["กองหลัง"], ["กองหน้า"] ถ้าไม่ระบุให้เป็น []
- pricePerHead: ราคาหารหัวเป็นบาท (ตัวเลขเท่านั้น) ถ้าไม่ระบุให้เป็น null
- skillLevel: ระดับฝีเท้า เลือกจาก beginner (มือใหม่/ชิล), casual (เตะออกกำลัง/ทั่วไป), competitive (จริงจัง/ฝีเท้าดี), any (ไม่ระบุ/ใครก็ได้)
- contactLine / contactTel: ดึง LINE ID และเบอร์โทรถ้ามี ไม่มีให้เป็น null
- confidence: ความมั่นใจในการแยกโดยรวม 0..1

ตอบเป็น JSON ตาม schema เท่านั้น ห้ามอธิบายเพิ่ม`;

const SCHEMA = {
  type: "object",
  additionalProperties: false,
  properties: {
    kickoffDate: { type: ["string", "null"], description: "ISO date YYYY-MM-DD or null" },
    kickoffTime: { type: ["string", "null"], description: "HH:MM 24h or null" },
    venueName: { type: ["string", "null"] },
    district: {
      type: ["string", "null"],
      enum: [...BKK_DISTRICTS, null],
      description: "ชื่อเขต กทม. หรือ null",
    },
    matchType: { type: ["integer", "null"], description: "5 | 7 | 11 | null" },
    playersNeeded: { type: ["integer", "null"] },
    positionsNeeded: { type: "array", items: { type: "string" } },
    pricePerHead: { type: ["number", "null"] },
    skillLevel: { type: "string", enum: ["beginner", "casual", "competitive", "any"] },
    contactLine: { type: ["string", "null"] },
    contactTel: { type: ["string", "null"] },
    confidence: { type: "number" },
  },
  required: [
    "kickoffDate", "kickoffTime", "venueName", "district", "matchType",
    "playersNeeded", "positionsNeeded", "pricePerHead", "skillLevel",
    "contactLine", "contactTel", "confidence",
  ],
} as const;

export async function parseMatchPost(rawText: string, todayISO: string): Promise<ParsedMatch> {
  // `output_config` is a current-API field that may not be in this SDK version's
  // static types yet; it's still sent in the request body. Cast through unknown.
  const params = {
    model: MODEL,
    max_tokens: 1024,
    thinking: { type: "disabled" }, // simple extraction — skip thinking for speed/cost
    system: [
      { type: "text", text: SYSTEM_PROMPT, cache_control: { type: "ephemeral" } },
    ],
    messages: [
      {
        role: "user",
        content: `วันนี้คือ ${todayISO} (Asia/Bangkok)\n\nข้อความโพสต์:\n"""\n${rawText}\n"""`,
      },
    ],
    // Structured output — guarantees valid JSON matching SCHEMA
    output_config: { format: { type: "json_schema", schema: SCHEMA } },
  } as unknown as Anthropic.MessageCreateParamsNonStreaming;

  const message = await client.messages.create(params);

  const textBlock = message.content.find((b) => b.type === "text");
  if (!textBlock || textBlock.type !== "text") {
    throw new Error("Parser returned no text content");
  }
  return JSON.parse(textBlock.text) as ParsedMatch;
}
