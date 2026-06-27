export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") || "http://localhost:8000";

export const WS_URL =
  process.env.NEXT_PUBLIC_WS_URL ||
  API_BASE.replace(/^http/, "ws") + "/api/admin/ws";

export type Message = {
  id?: number | null;
  direction: "inbound" | "outbound";
  channel: string;
  message_type?: string;
  body: string;
  from_address?: string;
  to_address?: string;
  lead_name?: string;
  lead_row_key?: string;
  provider_id?: string | null;
  status?: string;
  created_at?: string;
};

export type Conversation = {
  phone: string;
  lead_name?: string;
  last_message?: string;
  last_message_at?: string;
  last_direction?: string;
};

export type CallRow = {
  row_key: string;
  row_number?: number;
  name?: string;
  email?: string;
  phone_no?: string;
  dial_to?: string;
  address?: string;
  processed_at?: string;
  call_ended_at?: string;
  first_call_at?: string;
  call_duration_secs?: number;
  call_successful?: string;
  status?: string;
  termination_reason?: string;
  sms_eligible?: boolean;
  sms_sent?: boolean;
  upload_token_used?: boolean;
  confirmation_sms_sent?: boolean;
  appointment_start?: string;
  appointment_label?: string;
  callback_status?: string;
  callback_attempt?: number;
  next_retry_at?: string;
  call_in_progress?: boolean;
  last_twilio_status?: string;
  call_sid?: string;
  conversation_id?: string;
  cal_booking_uid?: string;
  google_event_uid?: string;
  transcript_summary?: string;
  bill_count?: number;
  bills?: BillRow[];
  [key: string]: unknown;
};

export type BillRow = {
  id: number;
  original_name?: string;
  content_type?: string;
  uploaded_at?: string;
  size_bytes?: number;
  status?: string;
};

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export function fetchConversations(q = "") {
  const params = new URLSearchParams({ q });
  return apiFetch<{ conversations: Conversation[]; count: number }>(
    `/api/admin/conversations?${params}`,
  );
}

export function fetchConversationMessages(phone: string) {
  const params = new URLSearchParams({ phone });
  return apiFetch<{
    phone: string;
    lead_name: string;
    messages: Message[];
    count: number;
  }>(`/api/admin/conversations/messages?${params}`);
}

export function sendMessage(phone: string, body: string) {
  return apiFetch<{ ok: boolean; message_sid?: string }>(
    "/api/admin/conversations/messages",
    {
      method: "POST",
      body: JSON.stringify({ phone, body }),
    },
  );
}

export function fetchCalls(q = "", filter = "all") {
  const params = new URLSearchParams({ q, filter });
  return apiFetch<{ calls: CallRow[]; count: number }>(
    `/api/admin/calls?${params}`,
  );
}

export function fetchCall(rowKey: string) {
  return apiFetch<CallRow>(`/api/admin/calls/${encodeURIComponent(rowKey)}`);
}

export function fetchBillSignedUrl(billId: number, download = false) {
  const params = download ? "?download=true" : "";
  return apiFetch<{ url: string; content_type: string; original_name: string }>(
    `/api/admin/bills/${billId}/signed-url${params}`,
  );
}

export function customerPhoneForMessage(m: Message): string {
  return m.direction === "inbound"
    ? (m.from_address || "").trim()
    : (m.to_address || "").trim();
}
