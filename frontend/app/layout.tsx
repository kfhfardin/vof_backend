import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Lien — AI intake supervision",
  description: "Live AI intake for personal injury law firms",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="min-h-screen text-ink">{children}</body>
    </html>
  );
}
