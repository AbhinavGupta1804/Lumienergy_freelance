-- Lumi Outbound AI Caller — run once in Supabase SQL Editor
-- Project → SQL → New query → paste → Run
-- Tables only (no seed data)

CREATE TABLE IF NOT EXISTS processed_leads (
    row_key TEXT PRIMARY KEY,
    row_number INTEGER NOT NULL,
    name TEXT,
    address TEXT,
    email TEXT,
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
    confirmation_sms_sent BOOLEAN NOT NULL DEFAULT FALSE,
    first_call_at TIMESTAMPTZ,
    callback_attempt INTEGER NOT NULL DEFAULT 0,
    next_retry_at TIMESTAMPTZ,
    callback_status TEXT NOT NULL DEFAULT 'none',
    call_in_progress BOOLEAN NOT NULL DEFAULT FALSE,
    last_twilio_status TEXT
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

-- Customer SMS / email message log (inbound + outbound)
CREATE TABLE IF NOT EXISTS customer_messages (
    id              BIGSERIAL PRIMARY KEY,
    direction       TEXT NOT NULL CHECK (direction IN ('inbound', 'outbound')),
    channel         TEXT NOT NULL CHECK (channel IN ('sms', 'email')),
    message_type    TEXT NOT NULL DEFAULT 'general',
    body            TEXT NOT NULL,
    from_address    TEXT,
    to_address      TEXT,
    lead_row_key    TEXT,
    lead_name       TEXT,
    call_sid        TEXT,
    conversation_id TEXT,
    provider_id     TEXT,
    status          TEXT NOT NULL DEFAULT 'sent',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_customer_messages_created_at
    ON customer_messages (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_customer_messages_lead_row_key
    ON customer_messages (lead_row_key);

COMMENT ON TABLE customer_messages IS
    'Log of SMS/email sent to customers and replies received from them';
