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
    <>
      <div className="flex items-center gap-3 border-b border-lumi-border bg-white px-4 py-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-lumi-blue text-sm font-bold text-white">
          {(leadName || phone).charAt(0).toUpperCase()}
        </div>
        <div>
          <div className="font-semibold">{leadName || "Unknown"}</div>
          <div className="text-xs text-lumi-muted">{phone}</div>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
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
                  className={`max-w-[75%] rounded-lg px-3 py-2 text-sm shadow-sm ${
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

      <div className="flex gap-2 border-t border-lumi-border bg-white p-3">
        <textarea
          rows={2}
          placeholder="Type a message…"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          className="min-h-[44px] flex-1 resize-none rounded-lg border border-lumi-border px-3 py-2 text-sm"
        />
        <button
          type="button"
          disabled={sending || !draft.trim()}
          onClick={submit}
          className="self-end rounded-lg bg-lumi-blue px-5 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {sending ? "…" : "Send"}
        </button>
      </div>
    </>
  );
}
