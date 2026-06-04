import { NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import type { ParsedMatch } from "@/lib/types";

export const runtime = "nodejs";

// GET /api/matches?district=&zone=&day=&skill=  -> open matches (not expired)
export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const district = searchParams.get("district");
  const skill = searchParams.get("skill");

  const matches = await prisma.match.findMany({
    where: {
      status: "open",
      expiresAt: { gt: new Date() },
      ...(skill ? { skillLevel: skill as never } : {}),
      ...(district ? { venue: { district } } : {}),
    },
    include: { venue: true },
    orderBy: { kickoffAt: "asc" },
    take: 100,
  });

  return NextResponse.json({ matches });
}

// POST /api/matches — create a match from a confirmed/edited ParsedMatch + host info.
// venueName is geocoded into a Venue (reused if it already exists).
export async function POST(req: Request) {
  try {
    const body = (await req.json()) as {
      parsed: ParsedMatch;
      hostName: string;
      rawText: string;
      sourceUrl?: string;
    };
    const { parsed, hostName, rawText, sourceUrl } = body;

    if (!hostName || !parsed?.kickoffDate || !parsed.kickoffTime || !parsed.venueName) {
      return NextResponse.json(
        { error: "hostName, kickoffDate, kickoffTime, venueName are required" },
        { status: 400 },
      );
    }

    const venue = await upsertVenue(parsed.venueName, parsed.district);

    const kickoffAt = new Date(`${parsed.kickoffDate}T${parsed.kickoffTime}:00+07:00`);
    const durationMin = 120;
    const expiresAt = new Date(kickoffAt.getTime() + durationMin * 60_000);

    const match = await prisma.match.create({
      data: {
        hostName,
        venueId: venue.id,
        kickoffAt,
        durationMin,
        matchType: parsed.matchType ?? 7,
        playersNeeded: parsed.playersNeeded ?? 1,
        positionsNeeded: parsed.positionsNeeded ?? [],
        pricePerHead: parsed.pricePerHead,
        skillLevel: parsed.skillLevel,
        contactLine: parsed.contactLine,
        contactTel: parsed.contactTel,
        rawText,
        sourceUrl: sourceUrl ?? null,
        expiresAt,
      },
      include: { venue: true },
    });

    return NextResponse.json({ match }, { status: 201 });
  } catch (err) {
    console.error("create match error", err);
    return NextResponse.json({ error: "create_failed" }, { status: 500 });
  }
}

// Find-or-create a Venue, geocoding the name via Google Maps when possible.
async function upsertVenue(name: string, district: string | null) {
  const existing = await prisma.venue.findFirst({ where: { name } });
  if (existing) return existing;

  const geo = await geocode(name);
  return prisma.venue.create({
    data: {
      name,
      address: geo?.address ?? null,
      lat: geo?.lat ?? null,
      lng: geo?.lng ?? null,
      gmapsPlaceId: geo?.placeId ?? null,
      gmapsUrl: geo?.placeId
        ? `https://www.google.com/maps/place/?q=place_id:${geo.placeId}`
        : null,
      district: geo?.district ?? district,
    },
  });
}

async function geocode(query: string) {
  const key = process.env.GOOGLE_MAPS_SERVER_KEY;
  if (!key) return null;
  const url = new URL("https://maps.googleapis.com/maps/api/geocode/json");
  url.searchParams.set("address", query);
  url.searchParams.set("region", "th");
  url.searchParams.set("language", "th");
  url.searchParams.set("key", key);

  const res = await fetch(url);
  const data = await res.json();
  const r = data.results?.[0];
  if (!r) return null;

  // เขต กทม. มักอยู่ใน administrative_area_level_2 (เช่น "เขตห้วยขวาง")
  const adminL2 = r.address_components?.find((c: { types: string[]; long_name: string }) =>
    c.types.includes("administrative_area_level_2"),
  );
  const district = adminL2?.long_name?.replace(/^เขต/, "").trim() ?? null;

  return {
    address: r.formatted_address as string,
    lat: r.geometry.location.lat as number,
    lng: r.geometry.location.lng as number,
    placeId: r.place_id as string,
    district,
  };
}
