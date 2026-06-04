import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "ก๊วนบอล — หาก๊วน หาคนเตะบอล",
  description: "รวมนัดเตะบอลในกรุงเทพฯ แยกโซน-เขต + แผนที่สนาม",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="th">
      <body>
        <header className="bg-pitch text-white">
          <nav className="mx-auto flex max-w-3xl items-center gap-4 px-4 py-3">
            <Link href="/" className="text-lg font-bold">
              ⚽ ก๊วนบอล
            </Link>
            <div className="flex-1" />
            <Link href="/" className="text-sm hover:underline">
              หาก๊วน
            </Link>
            <Link href="/map" className="text-sm hover:underline">
              แผนที่
            </Link>
            <Link
              href="/create"
              className="rounded bg-white/20 px-3 py-1 text-sm font-medium hover:bg-white/30"
            >
              + โพสต์นัด
            </Link>
          </nav>
        </header>
        <main className="mx-auto max-w-3xl px-4 py-6">{children}</main>
      </body>
    </html>
  );
}
