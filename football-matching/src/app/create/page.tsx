"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { SKILL_LABELS, type ParsedMatch, type SkillLevel } from "@/lib/types";

const SAMPLE = `คืนนี้ 20:00 สนามอารีน่า ลาดพร้าว 7 คน
ขาดอีก 2 คน เอากองหลังนะ มือใหม่ก็มาได้
หาร 70 บ. ติดต่อ LINE: kaikai089 โทร 0891112222`;

export default function CreatePage() {
  const router = useRouter();
  const [rawText, setRawText] = useState("");
  const [hostName, setHostName] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [parsed, setParsed] = useState<ParsedMatch | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function handleParse() {
    setBusy(true);
    setError("");
    try {
      const res = await fetch("/api/parse", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ rawText }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "parse_failed");
      setParsed(data.parsed);
    } catch (e) {
      setError("แยกข้อความไม่สำเร็จ ลองใหม่อีกครั้ง");
    } finally {
      setBusy(false);
    }
  }

  async function handleSubmit() {
    if (!parsed) return;
    setBusy(true);
    setError("");
    try {
      const res = await fetch("/api/matches", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ parsed, hostName, rawText, sourceUrl: sourceUrl || undefined }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "create_failed");
      router.push("/");
    } catch (e) {
      setError("บันทึกไม่สำเร็จ ตรวจวันเวลา/สนามให้ครบก่อนนะ");
    } finally {
      setBusy(false);
    }
  }

  function update<K extends keyof ParsedMatch>(key: K, val: ParsedMatch[K]) {
    setParsed((p) => (p ? { ...p, [key]: val } : p));
  }

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">โพสต์นัดเตะ</h1>

      <div>
        <label className="text-sm font-medium">วางข้อความจาก Facebook / LINE</label>
        <textarea
          className="mt-1 h-36 w-full rounded border p-3 text-sm"
          placeholder={SAMPLE}
          value={rawText}
          onChange={(e) => setRawText(e.target.value)}
        />
        <button
          className="mt-2 rounded bg-pitch px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          onClick={handleParse}
          disabled={busy || rawText.trim().length < 5}
        >
          {busy ? "กำลังแยก…" : "🤖 ให้ AI แยกข้อมูล"}
        </button>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}

      {parsed && (
        <div className="space-y-3 rounded-lg border bg-white p-4">
          <p className="text-sm text-gray-500">
            ตรวจ/แก้ข้อมูลก่อนโพสต์ (ความมั่นใจ AI: {Math.round(parsed.confidence * 100)}%)
          </p>

          <Field label="ชื่อคุณ (หัวหน้าก๊วน)">
            <input className="input" value={hostName} onChange={(e) => setHostName(e.target.value)} />
          </Field>

          <div className="grid grid-cols-2 gap-3">
            <Field label="วันที่">
              <input
                type="date"
                className="input"
                value={parsed.kickoffDate ?? ""}
                onChange={(e) => update("kickoffDate", e.target.value)}
              />
            </Field>
            <Field label="เวลา">
              <input
                type="time"
                className="input"
                value={parsed.kickoffTime ?? ""}
                onChange={(e) => update("kickoffTime", e.target.value)}
              />
            </Field>
          </div>

          <Field label="สนาม">
            <input
              className="input"
              value={parsed.venueName ?? ""}
              onChange={(e) => update("venueName", e.target.value)}
            />
          </Field>

          <div className="grid grid-cols-2 gap-3">
            <Field label="ประเภท (คน)">
              <select
                className="input"
                value={parsed.matchType ?? 7}
                onChange={(e) => update("matchType", Number(e.target.value))}
              >
                {[5, 7, 11].map((n) => (
                  <option key={n} value={n}>
                    {n} คน
                  </option>
                ))}
              </select>
            </Field>
            <Field label="ขาดกี่คน">
              <input
                type="number"
                className="input"
                value={parsed.playersNeeded ?? 1}
                onChange={(e) => update("playersNeeded", Number(e.target.value))}
              />
            </Field>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Field label="ระดับฝีเท้า">
              <select
                className="input"
                value={parsed.skillLevel}
                onChange={(e) => update("skillLevel", e.target.value as SkillLevel)}
              >
                {(Object.keys(SKILL_LABELS) as SkillLevel[]).map((s) => (
                  <option key={s} value={s}>
                    {SKILL_LABELS[s]}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="ราคา/คน (บาท)">
              <input
                type="number"
                className="input"
                value={parsed.pricePerHead ?? ""}
                onChange={(e) =>
                  update("pricePerHead", e.target.value ? Number(e.target.value) : null)
                }
              />
            </Field>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Field label="LINE ID">
              <input
                className="input"
                value={parsed.contactLine ?? ""}
                onChange={(e) => update("contactLine", e.target.value || null)}
              />
            </Field>
            <Field label="เบอร์โทร">
              <input
                className="input"
                value={parsed.contactTel ?? ""}
                onChange={(e) => update("contactTel", e.target.value || null)}
              />
            </Field>
          </div>

          <Field label="ลิงก์โพสต์ต้นฉบับ (ถ้า seed จาก FB — ไม่บังคับ)">
            <input
              className="input"
              placeholder="https://facebook.com/..."
              value={sourceUrl}
              onChange={(e) => setSourceUrl(e.target.value)}
            />
          </Field>

          <button
            className="w-full rounded bg-pitch px-4 py-2 font-medium text-white disabled:opacity-50"
            onClick={handleSubmit}
            disabled={busy || !hostName}
          >
            {busy ? "กำลังโพสต์…" : "โพสต์นัด"}
          </button>
        </div>
      )}

      <style jsx>{`
        :global(.input) {
          width: 100%;
          border: 1px solid #d1d5db;
          border-radius: 0.375rem;
          padding: 0.5rem;
          font-size: 0.875rem;
        }
      `}</style>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-sm text-gray-600">{label}</span>
      <div className="mt-1">{children}</div>
    </label>
  );
}
