-- Lumi Outbound AI Caller — run once in Supabase SQL Editor
-- Project → SQL → New query → paste → Run
-- Tables only (no seed data)

CREATE TABLE IF NOT EXISTS processed_leads (
    row_key TEXT PRIMARY KEY,
    row_number INTEGER NOT NULL,
    name TEXT,
    address TEXT,
    call_sid TEXT,
    conversation_id TEXT,
    status TEXT NOT NULL DEFAULT 'called',
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    phone_no TEXT,
    dial_to TEXT,
    sms_eligible BOOLEAN NOT NULL DEFAULT FALSE,
    sms_sent BOOLEAN NOT NULL DEFAULT FALSE,
    call_duration_secs INTEGER,
    call_successful TEXT,
    transcript_summary TEXT,
    termination_reason TEXT,
    call_ended_at TIMESTAMPTZ,
    cal_booking_uid TEXT,
    google_event_uid TEXT,
    appointment_start TEXT,
    appointment_label TEXT,
    confirmation_sms_sent BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_processed_leads_conversation_id
    ON processed_leads (conversation_id);

CREATE INDEX IF NOT EXISTS idx_processed_leads_call_sid
    ON processed_leads (call_sid);

CREATE INDEX IF NOT EXISTS idx_processed_leads_processed_at
    ON processed_leads (processed_at DESC);

CREATE INDEX IF NOT EXISTS idx_processed_leads_phone_dial
    ON processed_leads (dial_to, phone_no);

COMMENT ON TABLE processed_leads IS
    'One row per outbound call attempt (sheet dedup + SMS + post-call analytics)';
