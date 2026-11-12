"use client";

import type { Conversation } from "@/lib/api";

type Props = {
  conversations: Conversation[];
  loading: boolean;
  search: string;
  onSearchChange: (v: string) => void;
  selectedPhone: string | null;
  onSelect: (phone: string, name?: string) => void;
  onNewChat: () => void;
  /** Hide list when a thread is open (mobile swap) */
  mobileHidden?: boolean;
  isMobile?: boolean;
  emptyLabel?: string;
};

function fmtTime(iso?: string, compact = false) {
  if (!iso) return "";
  const d = new Date(iso);
  const now = new Date();
  const sameDay =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate();
  if (sameDay || compact) {
    return d.toLocaleTimeString(undefined, {
      hour: "numeric",
      minute: "2-digit",
    });
  }
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function unreadLabel(n: number) {
  if (n <= 0) return "";
  return n > 99 ? "99+" : String(n);
}

function initials(name?: string) {
  const parts = (name || "?").trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

export function ConversationList({
  conversations,
  loading,
  search,
  onSearchChange,
  selectedPhone,
  onSelect,
  onNewChat,
  mobileHidden = false,
  isMobile = false,
  emptyLabel = "No conversations yet",
}: Props) {
  return (
    <aside
      data-inbox-list
      className={`flex shrink-0 flex-col border-r border-lumi-border bg-white ${
        isMobile ? "w-full" : "w-[360px] xl:w-[400px]"
      } ${mobileHidden ? "hidden" : "flex"}`}
    >
      <div className="border-b border-lumi-border p-3">
        {!isMobile ? (
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-lumi-muted">
            Conversations
          </p>
        ) : null}
        <div className="flex gap-2">
          <input
            type="search"
            placeholder="Search name or phone…"
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            className="min-h-[44px] flex-1 rounded-lg border border-lumi-border px-3 py-2 text-base md:text-sm"
          />
          <button
            type="button"
            onClick={onNewChat}
            title="New message"
            aria-label="New message"
            className="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg bg-lumi-blue text-xl text-white hover:bg-blue-700"
          >
            +
          </button>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
        {loading ? (
          <p className="p-4 text-sm text-lumi-muted">Loading…</p>
        ) : conversations.length === 0 ? (
          <p className="p-4 text-sm text-lumi-muted">{emptyLabel}</p>
        ) : (
          conversations.map((c) => {
            const active = c.phone === selectedPhone;
            const unread = active ? 0 : c.unread_count || 0;
            const hasUnread = unread > 0;
            return (
              <button
                key={c.phone}
                type="button"
                onClick={() => onSelect(c.phone, c.lead_name)}
                className={`flex w-full items-start gap-3 border-b border-lumi-border px-3 py-3 text-left transition hover:bg-lumi-bg active:bg-blue-50 ${
                  active ? "bg-blue-50" : ""
                }`}
              >
                <div
                  className={`mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-xs font-bold ${
                    hasUnread
                      ? "bg-lumi-blue text-white"
                      : "bg-gray-100 text-gray-600"
                  }`}
                >
                  {initials(c.lead_name || c.phone)}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline justify-between gap-2">
                    <span
                      className={`truncate text-sm ${
                        hasUnread ? "font-bold text-gray-900" : "font-semibold"
                      }`}
                    >
                      {c.lead_name || "Unknown"}
                    </span>
                    <span
                      className={`shrink-0 text-[11px] ${
                        hasUnread
                          ? "font-semibold text-lumi-green"
                          : "text-lumi-muted"
                      }`}
                    >
                      {fmtTime(c.last_message_at)}
                    </span>
                  </div>
                  <div className="mt-0.5 flex items-center gap-2">
                    <span
                      className={`min-w-0 flex-1 truncate text-xs ${
                        hasUnread ? "font-medium text-gray-800" : "text-gray-500"
                      }`}
                    >
                      {c.last_direction === "outbound" ? "You: " : ""}
                      {c.last_message || c.phone || "—"}
                    </span>
                    {hasUnread ? (
                      <span
                        className="inline-flex min-w-[1.25rem] shrink-0 items-center justify-center rounded-full bg-lumi-green px-1.5 py-0.5 text-[11px] font-bold leading-none text-white"
                        aria-label={`${unread} unread`}
                      >
                        {unreadLabel(unread)}
                      </span>
                    ) : null}
                  </div>
                </div>
              </button>
            );
          })
        )}
      </div>
    </aside>
  );
}
