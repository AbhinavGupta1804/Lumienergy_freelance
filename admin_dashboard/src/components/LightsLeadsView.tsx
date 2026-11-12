"use client";

import { useCallback, useEffect, useState } from "react";
import {
  CallRow,
  DEFAULT_IMAGE_MODEL,
  IMAGE_MODELS,
  fetchCall,
  fetchCalls,
  fetchImageModels,
  fetchLeadStreetview,
  isLightsLead,
  lightingPreviewUrl,
  renderLightingPreview,
  streetviewImageUrl,
} from "@/lib/api";
import { useIsMobile } from "@/lib/useIsMobile";

function fmtDate(iso?: string | null) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function LightsLeadsView() {
  const [leads, setLeads] = useState<CallRow[]>([]);
  const [search, setSearch] = useState("");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [detail, setDetail] = useState<CallRow | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [fetching, setFetching] = useState(false);
  const [rendering, setRendering] = useState(false);
  const [extraPrompt, setExtraPrompt] = useState("");
  const [imageModels, setImageModels] = useState(IMAGE_MODELS);
  const [imageModel, setImageModel] = useState(DEFAULT_IMAGE_MODEL);
  const [imageVersion, setImageVersion] = useState(0);
  const isMobile = useIsMobile(1024);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchCalls(search, "all", "lights");
      setLeads(data.calls.filter(isLightsLead));
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load leads");
    } finally {
      setLoading(false);
    }
  }, [search]);

  useEffect(() => {
    const t = setTimeout(load, search ? 300 : 0);
    return () => clearTimeout(t);
  }, [load, search]);

  useEffect(() => {
    const saved = window.localStorage.getItem("lumi-lights-image-model");
    if (saved && IMAGE_MODELS.some((item) => item.id === saved)) {
      setImageModel(saved);
    }
    fetchImageModels()
      .then((data) => {
        if (data.models?.length) setImageModels(data.models);
      })
      .catch(() => {
        /* The built-in list still fills the dropdown. */
      });
  }, []);

  useEffect(() => {
    if (!selectedKey) {
      setDetail(null);
      return;
    }
    fetchCall(selectedKey)
      .then(setDetail)
      .catch(() => {
        setDetail(leads.find((lead) => lead.row_key === selectedKey) || null);
      });
  }, [selectedKey, leads]);

  const showDetail = Boolean(selectedKey);

  const fetchOne = async (rowKey: string) => {
    setFetching(true);
    setError("");
    try {
      await fetchLeadStreetview(rowKey);
      const fresh = await fetchCall(rowKey);
      setDetail(fresh);
      setImageVersion((n) => n + 1);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not fetch the home image");
    } finally {
      setFetching(false);
    }
  };

  const generatePreview = async (rowKey: string) => {
    setRendering(true);
    setError("");
    try {
      await renderLightingPreview(rowKey, extraPrompt, imageModel);
      const fresh = await fetchCall(rowKey);
      setDetail(fresh);
      setImageVersion((n) => n + 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not generate the lighting preview");
    } finally {
      setRendering(false);
    }
  };

  const downloadPreview = async (lead: CallRow) => {
    try {
      const res = await fetch(previewUrl(lead, imageVersion));
      if (!res.ok) throw new Error("Could not download the preview");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      const who = (lead.name || "home").replace(/[^\w.-]+/g, "-");
      link.href = url;
      link.download = `${who}-lighting-preview.jpg`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not download the preview");
    }
  };

  const imageSrc = detail?.has_streetview
    ? homeImageUrl(detail, imageVersion)
    : "";
  const previewSrc = detail?.has_lighting_preview
    ? previewUrl(detail, imageVersion)
    : "";

  return (
    <div className="flex h-full">
      <section
        className={`flex flex-col border-r border-lumi-border bg-white ${
          isMobile ? (showDetail ? "hidden" : "flex w-full") : "flex w-[42%]"
        }`}
      >
        <div className="space-y-3 border-b border-lumi-border p-3">
          <div className="flex gap-2">
            <input
              type="search"
              placeholder="Search name, phone, address…"
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
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          {loading ? (
            <p className="p-4 text-center text-sm text-lumi-muted">Loading…</p>
          ) : leads.length === 0 ? (
            <p className="p-4 text-center text-sm text-lumi-muted">No Lights leads</p>
          ) : (
            leads.map((lead) => (
              <button
                key={lead.row_key}
                type="button"
                onClick={() => setSelectedKey(lead.row_key)}
                className={`flex w-full items-center gap-3 border-b border-lumi-border px-4 py-3 text-left hover:bg-lumi-bg ${
                  selectedKey === lead.row_key ? "bg-blue-50" : ""
                }`}
              >
                <HomeThumb lead={lead} version={imageVersion} />
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold">{lead.name || "—"}</div>
                  <div className="truncate text-xs text-lumi-muted">
                    {lead.phone_no || lead.dial_to || "No phone"}
                  </div>
                  <div className="truncate text-xs text-gray-600">
                    {lead.address || "No address"}
                  </div>
                </div>
              </button>
            ))
          )}
        </div>
        {error && !showDetail ? (
          <p className="border-t border-amber-200 bg-amber-50 p-2 text-sm text-amber-950">{error}</p>
        ) : null}
      </section>

      <section
        className={`min-w-0 flex-1 overflow-auto bg-white ${
          showDetail ? "block" : isMobile ? "hidden" : "block"
        }`}
      >
        {!detail ? (
          <p className={`p-6 text-lumi-muted ${isMobile ? "hidden" : "block"}`}>
            Select a lead
          </p>
        ) : (
          <div className="p-4 sm:p-6">
            <div className="mb-4 flex items-start gap-2">
              {isMobile ? (
                <button
                  type="button"
                  onClick={() => {
                    setSelectedKey(null);
                    setDetail(null);
                  }}
                  aria-label="Back to leads"
                  className="mr-1 flex min-h-[44px] min-w-[44px] shrink-0 items-center justify-center rounded-lg text-lumi-blue hover:bg-lumi-bg"
                >
                  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                    <path d="M15 18l-6-6 6-6" />
                  </svg>
                </button>
              ) : null}
              <div className="min-w-0">
                <h2 className="truncate text-lg font-bold sm:text-xl">{detail.name || "Unknown"}</h2>
                <p className="truncate text-sm text-lumi-muted">{detail.email || "No email"}</p>
              </div>
            </div>

            <div className="mb-5 overflow-hidden rounded-xl border border-lumi-border bg-lumi-bg">
              {imageSrc ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={imageSrc}
                  alt={`Street View of ${detail.address || detail.name || "the home"}`}
                  className="max-h-[360px] w-full object-cover"
                />
              ) : (
                <div className="flex h-48 items-center justify-center px-6 text-center text-sm text-lumi-muted">
                  No home image yet
                </div>
              )}
            </div>

            <button
              type="button"
              disabled={fetching || !(detail.address || "").trim()}
              onClick={() => fetchOne(detail.row_key)}
              className="mb-5 min-h-[44px] rounded-lg bg-lumi-blue px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {fetching
                ? "Fetching Street View…"
                : detail.has_streetview
                  ? "Refresh home image"
                  : "Fetch home image"}
            </button>
            {!(detail.address || "").trim() ? (
              <p className="-mt-3 mb-5 text-xs text-lumi-muted">This lead has no address.</p>
            ) : null}

            <div className="mb-5">
              <label className="mb-2 block text-sm font-semibold" htmlFor="image-model">
                Model
              </label>
              <select
                id="image-model"
                value={imageModel}
                onChange={(e) => {
                  setImageModel(e.target.value);
                  window.localStorage.setItem("lumi-lights-image-model", e.target.value);
                }}
                className="mb-4 w-full rounded-lg border border-lumi-border bg-white px-3 py-2 text-sm"
              >
                {imageModels.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.label}
                  </option>
                ))}
              </select>
              <label className="mb-2 block text-sm font-semibold" htmlFor="extra-prompt">
                Extra instruction
              </label>
              <textarea
                id="extra-prompt"
                value={extraPrompt}
                onChange={(e) => setExtraPrompt(e.target.value)}
                maxLength={1000}
                rows={3}
                placeholder="Added after the evening lighting prompt. Example: use cool white LEDs on the garage only."
                className="mb-3 w-full rounded-lg border border-lumi-border px-3 py-2 text-sm"
              />
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <h3 className="text-sm font-semibold">Lighting preview</h3>
                <button
                  type="button"
                  disabled={rendering || !detail.has_streetview}
                  onClick={() => generatePreview(detail.row_key)}
                  className="min-h-[40px] rounded-lg border border-lumi-border px-3 py-2 text-sm font-medium hover:bg-lumi-bg disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {rendering ? "Generating…" : detail.has_lighting_preview ? "Regenerate preview" : "Generate preview"}
                </button>
                {previewSrc ? (
                  <button
                    type="button"
                    onClick={() => downloadPreview(detail)}
                    className="min-h-[40px] rounded-lg bg-lumi-blue px-3 py-2 text-sm font-medium text-white hover:bg-blue-700"
                  >
                    Download
                  </button>
                ) : null}
              </div>
              {previewSrc ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={previewSrc}
                  alt={`Lighting preview of ${detail.address || detail.name || "the home"}`}
                  className="max-h-[420px] w-full rounded-xl border border-lumi-border object-cover"
                />
              ) : (
                <p className="text-sm text-lumi-muted">
                  {detail.has_streetview
                    ? "Generate a night lighting preview from this Street View photo."
                    : "Fetch the Street View photo first."}
                </p>
              )}
            </div>

            <dl className="grid grid-cols-1 gap-x-4 gap-y-3 text-sm sm:grid-cols-2">
              <Field label="Phone" value={detail.phone_no || detail.dial_to} />
              <Field label="Email" value={detail.email} />
              <Field label="Offer page" value={detail.offer_page} />
              <Field label="Received" value={fmtDate(detail.processed_at)} />
              <Field label="Address" value={detail.address} full />
            </dl>
            {error ? (
              <p className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-2 text-sm text-amber-950">
                {error}
              </p>
            ) : null}
          </div>
        )}
      </section>
    </div>
  );
}

function previewUrl(lead: CallRow, version: number) {
  const base = lightingPreviewUrl(lead.row_key, lead.streetview_render_fetched_at);
  return `${base}${base.includes("?") ? "&" : "?"}k=${version}`;
}

function homeImageUrl(lead: CallRow, version: number) {
  const base = streetviewImageUrl(lead.row_key, lead.streetview_fetched_at);
  return `${base}${base.includes("?") ? "&" : "?"}k=${version}`;
}

function HomeThumb({ lead, version }: { lead: CallRow; version: number }) {
  if (!lead.has_streetview) {
    return (
      <span className="flex h-12 w-16 shrink-0 items-center justify-center rounded-md bg-lumi-bg text-[10px] text-lumi-muted">
        No photo
      </span>
    );
  }
  const src = homeImageUrl(lead, version);
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={src}
      alt=""
      className="h-12 w-16 shrink-0 rounded-md object-cover"
    />
  );
}

function Field({
  label,
  value,
  full,
}: {
  label: string;
  value?: string | null;
  full?: boolean;
}) {
  return (
    <div className={full ? "sm:col-span-2" : undefined}>
      <dt className="text-xs text-lumi-muted">{label}</dt>
      <dd className="break-words">{value || "—"}</dd>
    </div>
  );
}
