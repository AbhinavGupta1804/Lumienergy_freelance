-- Migration 002: bill upload support
-- Run this in Supabase → SQL Editor → New query → Run

-- ── 1. Add upload token columns to processed_leads ──────────────────────────
ALTER TABLE processed_leads
  ADD COLUMN IF NOT EXISTS upload_token      TEXT,
  ADD COLUMN IF NOT EXISTS upload_token_used BOOLEAN NOT NULL DEFAULT FALSE;

-- Unique index so token lookups are fast and no duplicates are possible
CREATE UNIQUE INDEX IF NOT EXISTS idx_processed_leads_upload_token
  ON processed_leads (upload_token)
  WHERE upload_token IS NOT NULL;

-- ── 2. Create bill_uploads metadata table ───────────────────────────────────
CREATE TABLE IF NOT EXISTS bill_uploads (
    id              BIGSERIAL PRIMARY KEY,
    lead_row_key    TEXT NOT NULL REFERENCES processed_leads (row_key),
    upload_token    TEXT NOT NULL,
    storage_path    TEXT NOT NULL,         -- path inside "bill_upload" bucket
    original_name   TEXT,
    content_type    TEXT,
    size_bytes      BIGINT,
    status          TEXT NOT NULL DEFAULT 'received', -- received | reviewed | processed
    uploaded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bill_uploads_lead_row_key
  ON bill_uploads (lead_row_key);

CREATE INDEX IF NOT EXISTS idx_bill_uploads_uploaded_at
  ON bill_uploads (uploaded_at DESC);

COMMENT ON TABLE bill_uploads IS
  'One row per uploaded energy bill, linked to the lead that submitted it.';

-- ── 3. Create the private storage bucket ────────────────────────────────────
-- Run this once via Supabase dashboard: Storage → New bucket
-- Name: bill_upload
-- Public: OFF  (files are NOT publicly accessible by URL)
--
-- Or run via SQL (requires pg_net / service role):
-- INSERT INTO storage.buckets (id, name, public)
-- VALUES ('bill_upload', 'bill_upload', false)
-- ON CONFLICT (id) DO NOTHING;
