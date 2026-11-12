"use client";

import { useEffect, useState } from "react";

const MOBILE_UA = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i;

function detectMobile(breakpointPx: number): boolean {
  if (typeof window === "undefined") return false;

  // Real layout width (DevTools device mode + normal responsive)
  const mq = window.matchMedia(`(max-width: ${breakpointPx - 1}px)`).matches;

  const uaMobile = MOBILE_UA.test(navigator.userAgent);
  const screenMin = Math.min(window.screen.width || 0, window.screen.height || 0);
  const narrowScreen = screenMin > 0 && screenMin < breakpointPx;
  const coarse = window.matchMedia("(pointer: coarse)").matches;
  const touchPoints = navigator.maxTouchPoints || 0;

  // Phone with Chrome "Desktop site": UA may be desktop + viewport ~980px,
  // but screen is still phone-sized and input is coarse/touch.
  const phoneDesktopSite =
    narrowScreen && (uaMobile || coarse || touchPoints > 1);

  return mq || uaMobile || phoneDesktopSite;
}

/**
 * True on phones (incl. Desktop-site mode). False on laptops/desktops
 * even if they have a touchscreen.
 */
export function useIsMobile(breakpointPx = 768, forceMobile = false): boolean {
  const [mobile, setMobile] = useState(forceMobile);

  useEffect(() => {
    const compute = () => setMobile(forceMobile || detectMobile(breakpointPx));
    compute();
    const mq = window.matchMedia(`(max-width: ${breakpointPx - 1}px)`);
    mq.addEventListener("change", compute);
    window.addEventListener("orientationchange", compute);
    return () => {
      mq.removeEventListener("change", compute);
      window.removeEventListener("orientationchange", compute);
    };
  }, [breakpointPx, forceMobile]);

  return mobile;
}

export function isMobileUserAgent(ua: string | null | undefined): boolean {
  return MOBILE_UA.test(ua || "");
}
