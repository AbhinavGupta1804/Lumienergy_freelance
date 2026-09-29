/** Persist when each SMS thread was last opened (WhatsApp-style unread). */

const STORAGE_KEY = "lumi-admin-inbox-last-read";

export type LastReadMap = Record<string, string>;

export function loadLastReadMap(): LastReadMap {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== "object") return {};
    const out: LastReadMap = {};
    for (const [phone, ts] of Object.entries(parsed as Record<string, unknown>)) {
      if (phone && typeof ts === "string" && ts) out[phone] = ts;
    }
    return out;
  } catch {
    return {};
  }
}

export function saveLastReadMap(map: LastReadMap): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(map));
  } catch {
    /* quota / private mode */
  }
}

export function markConversationRead(
  phone: string,
  at: string = new Date().toISOString(),
): LastReadMap {
  const map = loadLastReadMap();
  map[phone] = at;
  saveLastReadMap(map);
  return map;
}
