import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "VDB2 Scrapper Panel",
  description: "Upload criteria, run scraper, and download enriched Excel sheet inputs dynamically.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        {children}
      </body>
    </html>
  );
}
