"use client";

import { useEffect, useRef, useState } from "react";
import type { MatchView } from "@/components/MatchCard";

// Bangkok center
const CENTER = { lat: 13.7563, lng: 100.5018 };

declare global {
  interface Window {
    google?: typeof google;
  }
}

function loadGoogleMaps(key: string): Promise<void> {
  if (window.google?.maps) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const existing = document.getElementById("gmaps-js");
    if (existing) {
      existing.addEventListener("load", () => resolve());
      return;
    }
    const s = document.createElement("script");
    s.id = "gmaps-js";
    s.src = `https://maps.googleapis.com/maps/api/js?key=${key}&language=th&region=TH`;
    s.async = true;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error("failed to load Google Maps"));
    document.head.appendChild(s);
  });
}

export default function MapPage() {
  const mapRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const key = process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY;
    if (!key) {
      setError("ยังไม่ได้ตั้งค่า NEXT_PUBLIC_GOOGLE_MAPS_API_KEY");
      return;
    }

    let cancelled = false;
    (async () => {
      try {
        await loadGoogleMaps(key);
        const res = await fetch("/api/matches");
        const { matches } = (await res.json()) as { matches: MatchView[] };
        if (cancelled || !mapRef.current) return;

        const map = new google.maps.Map(mapRef.current, { center: CENTER, zoom: 11 });
        const info = new google.maps.InfoWindow();

        type V = MatchView & { venue: { lat?: number; lng?: number } };
        for (const m of matches as V[]) {
          const { lat, lng } = m.venue;
          if (lat == null || lng == null) continue;
          const marker = new google.maps.Marker({
            position: { lat, lng },
            map,
            title: m.venue.name,
          });
          marker.addListener("click", () => {
            info.setContent(
              `<div style="font-size:13px"><b>${m.venue.name}</b><br/>` +
                `${new Date(m.kickoffAt).toLocaleString("th-TH")}<br/>` +
                `ขาด ${m.playersNeeded} คน · ${m.matchType} คน</div>`,
            );
            info.open(map, marker);
          });
        }
      } catch {
        if (!cancelled) setError("โหลดแผนที่ไม่สำเร็จ");
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="space-y-3">
      <h1 className="text-xl font-bold">แผนที่สนาม</h1>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div ref={mapRef} className="h-[70vh] w-full rounded-lg border" />
    </div>
  );
}
