"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Conversation,
  Message,
  customerPhoneForMessage,
  fetchConversationMessages,
  fetchConversations,
  sendMessage,
} from "@/lib/api";
import { connectAdminWs } from "@/lib/ws";
import { ConversationList } from "./ConversationList";
import { MessageThread } from "./MessageThread";

function normalizePhoneInput(raw: string): string {
  const digits = raw.replace(/\D/g, "");
  if (digits.length === 10) return `+1${digits}`;
  if (digits.length === 11 && digits.startsWith("1")) return `+${digits}`;
  if (raw.trim().startsWith("+")) return `+${digits}`;
  return raw.trim();
}

export function ChatLayout() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [search, setSearch] = useState("");
  const [selectedPhone, setSelectedPhone] = useState<string | null>(null);
  const [leadName, setLeadName] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [loadingList, setLoadingList] = useState(true);
  const [loadingThread, setLoadingThread] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [composeNew, setComposeNew] = useState(false);
  const [newPhone, setNewPhone] = useState("");

  const loadConversations = useCallback(async () => {
    setLoadingList(true);
    try {
      const data = await fetchConversations(search);
      setConversations(data.conversations);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load conversations");
    } finally {
      setLoadingList(false);
    }
  }, [search]);

  const loadThread = useCallback(async (phone: string) => {
    setLoadingThread(true);
    setError("");
    try {
      const data = await fetchConversationMessages(phone);
      setMessages(data.messages);
      setLeadName(data.lead_name || "");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load messages");
    } finally {
      setLoadingThread(false);
    }
  }, []);

  useEffect(() => {
    const t = setTimeout(loadConversations, search ? 300 : 0);
    return () => clearTimeout(t);
  }, [loadConversations, search]);

  useEffect(() => {
    if (selectedPhone) {
      loadThread(selectedPhone);
      setComposeNew(false);
    }
  }, [selectedPhone, loadThread]);

  useEffect(() => {
    return connectAdminWs((msg) => {
      const phone = customerPhoneForMessage(msg);
      if (!phone) return;

      setConversations((prev) => {
        const rest = prev.filter((c) => c.phone !== phone);
        const existing = prev.find((c) => c.phone === phone);
        const updated: Conversation = {
          phone,
          lead_name: msg.lead_name || existing?.lead_name || "",
          last_message: msg.body?.slice(0, 120),
          last_message_at: msg.created_at || new Date().toISOString(),
          last_direction: msg.direction,
        };
        return [updated, ...rest].sort((a, b) =>
          (b.last_message_at || "").localeCompare(a.last_message_at || ""),
        );
      });

      if (selectedPhone === phone) {
        setMessages((prev) => {
          if (msg.id != null && prev.some((m) => m.id === msg.id)) return prev;
          return [...prev, { ...msg, created_at: msg.created_at || new Date().toISOString() }];
        });
      }
    });
  }, [selectedPhone]);

  const handleSelect = (phone: string, name?: string) => {
    setSelectedPhone(phone);
    if (name) setLeadName(name);
  };

  const handleStartNew = () => {
    setComposeNew(true);
    setSelectedPhone(null);
    setMessages([]);
    setLeadName("");
    setNewPhone("");
  };

  const handleConfirmNew = () => {
    const phone = normalizePhoneInput(newPhone);
    if (!phone || phone.length < 11) {
      setError("Enter a valid phone number");
      return;
    }
    setError("");
    setSelectedPhone(phone);
    setMessages([]);
    setComposeNew(false);
  };

  const handleSend = async (text: string) => {
    if (!selectedPhone) return;
    setSending(true);
    setError("");
    const optimistic: Message = {
      direction: "outbound",
      channel: "sms",
      message_type: "admin_manual",
      body: text,
      to_address: selectedPhone,
      status: "sending",
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, optimistic]);
    try {
      await sendMessage(selectedPhone, text);
      await loadThread(selectedPhone);
      await loadConversations();
    } catch (e) {
      setMessages((prev) => prev.filter((m) => m !== optimistic));
      setError(e instanceof Error ? e.message : "Send failed");
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="flex h-full">
      <ConversationList
        conversations={conversations}
        loading={loadingList}
        search={search}
        onSearchChange={setSearch}
        selectedPhone={selectedPhone}
        onSelect={handleSelect}
        onNewChat={handleStartNew}
      />

      <div className="flex min-w-0 flex-1 flex-col bg-[#e5ddd5]">
        {composeNew ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-4 bg-lumi-bg p-8">
            <h2 className="text-lg font-semibold">New message</h2>
            <input
              type="tel"
              placeholder="+1 (480) 555-1234"
              value={newPhone}
              onChange={(e) => setNewPhone(e.target.value)}
              className="w-full max-w-md rounded-lg border border-lumi-border px-4 py-3"
            />
            <button
              type="button"
              onClick={handleConfirmNew}
              className="rounded-lg bg-lumi-blue px-6 py-2 text-white hover:bg-blue-700"
            >
              Start chat
            </button>
          </div>
        ) : selectedPhone ? (
          <MessageThread
            phone={selectedPhone}
            leadName={leadName}
            messages={messages}
            loading={loadingThread}
            sending={sending}
            onSend={handleSend}
          />
        ) : (
          <div className="flex flex-1 items-center justify-center text-lumi-muted">
            Select a conversation or start a new message
          </div>
        )}
        {error && (
          <div className="border-t border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
            {error}
          </div>
        )}
      </div>
    </div>
  );
}
