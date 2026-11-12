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
  unread_count?: number;
};

export type TimelineEvent = {
  at?: string | null;
  type: string;
  title: string;
  detail?: string;
};

export type CallRow = {
  row_key: string;
  row_number?: number;
  name?: string;
  email?: string;
  phone_no?: string;
  dial_to?: string;
  address?: string;
  zoho_lead_id?: string;
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
  offer_page?: string;
  monthly_bill?: number | null;
  report_sent?: boolean;
  report_email_type?: string;
  self_booked?: boolean;
  followup_email_status?: string;
  followup_email_attempt?: number;
  next_followup_email_at?: string;
  pipeline_stage?: string;
  pipeline_label?: string;
  next_action?: string;
  bill_count?: number;
  bills?: BillRow[];
  business_unit?: string;
  has_streetview?: boolean;
  streetview_fetched_at?: string | null;
  has_lighting_preview?: boolean;
  streetview_render_fetched_at?: string | null;
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

export type StageCounts = Record<string, number>;

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

export function fetchConversations(
  q = "",
  lastReadByPhone: Record<string, string> = {},
  company: "energy" | "lights" = "energy",
) {
  const params = new URLSearchParams({ q, company });
  if (Object.keys(lastReadByPhone).length > 0) {
    params.set("reads", JSON.stringify(lastReadByPhone));
  }
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

export function isLightsLead(lead: {
  business_unit?: string;
  row_key?: string;
}) {
  const unit = (lead.business_unit || "")
    .toLowerCase()
    .replace(/-/g, " ")
    .replace(/_/g, " ");
  if (unit.includes("light")) return true;
  if (unit.includes("energy") || unit.includes("solar")) return false;
  return (lead.row_key || "").startsWith("lights_");
}

export function fetchCalls(
  q = "",
  filter = "all",
  company: "energy" | "lights" | "" = "",
) {
  const params = new URLSearchParams({ q, filter });
  if (company) params.set("company", company);
  return apiFetch<{
    calls: CallRow[];
    count: number;
    stage_counts?: StageCounts;
  }>(`/api/admin/calls?${params}`);
}

export function fetchCall(rowKey: string) {
  return apiFetch<CallRow>(`/api/admin/calls/${encodeURIComponent(rowKey)}`);
}

export function fetchLeadTimeline(rowKey: string) {
  return apiFetch<{
    row_key: string;
    events: TimelineEvent[];
    count: number;
  }>(`/api/admin/calls/${encodeURIComponent(rowKey)}/timeline`);
}

export function startVoiceCall(rowKey: string) {
  return apiFetch<{
    ok: boolean;
    call_sid?: string;
    to_number?: string;
    conversation_id?: string;
  }>(`/api/admin/calls/${encodeURIComponent(rowKey)}/start-voice-call`, {
    method: "POST",
  });
}

export function cancelFollowupCalls(rowKey: string) {
  return apiFetch<{ ok: boolean; cancelled: boolean; callback_status?: string }>(
    `/api/admin/calls/${encodeURIComponent(rowKey)}/cancel-followup-calls`,
    { method: "POST" },
  );
}

export function cancelFollowupEmails(rowKey: string) {
  return apiFetch<{
    ok: boolean;
    cancelled: boolean;
    followup_email_status?: string;
  }>(`/api/admin/calls/${encodeURIComponent(rowKey)}/cancel-followup-emails`, {
    method: "POST",
  });
}

export function fetchLeadStreetview(rowKey: string) {
  return apiFetch<{ ok: boolean; fetched_at?: string }>(
    `/api/admin/calls/${encodeURIComponent(rowKey)}/streetview`,
    { method: "POST" },
  );
}

export const DEFAULT_IMAGE_MODEL = "gpt-image-2.5-sunburst";

export const IMAGE_MODELS: { id: string; label: string }[] = [
  { id: "gpt-image-2.5-sunburst", label: "GPT Image 2.5 Sunburst" },
  { id: "gpt-image-2.5-flare", label: "GPT Image 2.5 Flare" },
  { id: "gpt-image-2.5-sunburst-2026-09-08", label: "GPT Image 2.5 Sunburst (Sep 2026)" },
  { id: "gpt-image-2.5-flare-2026-09-08", label: "GPT Image 2.5 Flare (Sep 2026)" },
  { id: "gpt-image-2", label: "GPT Image 2" },
  { id: "gpt-image-2-2026-04-21", label: "GPT Image 2 (Apr 2026)" },
  { id: "gpt-image-1.5", label: "GPT Image 1.5" },
  { id: "chatgpt-image-latest", label: "ChatGPT Image latest" },
];

export function fetchImageModels() {
  return apiFetch<{ default: string; models: { id: string; label: string }[] }>(
    "/api/admin/image-models",
  );
}

export function renderLightingPreview(rowKey: string, extraPrompt = "", model = "") {
  return apiFetch<{ ok: boolean; fetched_at?: string }>(
    `/api/admin/calls/${encodeURIComponent(rowKey)}/streetview/render`,
    {
      method: "POST",
      body: JSON.stringify({ extra_prompt: extraPrompt, model }),
    },
  );
}

export function lightingPreviewUrl(rowKey: string, version?: string | null) {
  const params = new URLSearchParams();
  if (version) params.set("v", version);
  const q = params.toString();
  return `${API_BASE}/api/admin/calls/${encodeURIComponent(rowKey)}/streetview/render${
    q ? `?${q}` : ""
  }`;
}

export function streetviewImageUrl(rowKey: string, version?: string | null) {
  const params = new URLSearchParams();
  if (version) params.set("v", version);
  const q = params.toString();
  return `${API_BASE}/api/admin/calls/${encodeURIComponent(rowKey)}/streetview${
    q ? `?${q}` : ""
  }`;
}

export function fetchBillSignedUrl(billId: number, download = false) {
  const params = download ? "?download=true" : "";
  return apiFetch<{ url: string; content_type: string; original_name: string }>(
    `/api/admin/bills/${billId}/signed-url${params}`,
  );
}

export type SalesLead = {
  row_key: string;
  name?: string;
  email?: string;
  phone_no?: string;
  dial_to?: string;
  offer_page?: string;
  zoho_lead_id?: string;
  has_zoho?: boolean;
  pipeline_label?: string;
  processed_at?: string;
  business_unit?: string;
};

export function fetchSalesLeads(
  q = "",
  zohoOnly = false,
  company: "energy" | "lights" = "energy",
) {
  const params = new URLSearchParams({ q, company });
  if (zohoOnly) params.set("zoho_only", "true");
  return apiFetch<{ leads: SalesLead[]; count: number }>(
    `/api/admin/sales/leads?${params}`,
  );
}

export function submitSalesClose(body: {
  row_key: string;
  note?: string;
  note_title?: string;
  sale_revenue?: number | null;
  pre_sight_profit?: number | null;
  post_inspection_profit?: number | null;
  sale_date?: string | null;
}) {
  return apiFetch<{
    ok: boolean;
    row_key: string;
    zoho_lead_id: string;
    lead_name: string;
    updated_fields: string[];
    note_created: boolean;
  }>("/api/admin/sales/close", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function customerPhoneForMessage(m: Message): string {
  return m.direction === "inbound"
    ? (m.from_address || "").trim()
    : (m.to_address || "").trim();
}
