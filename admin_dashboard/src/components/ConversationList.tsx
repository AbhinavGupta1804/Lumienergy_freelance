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
  /** On mobile, hide list when a thread is open */
  mobileHidden?: boolean;
};

function fmtTime(iso?: string) {
  if (!iso) return "";
  return new Date(iso).toLocaleString(undefined, {
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

export function ConversationList({
  conversations,
  loading,
  search,
  onSearchChange,
  selectedPhone,
  onSelect,
  onNewChat,
  mobileHidden = false,
}: Props) {
  return (
    <aside
      className={`flex w-full shrink-0 flex-col border-r border-lumi-border bg-white md:w-80 ${
        mobileHidden ? "hidden md:flex" : "flex"
      }`}
    >
      <div className="border-b border-lumi-border p-3">
        <div className="mb-0 flex gap-2">
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
          <p className="p-4 text-sm text-lumi-muted">No conversations yet</p>
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
                className={`flex w-full flex-col gap-0.5 border-b border-lumi-border px-4 py-3.5 text-left transition hover:bg-lumi-bg active:bg-blue-50 ${
                  active ? "bg-blue-50" : ""
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span
                    className={`truncate text-sm ${
                      hasUnread ? "font-bold text-gray-900" : "font-semibold"
                    }`}
                  >
                    {c.lead_name || "Unknown"}
                  </span>
                  <div className="flex shrink-0 items-center gap-2">
                    <span
                      className={`text-[10px] ${
                        hasUnread ? "font-semibold text-lumi-green" : "text-lumi-muted"
                      }`}
                    >
                      {fmtTime(c.last_message_at)}
                    </span>
                    {hasUnread ? (
                      <span
                        className="inline-flex min-w-[1.25rem] items-center justify-center rounded-full bg-lumi-green px-1.5 py-0.5 text-[11px] font-bold leading-none text-white"
                        aria-label={`${unread} unread`}
                      >
                        {unreadLabel(unread)}
                      </span>
                    ) : null}
                  </div>
                </div>
                <span className="text-xs text-lumi-muted">{c.phone}</span>
                <span
                  className={`truncate text-xs ${
                    hasUnread ? "font-medium text-gray-800" : "text-gray-600"
                  }`}
                >
                  {c.last_direction === "outbound" ? "You: " : ""}
                  {c.last_message || "—"}
                </span>
              </button>
            );
          })
        )}
      </div>
    </aside>
  );
}
