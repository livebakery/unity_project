"use client";

import { BKK_DISTRICTS } from "@/lib/districts";
import { SKILL_LABELS, type SkillLevel } from "@/lib/types";

export interface FilterState {
  district: string;
  skill: string;
}

export default function Filters({
  value,
  onChange,
}: {
  value: FilterState;
  onChange: (next: FilterState) => void;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      <select
        className="rounded border bg-white px-3 py-2 text-sm"
        value={value.district}
        onChange={(e) => onChange({ ...value, district: e.target.value })}
      >
        <option value="">ทุกเขต</option>
        {BKK_DISTRICTS.map((d) => (
          <option key={d} value={d}>
            เขต{d}
          </option>
        ))}
      </select>

      <select
        className="rounded border bg-white px-3 py-2 text-sm"
        value={value.skill}
        onChange={(e) => onChange({ ...value, skill: e.target.value })}
      >
        <option value="">ทุกระดับ</option>
        {(Object.keys(SKILL_LABELS) as SkillLevel[]).map((s) => (
          <option key={s} value={s}>
            {SKILL_LABELS[s]}
          </option>
        ))}
      </select>
    </div>
  );
}
