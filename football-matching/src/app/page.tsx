"use client";

import { useEffect, useState } from "react";
import MatchCard, { type MatchView } from "@/components/MatchCard";
import Filters, { type FilterState } from "@/components/Filters";

export default function HomePage() {
  const [filter, setFilter] = useState<FilterState>({ district: "", skill: "" });
  const [matches, setMatches] = useState<MatchView[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const params = new URLSearchParams();
    if (filter.district) params.set("district", filter.district);
    if (filter.skill) params.set("skill", filter.skill);

    setLoading(true);
    fetch(`/api/matches?${params}`)
      .then((r) => r.json())
      .then((d) => setMatches(d.matches ?? []))
      .finally(() => setLoading(false));
  }, [filter]);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold">ก๊วนที่กำลังหาคน</h1>
        <p className="text-sm text-gray-500">เลือกเขต/ระดับ แล้วกดติดต่อหัวหน้าก๊วนได้เลย</p>
      </div>

      <Filters value={filter} onChange={setFilter} />

      {loading ? (
        <p className="text-gray-400">กำลังโหลด…</p>
      ) : matches.length === 0 ? (
        <p className="text-gray-400">ยังไม่มีนัดในเงื่อนไขนี้ — ลองเปลี่ยนเขต หรือเป็นคนแรกที่โพสต์</p>
      ) : (
        <div className="space-y-3">
          {matches.map((m) => (
            <MatchCard key={m.id} m={m} />
          ))}
        </div>
      )}
    </div>
  );
}
