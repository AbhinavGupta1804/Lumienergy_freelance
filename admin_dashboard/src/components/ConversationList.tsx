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

export function ConversationList({
  conversations,
  loading,
  search,
  onSearchChange,
  selectedPhone,
  onSelect,
  onNewChat,
}: Props) {
  return (
    <aside className="flex w-80 shrink-0 flex-col border-r border-lumi-border bg-white">
      <div className="border-b border-lumi-border p-3">
        <div className="mb-2 flex gap-2">
          <input
            type="search"
            placeholder="Search name or phone…"
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            className="flex-1 rounded-lg border border-lumi-border px-3 py-2 text-sm"
          />
          <button
            type="button"
            onClick={onNewChat}
            title="New message"
            className="rounded-lg bg-lumi-blue px-3 py-2 text-lg text-white hover:bg-blue-700"
          >
            +
          </button>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {loading ? (
          <p className="p-4 text-sm text-lumi-muted">Loading…</p>
        ) : conversations.length === 0 ? (
          <p className="p-4 text-sm text-lumi-muted">No conversations yet</p>
        ) : (
          conversations.map((c) => {
            const active = c.phone === selectedPhone;
            return (
              <button
                key={c.phone}
                type="button"
                onClick={() => onSelect(c.phone, c.lead_name)}
                className={`flex w-full flex-col gap-0.5 border-b border-lumi-border px-4 py-3 text-left transition hover:bg-lumi-bg ${
                  active ? "bg-blue-50" : ""
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate font-semibold text-sm">
                    {c.lead_name || "Unknown"}
                  </span>
                  <span className="shrink-0 text-[10px] text-lumi-muted">
                    {fmtTime(c.last_message_at)}
                  </span>
                </div>
                <span className="text-xs text-lumi-muted">{c.phone}</span>
                <span className="truncate text-xs text-gray-600">
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
