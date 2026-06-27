"use client";

import { useCallback, useEffect, useState } from "react";
import {
  BillRow,
  CallRow,
  fetchBillSignedUrl,
  fetchCall,
  fetchCalls,
} from "@/lib/api";

function fmtDate(iso?: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function fmtDuration(secs?: number | string | null) {
  if (secs == null || secs === "") return "—";
  const n = Number(secs);
  if (Number.isNaN(n)) return "—";
  const m = Math.floor(n / 60);
  const s = n % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function fmtBytes(bytes?: number | null) {
  if (!bytes) return "";
  const n = Number(bytes);
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function yesNo(val?: boolean | null) {
  if (val == null) return "—";
  return val ? "Yes" : "No";
}

function callStatusPill(row: CallRow) {
  const val = String(row.call_successful || "").toLowerCase();
  if (["true", "success", "yes", "1"].includes(val)) {
    return <Pill label="Success" tone="green" />;
  }
  if (["false", "failure", "failed", "no", "0"].includes(val)) {
    return <Pill label="Failed" tone="red" />;
  }
  if (row.call_successful) {
    return <Pill label={String(row.call_successful)} tone="amber" />;
  }
  return <Pill label={row.status || "—"} tone="gray" />;
}

function callbackPill(row: CallRow) {
  const st = (row.callback_status || "none").toLowerCase();
  if (st === "answered") return <Pill label="Answered" tone="green" />;
  if (st === "active") {
    const next = row.next_retry_at ? fmtDate(row.next_retry_at) : "pending";
    return <Pill label={`Active · ${next}`} tone="amber" />;
  }
  if (st === "exhausted") return <Pill label="Exhausted" tone="red" />;
  if (st === "none") return <Pill label="None" tone="gray" />;
  return <Pill label={row.callback_status || "—"} tone="gray" />;
}

function billPill(count?: number) {
  const n = count ?? 0;
  if (n > 0) return <Pill label={`${n} file${n > 1 ? "s" : ""}`} tone="blue" />;
  return <Pill label="None" tone="gray" />;
}

function smsPill(sent?: boolean) {
  return sent ? <Pill label="Sent" tone="green" /> : <Pill label="No" tone="gray" />;
}

function Pill({
  label,
  tone,
}: {
  label: string;
  tone: "green" | "red" | "amber" | "blue" | "gray";
}) {
  const tones = {
    green: "bg-emerald-50 text-emerald-700",
    red: "bg-red-50 text-red-700",
    amber: "bg-amber-50 text-amber-800",
    blue: "bg-blue-50 text-blue-700",
    gray: "bg-gray-100 text-gray-600",
  };
  return (
    <span
      className={`inline-block max-w-[140px] truncate rounded-full px-2 py-0.5 text-xs font-medium ${tones[tone]}`}
      title={label}
    >
      {label}
    </span>
  );
}

export function CallsView() {
  const [calls, setCalls] = useState<CallRow[]>([]);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [detail, setDetail] = useState<CallRow | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewType, setPreviewType] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchCalls(search, filter);
      setCalls(data.calls);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load calls");
    } finally {
      setLoading(false);
    }
  }, [search, filter]);

  useEffect(() => {
    const t = setTimeout(load, search ? 300 : 0);
    return () => clearTimeout(t);
  }, [load, search]);

  useEffect(() => {
    if (!selectedKey) {
      setDetail(null);
      return;
    }
    fetchCall(selectedKey)
      .then(setDetail)
      .catch(() => setDetail(calls.find((c) => c.row_key === selectedKey) || null));
  }, [selectedKey, calls]);

  const viewBill = async (bill: BillRow) => {
    try {
      const { url, content_type } = await fetchBillSignedUrl(bill.id, false);
      setPreviewUrl(url);
      setPreviewType(content_type || "");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load bill");
    }
  };

  const downloadBill = async (bill: BillRow) => {
    try {
      const { url } = await fetchBillSignedUrl(bill.id, true);
      window.open(url, "_blank");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not download bill");
    }
  };

  return (
    <div className="flex h-full">
      <section className="flex w-[58%] flex-col border-r border-lumi-border bg-white">
        <div className="flex gap-2 border-b border-lumi-border p-3">
          <input
            type="search"
            placeholder="Search name, phone, address…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="flex-1 rounded-lg border border-lumi-border px-3 py-2 text-sm"
          />
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="rounded-lg border border-lumi-border px-2 py-2 text-sm"
          >
            <option value="all">All calls</option>
            <option value="bill_uploaded">Bill uploaded</option>
            <option value="no_bill">No bill</option>
            <option value="sms_sent">SMS sent</option>
            <option value="call_failed">Call failed</option>
            <option value="callback_active">Callback scheduled</option>
          </select>
          <button
            type="button"
            onClick={load}
            className="rounded-lg border border-lumi-border px-3 py-2 text-sm hover:bg-lumi-bg"
          >
            Refresh
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-auto">
          <table className="w-full text-left text-sm">
            <thead className="sticky top-0 z-10 bg-gray-50 text-xs text-lumi-muted">
              <tr>
                <th className="px-3 py-2">Name</th>
                <th className="px-3 py-2">Phone</th>
                <th className="px-3 py-2">Date</th>
                <th className="px-3 py-2">Duration</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">SMS</th>
                <th className="px-3 py-2">Callback</th>
                <th className="px-3 py-2">Bill</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={8} className="px-3 py-6 text-center text-lumi-muted">
                    Loading…
                  </td>
                </tr>
              ) : calls.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-3 py-6 text-center text-lumi-muted">
                    No calls found
                  </td>
                </tr>
              ) : (
                calls.map((row) => (
                  <tr
                    key={row.row_key}
                    onClick={() => {
                      setSelectedKey(row.row_key);
                      setPreviewUrl(null);
                    }}
                    className={`cursor-pointer border-t border-lumi-border hover:bg-lumi-bg ${
                      selectedKey === row.row_key ? "bg-blue-50" : ""
                    }`}
                  >
                    <td className="px-3 py-2 font-medium">{row.name || "—"}</td>
                    <td className="px-3 py-2 whitespace-nowrap">
                      {row.dial_to || row.phone_no || "—"}
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap text-xs">
                      {fmtDate(row.processed_at)}
                    </td>
                    <td className="px-3 py-2">{fmtDuration(row.call_duration_secs)}</td>
                    <td className="px-3 py-2">{callStatusPill(row)}</td>
                    <td className="px-3 py-2">{smsPill(row.sms_sent)}</td>
                    <td className="px-3 py-2">{callbackPill(row)}</td>
                    <td className="px-3 py-2">{billPill(row.bill_count)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        {error && (
          <p className="border-t border-red-200 bg-red-50 p-2 text-sm text-red-700">{error}</p>
        )}
      </section>

      <section className="min-w-0 flex-1 overflow-auto bg-white">
        {!detail ? (
          <p className="p-6 text-lumi-muted">Select a call to view details</p>
        ) : (
          <div className="p-6">
            <div className="mb-4 flex items-start justify-between gap-4">
              <div>
                <h2 className="text-xl font-bold">{detail.name || "Unknown"}</h2>
                <p className="text-sm text-lumi-muted">{detail.row_key}</p>
              </div>
              {callStatusPill(detail)}
            </div>

            <DetailSection title="Contact">
              <FieldGrid>
                <Field label="Phone" value={detail.phone_no} />
                <Field label="Dialled to" value={detail.dial_to} />
                <Field label="Email" value={detail.email} />
                <Field label="Address" value={detail.address} full />
              </FieldGrid>
            </DetailSection>

            <DetailSection title="Call">
              <FieldGrid>
                <Field label="Call date" value={fmtDate(detail.processed_at)} />
                <Field label="Call ended" value={fmtDate(detail.call_ended_at)} />
                <Field label="Duration" value={fmtDuration(detail.call_duration_secs)} />
                <Field label="Termination" value={detail.termination_reason} />
                <Field label="In progress" value={yesNo(detail.call_in_progress)} />
                <Field label="Last Twilio status" value={detail.last_twilio_status} />
              </FieldGrid>
            </DetailSection>

            <DetailSection title="SMS & notifications">
              <FieldGrid>
                <Field label="SMS eligible" value={yesNo(detail.sms_eligible)} />
                <Field label="Bill-upload SMS sent" value={yesNo(detail.sms_sent)} />
                <Field label="Bill link used" value={yesNo(detail.upload_token_used)} />
                <Field
                  label="Confirmation SMS sent"
                  value={yesNo(detail.confirmation_sms_sent)}
                />
              </FieldGrid>
            </DetailSection>

            <DetailSection title="Callback">
              <div className="mb-3">{callbackPill(detail)}</div>
              <FieldGrid>
                <Field label="Status" value={detail.callback_status} />
                <Field
                  label="Attempts completed"
                  value={
                    detail.callback_attempt != null
                      ? String(detail.callback_attempt)
                      : "—"
                  }
                />
                <Field label="Next retry at" value={fmtDate(detail.next_retry_at)} />
                <Field label="First call at" value={fmtDate(detail.first_call_at)} />
              </FieldGrid>
            </DetailSection>

            <DetailSection title="Appointment">
              <FieldGrid>
                <Field label="Scheduled" value={detail.appointment_label} full />
                <Field label="Start (ISO)" value={detail.appointment_start} />
                <Field label="Cal.com booking" value={detail.cal_booking_uid} mono />
                <Field label="Google event" value={detail.google_event_uid} mono />
              </FieldGrid>
            </DetailSection>

            <DetailSection title="IDs">
              <FieldGrid>
                <Field label="Call SID" value={detail.call_sid} mono />
                <Field label="Conversation ID" value={detail.conversation_id} mono />
                <Field label="Sheet row #" value={detail.row_number?.toString()} />
              </FieldGrid>
            </DetailSection>

            <DetailSection title="Transcript summary">
              <p className="text-sm leading-relaxed text-gray-700">
                {detail.transcript_summary || "No summary available."}
              </p>
            </DetailSection>

            <DetailSection title={`Uploaded bills (${detail.bill_count ?? 0})`}>
              {(detail.bills || []).length === 0 ? (
                <p className="text-sm text-lumi-muted">No bill uploaded yet.</p>
              ) : (
                <ul className="space-y-2">
                  {(detail.bills || []).map((b) => (
                    <li
                      key={b.id}
                      className="flex items-center justify-between gap-3 rounded-lg border border-lumi-border p-3"
                    >
                      <div className="min-w-0">
                        <p className="truncate font-medium text-sm">
                          {b.original_name || "Uploaded file"}
                        </p>
                        <p className="text-xs text-lumi-muted">
                          {[fmtDate(b.uploaded_at), fmtBytes(b.size_bytes), b.status]
                            .filter(Boolean)
                            .join(" · ")}
                        </p>
                      </div>
                      <div className="flex shrink-0 gap-2">
                        <button
                          type="button"
                          onClick={() => viewBill(b)}
                          className="rounded-md bg-lumi-blue px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700"
                        >
                          View
                        </button>
                        <button
                          type="button"
                          onClick={() => downloadBill(b)}
                          className="rounded-md border border-lumi-border px-3 py-1.5 text-xs hover:bg-lumi-bg"
                        >
                          Download
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
              {previewUrl && (
                <div className="mt-4 rounded-lg border border-lumi-border bg-lumi-bg p-2">
                  <div className="mb-2 flex items-center justify-between">
                    <span className="text-xs font-medium text-lumi-muted">Preview</span>
                    <button
                      type="button"
                      onClick={() => setPreviewUrl(null)}
                      className="text-xs text-lumi-blue hover:underline"
                    >
                      Close
                    </button>
                  </div>
                  {previewType.startsWith("image/") ? (
                    <img src={previewUrl} alt="Bill preview" className="mx-auto max-h-96" />
                  ) : previewType === "application/pdf" ? (
                    <iframe
                      src={previewUrl}
                      title="Bill PDF"
                      className="h-96 w-full rounded border-0"
                    />
                  ) : (
                    <p className="p-4 text-sm text-lumi-muted">
                      Preview not available — use Download.
                    </p>
                  )}
                </div>
              )}
            </DetailSection>
          </div>
        )}
      </section>
    </div>
  );
}

function DetailSection({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mb-5 border-b border-lumi-border pb-5 last:border-0">
      <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-lumi-muted">
        {title}
      </h3>
      {children}
    </div>
  );
}

function FieldGrid({ children }: { children: React.ReactNode }) {
  return <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">{children}</dl>;
}

function Field({
  label,
  value,
  mono,
  full,
}: {
  label: string;
  value?: string | null;
  mono?: boolean;
  full?: boolean;
}) {
  return (
    <div className={full ? "col-span-2" : undefined}>
      <dt className="text-xs text-lumi-muted">{label}</dt>
      <dd className={`break-words ${mono ? "font-mono text-xs" : ""}`}>
        {value || "—"}
      </dd>
    </div>
  );
}
