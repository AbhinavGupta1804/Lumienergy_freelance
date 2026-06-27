import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Lumi Energy Admin",
  description: "Calls and customer SMS",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
