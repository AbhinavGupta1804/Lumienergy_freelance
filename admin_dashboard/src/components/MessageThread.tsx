"use client";

import { useEffect, useRef, useState } from "react";
import type { Message } from "@/lib/api";

type Props = {
  phone: string;
  leadName: string;
  messages: Message[];
  loading: boolean;
  sending: boolean;
  onSend: (text: string) => Promise<void>;
  onBack?: () => void;
};

function fmtBubbleTime(iso?: string) {
  if (!iso) return "";
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
}

export function MessageThread({
  phone,
  leadName,
  messages,
  loading,
  sending,
  onSend,
  onBack,
}: Props) {
  const [draft, setDraft] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const submit = async () => {
    const text = draft.trim();
    if (!text || sending) return;
    setDraft("");
    await onSend(text);
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-2 border-b border-lumi-border bg-white px-2 py-2.5 sm:gap-3 sm:px-4 sm:py-3">
        {onBack ? (
          <button
            type="button"
            onClick={onBack}
            aria-label="Back to conversations"
            className="flex min-h-[44px] min-w-[44px] shrink-0 items-center justify-center rounded-lg text-lumi-blue hover:bg-lumi-bg md:hidden"
          >
            <svg
              width="22"
              height="22"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden
            >
              <path d="M15 18l-6-6 6-6" />
            </svg>
          </button>
        ) : null}
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-lumi-blue text-sm font-bold text-white">
          {(leadName || phone).charAt(0).toUpperCase()}
        </div>
        <div className="min-w-0">
          <div className="truncate font-semibold">{leadName || "Unknown"}</div>
          <div className="truncate text-xs text-lumi-muted">{phone}</div>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-3 py-4 sm:px-4">
        {loading ? (
          <p className="text-center text-sm text-lumi-muted">Loading messages…</p>
        ) : messages.length === 0 ? (
          <p className="text-center text-sm text-lumi-muted">
            No messages yet. Send the first one below.
          </p>
        ) : (
          messages.map((m, i) => {
            const outbound = m.direction === "outbound";
            return (
              <div
                key={m.id ?? `msg-${i}`}
                className={`mb-2 flex ${outbound ? "justify-end" : "justify-start"}`}
              >
                <div
                  className={`max-w-[85%] rounded-lg px-3 py-2 text-sm shadow-sm sm:max-w-[75%] ${
                    outbound
                      ? "rounded-br-none bg-[#dcf8c6]"
                      : "rounded-bl-none bg-white"
                  }`}
                >
                  <p className="whitespace-pre-wrap break-words">{m.body}</p>
                  <p className="mt-1 text-right text-[10px] text-gray-500">
                    {fmtBubbleTime(m.created_at)}
                    {m.status?.startsWith("failed") && (
                      <span className="ml-1 text-red-600">failed</span>
                    )}
                  </p>
                </div>
              </div>
            );
          })
        )}
        <div ref={bottomRef} />
      </div>

      <div className="flex gap-2 border-t border-lumi-border bg-white p-3 safe-pb">
        <textarea
          rows={1}
          placeholder="Type a message…"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          className="min-h-[44px] max-h-32 flex-1 resize-none rounded-lg border border-lumi-border px-3 py-2.5 text-base md:text-sm"
        />
        <button
          type="button"
          disabled={sending || !draft.trim()}
          onClick={submit}
          className="min-h-[44px] self-end rounded-lg bg-lumi-blue px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 sm:px-5"
        >
          {sending ? "…" : "Send"}
        </button>
      </div>
    </div>
  );
}
