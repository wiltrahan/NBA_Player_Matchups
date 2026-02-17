import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "NBA Matchup Finder",
  description: "Daily NBA prop matchup explorer",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
