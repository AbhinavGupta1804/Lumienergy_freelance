import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Lumi Energy Admin",
  description: "Calls and customer SMS",
  appleWebApp: {
    capable: true,
    statusBarStyle: "default",
    title: "Lumi Admin",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  viewportFit: "cover",
  themeColor: "#F8FAFC",
};

/** Runs before paint — phones only (incl. Desktop-site); not laptops */
const FORCE_MOBILE_SCRIPT = `
(function () {
  try {
    var ua = navigator.userAgent || "";
    var min = Math.min(screen.width || 0, screen.height || 0);
    var uaMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(ua);
    var coarse = false;
    try { coarse = window.matchMedia("(pointer: coarse)").matches; } catch (e) {}
    var touch = (navigator.maxTouchPoints || 0) > 1;
    var phoneDesktopSite = min > 0 && min < 768 && (uaMobile || coarse || touch);
    if (uaMobile || phoneDesktopSite) {
      document.documentElement.classList.add("force-mobile");
    }
  } catch (e) {}
})();
`;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: FORCE_MOBILE_SCRIPT }} />
      </head>
      <body className="overscroll-none">{children}</body>
    </html>
  );
}
