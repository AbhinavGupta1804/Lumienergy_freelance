"use client";

import { useCallback, useEffect, useState } from "react";
import {
  BillRow,
  CallRow,
  StageCounts,
  TimelineEvent,
  cancelFollowupCalls,
  cancelFollowupEmails,
  fetchBillSignedUrl,
  fetchCall,
  fetchCalls,
  fetchLeadTimeline,
} from "@/lib/api";

const STAGE_CHIPS: { id: string; label: string }[] = [
  { id: "all", label: "All" },
  { id: "trying", label: "Trying" },
  { id: "reached", label: "Reached" },
  { id: "booked", label: "Booked" },
  { id: "self_booked", label: "Self-booked" },
  { id: "report_pending", label: "Report pending" },
  { id: "report_sent", label: "Report sent" },
  { id: "followup_emails", label: "Follow-up emails" },
  { id: "bill_uploaded", label: "Bill uploaded" },
  { id: "confirmed", label: "Confirmed" },
  { id: "exhausted", label: "Exhausted" },
  { id: "failed", label: "Failed" },
];

const FOLLOWUP_EMAIL_MAX = 4;

function fmtDate(iso?: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

/** Arizona business time — matches follow-up email scheduling. */
function fmtAz(iso?: string | null) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const stamped = d.toLocaleString("en-US", {
    timeZone: "America/Phoenix",
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
  return `${stamped} AZ`;
}

function fmtDuration(secs?: number | null) {
  if (secs == null) return "—";
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

function offerLabel(offer?: string | null) {
  const o = (offer || "").toLowerCase();
  if (o === "aps-hike") return "APS";
  if (o === "zero-down") return "Zero Down";
  if (o === "battery-rebate") return "Battery";
  if (o === "solar-roi-calculator") return "Solar ROI";
  if (o === "getquote") return "Get Quote";
  return offer || "—";
}

const REPORT_ELIGIBLE_OFFERS = new Set([
  "aps-hike",
  "zero-down",
  "solar-roi-calculator",
  "getquote",
]);

function stageTone(
  stage?: string,
): "green" | "red" | "amber" | "blue" | "gray" | "purple" {
  switch ((stage || "").toLowerCase()) {
    case "confirmed":
    case "booked":
    case "self_booked":
    case "bill_uploaded":
      return "green";
    case "trying":
    case "report_sent":
    case "reached":
      return "amber";
    case "exhausted":
    case "failed":
      return "red";
    case "new":
      return "blue";
    default:
      return "gray";
  }
}

function Pill({
  label,
  tone,
}: {
  label: string;
  tone: "green" | "red" | "amber" | "blue" | "gray" | "purple";
}) {
  const tones = {
    green: "bg-emerald-50 text-emerald-700",
    red: "bg-red-50 text-red-700",
    amber: "bg-amber-50 text-amber-800",
    blue: "bg-blue-50 text-blue-700",
    gray: "bg-gray-100 text-gray-600",
    purple: "bg-violet-50 text-violet-700",
  };
  return (
    <span
      className={`inline-block max-w-[160px] truncate rounded-full px-2 py-0.5 text-xs font-medium ${tones[tone]}`}
      title={label}
    >
      {label}
    </span>
  );
}

function stagePill(row: CallRow) {
  const label = row.pipeline_label || row.pipeline_stage || "—";
  return <Pill label={label} tone={stageTone(row.pipeline_stage)} />;
}

function reportPill(row: CallRow) {
  if (row.report_sent) {
    const t = (row.report_email_type || "").includes("without")
      ? "No cal link"
      : (row.report_email_type || "").includes("with")
        ? "With cal"
        : "Sent";
    return <Pill label={t} tone="green" />;
  }
  const offer = (row.offer_page || "").toLowerCase();
  if (REPORT_ELIGIBLE_OFFERS.has(offer)) {
    return <Pill label="Pending" tone="amber" />;
  }
  return <Pill label="N/A" tone="gray" />;
}

function followupEmailPill(row: CallRow) {
  const status = (row.followup_email_status || "none").toLowerCase();
  const attempt = row.followup_email_attempt ?? 0;
  if (status === "active") {
    return (
      <Pill
        label={`${attempt}/${FOLLOWUP_EMAIL_MAX} · next`}
        tone="amber"
      />
    );
  }
  if (status === "booked") return <Pill label="Stopped · booked" tone="green" />;
  if (status === "cancelled") return <Pill label="Cancelled" tone="gray" />;
  if (status === "exhausted") return <Pill label="Exhausted" tone="red" />;
  if (status === "none" || !row.followup_email_status) {
    return <Pill label="—" tone="gray" />;
  }
  return <Pill label={status} tone="gray" />;
}

function followupEmailSummary(row: CallRow) {
  const status = (row.followup_email_status || "none").toLowerCase();
  const attempt = row.followup_email_attempt ?? 0;
  if (status === "active") {
    const when = row.next_followup_email_at
      ? fmtAz(row.next_followup_email_at)
      : "time TBD";
    return {
      statusLabel: "Active",
      attempts: `${attempt} of ${FOLLOWUP_EMAIL_MAX} sent`,
      nextLabel: when,
      remaining: Math.max(FOLLOWUP_EMAIL_MAX - attempt, 0),
    };
  }
  if (status === "none" || !row.followup_email_status) {
    return null;
  }
  return {
    statusLabel: status.replace(/_/g, " "),
    attempts: `${attempt} of ${FOLLOWUP_EMAIL_MAX} sent`,
    nextLabel: "—",
    remaining: 0,
  };
}

export function CallsView() {
  const [calls, setCalls] = useState<CallRow[]>([]);
  const [counts, setCounts] = useState<StageCounts>({});
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [detail, setDetail] = useState<CallRow | null>(null);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewType, setPreviewType] = useState("");
  const [cancelBusy, setCancelBusy] = useState<"calls" | "emails" | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchCalls(search, filter);
      setCalls(data.calls);
      setCounts(data.stage_counts || {});
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load leads");
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
      setTimeline([]);
      return;
    }
    Promise.all([fetchCall(selectedKey), fetchLeadTimeline(selectedKey)])
      .then(([d, t]) => {
        setDetail(d);
        setTimeline(t.events || []);
      })
      .catch(() => {
        setDetail(calls.find((c) => c.row_key === selectedKey) || null);
        setTimeline([]);
      });
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

  const doCancelFollowup = async (kind: "calls" | "emails") => {
    if (!detail) return;
    setCancelBusy(kind);
    try {
      if (kind === "calls") {
        await cancelFollowupCalls(detail.row_key);
      } else {
        await cancelFollowupEmails(detail.row_key);
      }
      const fresh = await fetchCall(detail.row_key);
      setDetail(fresh);
      setError("");
      load();
    } catch (e) {
      setError(
        e instanceof Error ? e.message : `Could not cancel follow-up ${kind}`,
      );
    } finally {
      setCancelBusy(null);
    }
  };

  const showDetail = Boolean(selectedKey);

  const selectLead = (rowKey: string) => {
    setSelectedKey(rowKey);
    setPreviewUrl(null);
  };

  const clearSelection = () => {
    setSelectedKey(null);
    setDetail(null);
    setTimeline([]);
    setPreviewUrl(null);
  };

  return (
    <div className="flex h-full">
      <section
        className={`flex w-full flex-col border-r border-lumi-border bg-white lg:w-[58%] ${
          showDetail ? "hidden lg:flex" : "flex"
        }`}
      >
        <div className="space-y-3 border-b border-lumi-border p-3">
          <div className="flex gap-2">
            <input
              type="search"
              placeholder="Search name, phone, email…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="min-h-[44px] flex-1 rounded-lg border border-lumi-border px-3 py-2 text-base md:text-sm"
            />
            <button
              type="button"
              onClick={load}
              className="min-h-[44px] rounded-lg border border-lumi-border px-3 py-2 text-sm hover:bg-lumi-bg"
            >
              Refresh
            </button>
          </div>
          <div className="-mx-3 flex gap-1.5 overflow-x-auto px-3 pb-0.5 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden lg:flex-wrap lg:overflow-visible">
            {STAGE_CHIPS.map((chip) => {
              const count = chip.id === "all" ? counts.all : counts[chip.id];
              const active = filter === chip.id;
              return (
                <button
                  key={chip.id}
                  type="button"
                  onClick={() => setFilter(chip.id)}
                  className={`shrink-0 rounded-full px-3 py-1.5 text-xs font-medium transition ${
                    active
                      ? "bg-lumi-blue text-white"
                      : "bg-lumi-bg text-lumi-muted hover:text-gray-900"
                  }`}
                >
                  {chip.label}
                  {count != null ? (
                    <span className={`ml-1 ${active ? "opacity-80" : ""}`}>
                      {count}
                    </span>
                  ) : null}
                </button>
              );
            })}
          </div>
        </div>

        {/* Mobile card list */}
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain lg:hidden">
          {loading ? (
            <p className="p-4 text-center text-sm text-lumi-muted">Loading…</p>
          ) : calls.length === 0 ? (
            <p className="p-4 text-center text-sm text-lumi-muted">No leads found</p>
          ) : (
            calls.map((row) => (
              <button
                key={row.row_key}
                type="button"
                onClick={() => selectLead(row.row_key)}
                className="flex w-full flex-col gap-1.5 border-b border-lumi-border px-4 py-3.5 text-left active:bg-blue-50"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="truncate font-semibold text-sm">
                      {row.name || "—"}
                    </div>
                    <div className="truncate text-xs text-lumi-muted">
                      {row.dial_to || row.phone_no || "—"}
                    </div>
                  </div>
                  {stagePill(row)}
                </div>
                <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-lumi-muted">
                  <span>{offerLabel(row.offer_page)}</span>
                  {row.callback_attempt != null ? (
                    <span>· {row.callback_attempt} tries</span>
                  ) : null}
                  {row.appointment_label || row.self_booked ? (
                    <span>
                      · {row.appointment_label || (row.self_booked ? "Self" : "")}
                    </span>
                  ) : null}
                </div>
                {row.next_action ? (
                  <p className="line-clamp-2 text-xs text-gray-600">{row.next_action}</p>
                ) : null}
              </button>
            ))
          )}
        </div>

        {/* Desktop table */}
        <div className="hidden min-h-0 flex-1 overflow-auto lg:block">
          <table className="w-full text-left text-sm">
            <thead className="sticky top-0 z-10 bg-gray-50 text-xs text-lumi-muted">
              <tr>
                <th className="px-3 py-2">Lead</th>
                <th className="px-3 py-2">Offer</th>
                <th className="px-3 py-2">Stage</th>
                <th className="px-3 py-2">Call tries</th>
                <th className="px-3 py-2">Report</th>
                <th className="px-3 py-2">FU email</th>
                <th className="px-3 py-2">Next FU email</th>
                <th className="px-3 py-2">Appt</th>
                <th className="px-3 py-2">Next action</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={9} className="px-3 py-6 text-center text-lumi-muted">
                    Loading…
                  </td>
                </tr>
              ) : calls.length === 0 ? (
                <tr>
                  <td colSpan={9} className="px-3 py-6 text-center text-lumi-muted">
                    No leads found
                  </td>
                </tr>
              ) : (
                calls.map((row) => (
                  <tr
                    key={row.row_key}
                    onClick={() => selectLead(row.row_key)}
                    className={`cursor-pointer border-t border-lumi-border hover:bg-lumi-bg ${
                      selectedKey === row.row_key ? "bg-blue-50" : ""
                    }`}
                  >
                    <td className="px-3 py-2">
                      <div className="font-medium">{row.name || "—"}</div>
                      <div className="whitespace-nowrap text-xs text-lumi-muted">
                        {row.dial_to || row.phone_no || "—"}
                      </div>
                    </td>
                    <td className="px-3 py-2 text-xs">{offerLabel(row.offer_page)}</td>
                    <td className="px-3 py-2">{stagePill(row)}</td>
                    <td className="px-3 py-2 text-center">
                      {row.callback_attempt != null ? row.callback_attempt : "—"}
                    </td>
                    <td className="px-3 py-2">{reportPill(row)}</td>
                    <td className="px-3 py-2">{followupEmailPill(row)}</td>
                    <td
                      className="whitespace-nowrap px-3 py-2 text-xs text-gray-700"
                      title={row.next_followup_email_at || ""}
                    >
                      {(row.followup_email_status || "").toLowerCase() === "active"
                        ? fmtAz(row.next_followup_email_at)
                        : "—"}
                    </td>
                    <td
                      className="max-w-[100px] truncate px-3 py-2 text-xs"
                      title={row.appointment_label || ""}
                    >
                      {row.appointment_label || (row.self_booked ? "Self" : "—")}
                    </td>
                    <td className="max-w-[200px] px-3 py-2 text-xs text-gray-700">
                      <span className="line-clamp-2" title={row.next_action || ""}>
                        {row.next_action || "—"}
                      </span>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        {error && !showDetail ? (
          <p className="border-t border-red-200 bg-red-50 p-2 text-sm text-red-700">
            {error}
          </p>
        ) : null}
      </section>

      <section
        className={`min-w-0 flex-1 overflow-auto overscroll-contain bg-white ${
          showDetail ? "flex flex-col" : "hidden lg:block"
        }`}
      >
        {!detail ? (
          <p className="hidden p-6 text-lumi-muted lg:block">
            Select a lead to view journey
          </p>
        ) : (
          <div className="p-4 sm:p-6">
            <div className="mb-4 flex items-start gap-2">
              <button
                type="button"
                onClick={clearSelection}
                aria-label="Back to leads"
                className="mr-1 flex min-h-[44px] min-w-[44px] shrink-0 items-center justify-center rounded-lg text-lumi-blue hover:bg-lumi-bg lg:hidden"
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
              <div className="min-w-0 flex-1">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h2 className="truncate text-lg font-bold sm:text-xl">
                      {detail.name || "Unknown"}
                    </h2>
                    <p className="truncate text-sm text-lumi-muted">
                      {offerLabel(detail.offer_page)}
                      {detail.email ? ` · ${detail.email}` : ""}
                    </p>
                  </div>
                  {stagePill(detail)}
                </div>
              </div>
            </div>

            <div className="mb-5 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
              <p className="text-xs font-semibold uppercase tracking-wide text-amber-800">
                Next action
              </p>
              <p className="text-sm text-amber-950">{detail.next_action || "—"}</p>
            </div>

            {(() => {
              const fu = followupEmailSummary(detail);
              if (!fu) return null;
              return (
                <div className="mb-5 rounded-lg border border-blue-200 bg-blue-50 px-4 py-3">
                  <p className="text-xs font-semibold uppercase tracking-wide text-blue-800">
                    Follow-up emails
                  </p>
                  <div className="mt-2 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
                    <div>
                      <p className="text-[11px] uppercase tracking-wide text-blue-700/80">
                        Status
                      </p>
                      <p className="font-medium capitalize text-blue-950">
                        {fu.statusLabel}
                      </p>
                    </div>
                    <div>
                      <p className="text-[11px] uppercase tracking-wide text-blue-700/80">
                        Attempts
                      </p>
                      <p className="font-medium text-blue-950">{fu.attempts}</p>
                    </div>
                    <div>
                      <p className="text-[11px] uppercase tracking-wide text-blue-700/80">
                        Remaining
                      </p>
                      <p className="font-medium text-blue-950">
                        {(detail.followup_email_status || "").toLowerCase() ===
                        "active"
                          ? fu.remaining
                          : "—"}
                      </p>
                    </div>
                    <div className="col-span-2 sm:col-span-1">
                      <p className="text-[11px] uppercase tracking-wide text-blue-700/80">
                        Next send
                      </p>
                      <p className="font-medium text-blue-950">{fu.nextLabel}</p>
                    </div>
                  </div>
                </div>
              );
            })()}

            <div className="mb-5 flex flex-col gap-2 sm:flex-row sm:flex-wrap">
              <button
                type="button"
                disabled={
                  detail.callback_status !== "active" || cancelBusy !== null
                }
                onClick={() => doCancelFollowup("calls")}
                className="min-h-[44px] rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs font-medium text-red-700 hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {cancelBusy === "calls"
                  ? "Cancelling…"
                  : detail.callback_status === "active"
                    ? "Cancel pending follow-up calls"
                    : detail.callback_status === "cancelled"
                      ? "Follow-up calls cancelled"
                      : "No pending follow-up calls"}
              </button>
              <button
                type="button"
                disabled={
                  detail.followup_email_status !== "active" ||
                  cancelBusy !== null
                }
                onClick={() => doCancelFollowup("emails")}
                className="min-h-[44px] rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs font-medium text-red-700 hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {cancelBusy === "emails"
                  ? "Cancelling…"
                  : detail.followup_email_status === "active"
                    ? "Cancel pending follow-up emails"
                    : detail.followup_email_status === "cancelled"
                      ? "Follow-up emails cancelled"
                      : "No pending follow-up emails"}
              </button>
            </div>

            <DetailSection title="Timeline">
              {timeline.length === 0 ? (
                <p className="text-sm text-lumi-muted">No activity yet.</p>
              ) : (
                <ol className="relative space-y-0 border-l border-lumi-border ml-2">
                  {timeline.map((ev, i) => (
                    <li key={`${ev.at}-${ev.type}-${i}`} className="relative pb-4 pl-4">
                      <span className="absolute -left-1.5 top-1.5 h-3 w-3 rounded-full border-2 border-white bg-lumi-blue" />
                      <p className="text-sm font-medium text-gray-900">{ev.title}</p>
                      {ev.detail ? (
                        <p className="text-xs text-lumi-muted mt-0.5">{ev.detail}</p>
                      ) : null}
                      <p className="text-[11px] text-gray-400 mt-0.5">
                        {fmtDate(ev.at)}
                      </p>
                    </li>
                  ))}
                </ol>
              )}
            </DetailSection>

            <DetailSection title="Contact">
              <FieldGrid>
                <Field label="Phone" value={detail.phone_no} />
                <Field label="Dialled to" value={detail.dial_to} />
                <Field label="Email" value={detail.email} />
                <Field label="Offer page" value={offerLabel(detail.offer_page)} />
                <Field
                  label="Monthly bill"
                  value={
                    detail.monthly_bill != null
                      ? `$${detail.monthly_bill}`
                      : undefined
                  }
                />
                <Field label="Address" value={detail.address} full />
              </FieldGrid>
            </DetailSection>

            <DetailSection title="Pipeline">
              <FieldGrid>
                <Field label="Stage" value={detail.pipeline_label} />
                <Field label="Callback" value={detail.callback_status} />
                <Field
                  label="Attempts"
                  value={
                    detail.callback_attempt != null
                      ? String(detail.callback_attempt)
                      : "—"
                  }
                />
                <Field label="Next retry" value={fmtDate(detail.next_retry_at)} />
                <Field label="Report sent" value={yesNo(detail.report_sent)} />
                <Field
                  label="Report type"
                  value={(detail.report_email_type || "").replace(/_/g, " ") || undefined}
                />
                <Field label="Self-booked" value={yesNo(detail.self_booked)} />
                <Field
                  label="FU email status"
                  value={
                    detail.followup_email_status &&
                    detail.followup_email_status !== "none"
                      ? detail.followup_email_status
                      : "—"
                  }
                />
                <Field
                  label="FU emails sent"
                  value={
                    detail.followup_email_status &&
                    detail.followup_email_status !== "none"
                      ? `${detail.followup_email_attempt ?? 0} / ${FOLLOWUP_EMAIL_MAX}`
                      : "—"
                  }
                />
                <Field
                  label="Next FU email (AZ)"
                  value={
                    (detail.followup_email_status || "").toLowerCase() === "active"
                      ? fmtAz(detail.next_followup_email_at)
                      : "—"
                  }
                />
                <Field label="Appointment" value={detail.appointment_label} full />
              </FieldGrid>
            </DetailSection>

            <DetailSection title="Call details">
              <FieldGrid>
                <Field label="First call" value={fmtDate(detail.first_call_at)} />
                <Field label="Last processed" value={fmtDate(detail.processed_at)} />
                <Field label="Call ended" value={fmtDate(detail.call_ended_at)} />
                <Field label="Duration" value={fmtDuration(detail.call_duration_secs)} />
                <Field label="Termination" value={detail.termination_reason} />
                <Field label="Twilio status" value={detail.last_twilio_status} />
              </FieldGrid>
            </DetailSection>

            <DetailSection title="SMS & notifications">
              <FieldGrid>
                <Field label="SMS eligible" value={yesNo(detail.sms_eligible)} />
                <Field label="Bill-upload SMS" value={yesNo(detail.sms_sent)} />
                <Field label="Bill link used" value={yesNo(detail.upload_token_used)} />
                <Field
                  label="Confirmation sent"
                  value={yesNo(detail.confirmation_sms_sent)}
                />
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
                          className="min-h-[40px] rounded-md bg-lumi-blue px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700"
                        >
                          View
                        </button>
                        <button
                          type="button"
                          onClick={() => downloadBill(b)}
                          className="min-h-[40px] rounded-md border border-lumi-border px-3 py-1.5 text-xs hover:bg-lumi-bg"
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
                    // eslint-disable-next-line @next/next/no-img-element
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

            <DetailSection title="IDs">
              <FieldGrid>
                <Field label="Row key" value={detail.row_key} mono />
                <Field label="Call SID" value={detail.call_sid} mono />
                <Field label="Conversation ID" value={detail.conversation_id} mono />
                <Field label="Cal booking" value={detail.cal_booking_uid} mono />
              </FieldGrid>
            </DetailSection>
            {error ? (
              <p className="mt-2 rounded-lg border border-red-200 bg-red-50 p-2 text-sm text-red-700 lg:hidden">
                {error}
              </p>
            ) : null}
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
  return (
    <dl className="grid grid-cols-1 gap-x-4 gap-y-3 text-sm sm:grid-cols-2">
      {children}
    </dl>
  );
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
