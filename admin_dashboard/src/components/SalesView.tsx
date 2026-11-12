"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  SalesLead,
  fetchSalesLeads,
  submitSalesClose,
} from "@/lib/api";
import { useCompany } from "@/lib/company";
import { useIsMobile } from "@/lib/useIsMobile";

function initials(name?: string) {
  const parts = (name || "?").trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <span className="mb-1.5 block text-[11px] font-semibold uppercase tracking-[0.06em] text-lumi-muted">
      {children}
    </span>
  );
}

const inputClass =
  "min-h-[48px] w-full rounded-xl border border-lumi-border bg-white px-3.5 py-2.5 text-base text-gray-900 outline-none transition placeholder:text-gray-400 focus:border-lumi-blue focus:ring-2 focus:ring-blue-100";

function isLightsSalesLead(lead: SalesLead) {
  const unit = (lead.business_unit || "")
    .toLowerCase()
    .replace(/-/g, " ")
    .replace(/_/g, " ");
  if (unit.includes("light")) return true;
  if (unit.includes("energy") || unit.includes("solar")) return false;
  return (lead.row_key || "").startsWith("lights_");
}

export function SalesView() {
  const isMobile = useIsMobile();
  const { company, ready } = useCompany();
  const requestSeq = useRef(0);
  const brand = company === "lights" ? "Lumi Lights" : "Lumi Energy";
  const [leads, setLeads] = useState<SalesLead[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [noteTitle, setNoteTitle] = useState("");
  const [revenue, setRevenue] = useState("");
  const [preSightProfit, setPreSightProfit] = useState("");
  const [postInspectionProfit, setPostInspectionProfit] = useState("");
  const [saleDate, setSaleDate] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const selected = leads.find((l) => l.row_key === selectedKey) || null;
  const showForm = Boolean(selected);

  const load = useCallback(async () => {
    const requested = company;
    const seq = ++requestSeq.current;
    setLoading(true);
    try {
      const data = await fetchSalesLeads(search, false, requested);
      if (seq !== requestSeq.current) return;
      const visible = data.leads.filter((lead) =>
        requested === "lights" ? isLightsSalesLead(lead) : !isLightsSalesLead(lead),
      );
      setLeads(visible);
      setError("");
    } catch (e) {
      if (seq !== requestSeq.current) return;
      setError(e instanceof Error ? e.message : "Failed to load leads");
    } finally {
      if (seq === requestSeq.current) setLoading(false);
    }
  }, [search, company]);

  useEffect(() => {
    if (!ready) return;
    const t = setTimeout(load, search ? 300 : 0);
    return () => clearTimeout(t);
  }, [load, search, ready]);

  useEffect(() => {
    setSelectedKey(null);
    setSuccess("");
    setError("");
  }, [company]);

  const selectLead = (rowKey: string) => {
    setSelectedKey(rowKey);
    setNote("");
    setNoteTitle("");
    setRevenue("");
    setPreSightProfit("");
    setPostInspectionProfit("");
    setSaleDate("");
    setError("");
    setSuccess("");
  };

  const clearSelection = () => {
    setSelectedKey(null);
    setSuccess("");
    setError("");
  };

  const parseMoney = (raw: string): number | null => {
    const t = raw.trim().replace(/[$,]/g, "");
    if (!t) return null;
    const n = Number(t);
    if (Number.isNaN(n)) throw new Error("Invalid amount");
    return n;
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selected) return;

    let sale_revenue: number | null = null;
    let pre_sight_profit: number | null = null;
    let post_inspection_profit: number | null = null;
    try {
      sale_revenue = parseMoney(revenue);
      pre_sight_profit = parseMoney(preSightProfit);
      post_inspection_profit = parseMoney(postInspectionProfit);
    } catch {
      setError("Revenue and profit must be numbers");
      return;
    }

    const noteText = note.trim();
    const titleText = noteTitle.trim();
    const dateText = saleDate.trim();
    if (
      !noteText &&
      sale_revenue == null &&
      pre_sight_profit == null &&
      post_inspection_profit == null &&
      !dateText
    ) {
      setError("Add at least a note, revenue, profit, or date");
      return;
    }

    setSubmitting(true);
    setError("");
    setSuccess("");
    try {
      const res = await submitSalesClose({
        row_key: selected.row_key,
        note: noteText || undefined,
        note_title: titleText || undefined,
        sale_revenue,
        pre_sight_profit,
        post_inspection_profit,
        sale_date: dateText || null,
      });
      const bits: string[] = [];
      if (res.updated_fields?.length) bits.push("Sale fields updated");
      if (res.note_created) bits.push("Note added");
      setSuccess(bits.join(" · ") || "Saved to Zoho");
      setNote("");
      setNoteTitle("");
      setRevenue("");
      setPreSightProfit("");
      setPostInspectionProfit("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Submit failed");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex h-full bg-lumi-bg">
      {/* Lead list */}
      <section
        className={`flex flex-col bg-white ${
          isMobile
            ? showForm
              ? "hidden"
              : "flex w-full"
            : "flex w-full max-w-md border-r border-lumi-border"
        }`}
      >
        <div className="shrink-0 space-y-3 border-b border-lumi-border px-4 py-3">
          <div>
            <h1 className="text-base font-bold text-gray-900">Close a sale</h1>
            <p className="text-xs text-lumi-muted">
              {brand} leads — notes, revenue, and profit go to Zoho
            </p>
          </div>
          <div className="relative">
            <svg
              className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-lumi-muted"
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              aria-hidden
            >
              <circle cx="11" cy="11" r="7" />
              <path d="M21 21l-4.3-4.3" />
            </svg>
            <input
              type="search"
              placeholder="Search name, phone, email…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className={`${inputClass} pl-10`}
            />
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
          {loading ? (
            <div className="space-y-0 p-2">
              {[0, 1, 2, 3, 4].map((i) => (
                <div
                  key={i}
                  className="mb-1 animate-pulse rounded-xl bg-lumi-bg px-3 py-4"
                >
                  <div className="h-4 w-2/5 rounded bg-gray-200" />
                  <div className="mt-2 h-3 w-3/5 rounded bg-gray-100" />
                </div>
              ))}
            </div>
          ) : leads.length === 0 ? (
            <div className="flex flex-col items-center px-6 py-16 text-center">
              <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-lumi-bg text-lumi-muted">
                <svg
                  width="22"
                  height="22"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  aria-hidden
                >
                  <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
                  <circle cx="9" cy="7" r="4" />
                  <path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" />
                </svg>
              </div>
              <p className="text-sm font-medium text-gray-900">No {brand} leads found</p>
              <p className="mt-1 text-xs text-lumi-muted">
                {search ? "Try another search" : "Linked Zoho leads for this brand show up here"}
              </p>
            </div>
          ) : (
            <ul className="pb-4">
              {leads.map((lead) => {
                const active = lead.row_key === selectedKey;
                return (
                  <li key={lead.row_key}>
                    <button
                      type="button"
                      onClick={() => selectLead(lead.row_key)}
                      className={`flex w-full items-center gap-3 px-4 py-3.5 text-left transition active:bg-blue-50 ${
                        active ? "bg-blue-50" : "hover:bg-lumi-bg"
                      }`}
                    >
                      <div
                        className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-sm font-bold ${
                          lead.has_zoho
                            ? "bg-lumi-blue text-white"
                            : "bg-gray-100 text-gray-500"
                        }`}
                      >
                        {initials(lead.name)}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="truncate text-[15px] font-semibold text-gray-900">
                            {lead.name || "Unknown"}
                          </span>
                          {lead.has_zoho ? (
                            <span className="shrink-0 rounded-md bg-emerald-50 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-700">
                              Zoho
                            </span>
                          ) : null}
                        </div>
                        <p className="truncate text-xs text-lumi-muted">
                          {lead.dial_to || lead.phone_no || "No phone"}
                        </p>
                        {lead.email ? (
                          <p className="truncate text-xs text-lumi-muted">
                            {lead.email}
                          </p>
                        ) : null}
                      </div>
                      <svg
                        className="shrink-0 text-gray-300"
                        width="18"
                        height="18"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2.5"
                        aria-hidden
                      >
                        <path d="M9 18l6-6-6-6" />
                      </svg>
                    </button>
                    <div className="mx-4 border-b border-lumi-border/80" />
                  </li>
                );
              })}
            </ul>
          )}
        </div>
        {error && !showForm ? (
          <p className="border-t border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 safe-pb">
            {error}
          </p>
        ) : null}
      </section>

      {/* Form pane */}
      <section
        className={`min-w-0 flex-1 bg-lumi-bg ${
          showForm ? "flex flex-col" : isMobile ? "hidden" : "flex"
        }`}
      >
        {!selected ? (
          <div className="flex flex-1 flex-col items-center justify-center px-8 text-center">
            <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-white text-lumi-blue shadow-sm">
              <svg
                width="26"
                height="26"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                aria-hidden
              >
                <path d="M12 20h9" />
                <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" />
              </svg>
            </div>
            <p className="text-base font-semibold text-gray-900">
              Select a lead
            </p>
            <p className="mt-1 max-w-xs text-sm text-lumi-muted">
              Choose someone from the list to add a Zoho note and update sale
              revenue, inspection profits, and date.
            </p>
          </div>
        ) : (
          <form onSubmit={onSubmit} className="flex min-h-0 flex-1 flex-col">
            {/* Sticky lead header */}
            <div className="shrink-0 border-b border-lumi-border bg-white px-3 py-3 sm:px-6">
              <div className="flex items-center gap-2">
                {isMobile ? (
                  <button
                    type="button"
                    onClick={clearSelection}
                    aria-label="Back to leads"
                    className="flex min-h-[44px] min-w-[44px] shrink-0 items-center justify-center rounded-xl text-lumi-blue hover:bg-lumi-bg"
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
                <div
                  className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-sm font-bold ${
                    selected.has_zoho
                      ? "bg-lumi-blue text-white"
                      : "bg-gray-100 text-gray-500"
                  }`}
                >
                  {initials(selected.name)}
                </div>
                <div className="min-w-0 flex-1">
                  <h2 className="truncate text-base font-bold text-gray-900 sm:text-lg">
                    {selected.name || "Unknown"}
                  </h2>
                  <p className="truncate text-xs text-lumi-muted">
                    {selected.dial_to || selected.phone_no || "—"}
                    {selected.email ? ` · ${selected.email}` : ""}
                  </p>
                </div>
                {selected.has_zoho ? (
                  <span className="shrink-0 rounded-full bg-emerald-50 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide text-emerald-700">
                    Linked
                  </span>
                ) : (
                  <span className="shrink-0 rounded-full bg-amber-50 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide text-amber-800">
                    Unlinked
                  </span>
                )}
              </div>
            </div>

            {/* Scrollable fields */}
            <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-4 sm:px-6">
              {!selected.has_zoho ? (
                <div className="mb-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950">
                  This lead is not linked to a saved Zoho ID yet. Saving looks
                  the lead up in Zoho by email or phone.
                </div>
              ) : null}

              <section className="mb-4 overflow-hidden rounded-2xl border border-lumi-border bg-white">
                <div className="border-b border-lumi-border px-4 py-3">
                  <h3 className="text-sm font-semibold text-gray-900">Note</h3>
                  <p className="text-xs text-lumi-muted">
                    Appears in the lead&apos;s Notes timeline
                  </p>
                </div>
                <div className="space-y-4 p-4">
                  <label className="block">
                    <FieldLabel>Title</FieldLabel>
                    <input
                      type="text"
                      value={noteTitle}
                      onChange={(e) => setNoteTitle(e.target.value)}
                      placeholder="Sale closed, Deposit received…"
                      maxLength={100}
                      className={inputClass}
                    />
                  </label>
                  <label className="block">
                    <FieldLabel>Details</FieldLabel>
                    <textarea
                      rows={isMobile ? 3 : 4}
                      value={note}
                      onChange={(e) => setNote(e.target.value)}
                      placeholder="What happened with this sale…"
                      className={`${inputClass} min-h-[96px] resize-none py-3`}
                    />
                  </label>
                </div>
              </section>

              <section className="mb-4 overflow-hidden rounded-2xl border border-lumi-border bg-white">
                <div className="border-b border-lumi-border px-4 py-3">
                  <h3 className="text-sm font-semibold text-gray-900">
                    Sale numbers
                  </h3>
                  <p className="text-xs text-lumi-muted">
                    Updates Sale Revenue, Pre/Post Inspection Profit, and Date
                    in Zoho
                  </p>
                </div>
                <div className="space-y-4 p-4">
                  <label className="block">
                    <FieldLabel>Revenue</FieldLabel>
                    <div className="relative">
                      <span className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-sm font-medium text-lumi-muted">
                        $
                      </span>
                      <input
                        type="text"
                        inputMode="decimal"
                        value={revenue}
                        onChange={(e) => setRevenue(e.target.value)}
                        placeholder="0.00"
                        className={`${inputClass} pl-7`}
                      />
                    </div>
                  </label>
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                    <label className="block">
                      <FieldLabel>Pre Sight Inspection Profit</FieldLabel>
                      <div className="relative">
                        <span className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-sm font-medium text-lumi-muted">
                          $
                        </span>
                        <input
                          type="text"
                          inputMode="decimal"
                          value={preSightProfit}
                          onChange={(e) => setPreSightProfit(e.target.value)}
                          placeholder="0.00"
                          className={`${inputClass} pl-7`}
                        />
                      </div>
                    </label>
                    <label className="block">
                      <FieldLabel>Post Inspection Profit</FieldLabel>
                      <div className="relative">
                        <span className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-sm font-medium text-lumi-muted">
                          $
                        </span>
                        <input
                          type="text"
                          inputMode="decimal"
                          value={postInspectionProfit}
                          onChange={(e) =>
                            setPostInspectionProfit(e.target.value)
                          }
                          placeholder="0.00"
                          className={`${inputClass} pl-7`}
                        />
                      </div>
                    </label>
                  </div>
                  <label className="block">
                    <FieldLabel>Sale date</FieldLabel>
                    <input
                      type="date"
                      value={saleDate}
                      onChange={(e) => setSaleDate(e.target.value)}
                      className={`${inputClass} max-w-full sm:max-w-xs`}
                    />
                  </label>
                </div>
              </section>

              {error ? (
                <div className="mb-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                  {error}
                </div>
              ) : null}
              {success ? (
                <div className="mb-3 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-medium text-emerald-800">
                  {success}
                </div>
              ) : null}

              {/* Spacer so sticky CTA doesn't cover content */}
              <div className="h-4 sm:h-2" />
            </div>

            {/* Sticky submit */}
            <div className="shrink-0 border-t border-lumi-border bg-white px-4 py-3 safe-pb sm:px-6">
              <button
                type="submit"
                disabled={submitting}
                className="flex min-h-[52px] w-full items-center justify-center rounded-xl bg-lumi-blue text-[15px] font-semibold text-white shadow-sm transition hover:bg-blue-700 active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-45"
              >
                {submitting ? "Saving to Zoho…" : "Submit to Zoho CRM"}
              </button>
            </div>
          </form>
        )}
      </section>
    </div>
  );
}
