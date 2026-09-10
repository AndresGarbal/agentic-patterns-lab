import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Agentic Patterns Lab",
  description: "Demo agents, each built to show a specific agentic pattern.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-neutral-950 text-neutral-100 antialiased">
        <div className="mx-auto max-w-3xl px-6 py-12">{children}</div>
        {/* Phase 4: the narrator widget mounts here so it survives navigation. */}
      </body>
    </html>
  );
}
