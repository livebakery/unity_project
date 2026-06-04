import { SKILL_LABELS, type SkillLevel } from "@/lib/types";

export interface MatchView {
  id: string;
  hostName: string;
  kickoffAt: string;
  matchType: number;
  playersNeeded: number;
  positionsNeeded: string[];
  pricePerHead: number | null;
  skillLevel: SkillLevel;
  contactLine: string | null;
  contactTel: string | null;
  sourceUrl: string | null;
  venue: { name: string; district: string | null; gmapsUrl: string | null };
}

function fmtWhen(iso: string) {
  return new Date(iso).toLocaleString("th-TH", {
    timeZone: "Asia/Bangkok",
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function MatchCard({ m }: { m: MatchView }) {
  return (
    <div className="rounded-lg border bg-white p-4 shadow-sm">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="font-semibold">{m.venue.name}</div>
          <div className="text-sm text-gray-500">
            {m.venue.district ? `เขต${m.venue.district} · ` : ""}
            {fmtWhen(m.kickoffAt)}
          </div>
        </div>
        <span className="shrink-0 rounded-full bg-green-100 px-2 py-1 text-xs text-green-800">
          ขาด {m.playersNeeded} คน
        </span>
      </div>

      <div className="mt-3 flex flex-wrap gap-2 text-xs">
        <span className="rounded bg-gray-100 px-2 py-1">{m.matchType} คน</span>
        <span className="rounded bg-gray-100 px-2 py-1">{SKILL_LABELS[m.skillLevel]}</span>
        {m.positionsNeeded.map((p) => (
          <span key={p} className="rounded bg-gray-100 px-2 py-1">
            {p}
          </span>
        ))}
        {m.pricePerHead != null && (
          <span className="rounded bg-gray-100 px-2 py-1">{m.pricePerHead} บ./คน</span>
        )}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-3 text-sm">
        {m.contactTel && (
          <a className="text-pitch underline" href={`tel:${m.contactTel}`}>
            📞 {m.contactTel}
          </a>
        )}
        {m.contactLine && <span className="text-gray-600">LINE: {m.contactLine}</span>}
        {m.venue.gmapsUrl && (
          <a className="text-blue-600 underline" href={m.venue.gmapsUrl} target="_blank" rel="noreferrer">
            🗺️ นำทาง
          </a>
        )}
        {m.sourceUrl && (
          <a className="ml-auto text-xs text-gray-400 underline" href={m.sourceUrl} target="_blank" rel="noreferrer">
            ที่มา
          </a>
        )}
      </div>
      <div className="mt-2 text-xs text-gray-400">โดย {m.hostName}</div>
    </div>
  );
}
