import { NextResponse } from "next/server";
import { parseMatchPost } from "@/lib/anthropic";

export const runtime = "nodejs";

// POST /api/parse  { rawText: string }  ->  ParsedMatch
// วางข้อความโพสต์ -> AI แตกเป็น field (spec §5.1)
export async function POST(req: Request) {
  try {
    const { rawText } = await req.json();
    if (!rawText || typeof rawText !== "string" || rawText.trim().length < 5) {
      return NextResponse.json({ error: "rawText is required" }, { status: 400 });
    }

    const todayISO = new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Bangkok" });
    const parsed = await parseMatchPost(rawText.trim(), todayISO);

    return NextResponse.json({ parsed });
  } catch (err) {
    console.error("parse error", err);
    return NextResponse.json({ error: "parse_failed" }, { status: 500 });
  }
}
