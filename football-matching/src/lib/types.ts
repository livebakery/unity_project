export type SkillLevel = "beginner" | "casual" | "competitive" | "any";

export const SKILL_LABELS: Record<SkillLevel, string> = {
  beginner: "🟢 มือใหม่หัดเตะ",
  casual: "🔵 เตะออกกำลัง",
  competitive: "🔴 จริงจัง",
  any: "⚪ ไม่จำกัด",
};

/** Shape returned by POST /api/parse — one parsed match post. */
export interface ParsedMatch {
  kickoffDate: string | null; // ISO date, e.g. "2026-06-10"
  kickoffTime: string | null; // "HH:MM" 24h
  venueName: string | null;
  district: string | null; // one of BKK_DISTRICTS, else null
  matchType: number | null; // 5 | 7 | 11
  playersNeeded: number | null;
  positionsNeeded: string[];
  pricePerHead: number | null;
  skillLevel: SkillLevel;
  contactLine: string | null;
  contactTel: string | null;
  confidence: number; // 0..1 — parser's self-rated confidence
}
