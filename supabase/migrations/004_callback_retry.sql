-- Callback retry scheduling for unanswered outbound calls

ALTER TABLE processed_leads
  ADD COLUMN IF NOT EXISTS first_call_at        TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS callback_attempt     INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS next_retry_at        TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS callback_status      TEXT NOT NULL DEFAULT 'none',
  ADD COLUMN IF NOT EXISTS call_in_progress     BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS last_twilio_status   TEXT;

CREATE INDEX IF NOT EXISTS idx_processed_leads_callback_due
  ON processed_leads (next_retry_at)
  WHERE callback_status = 'active' AND call_in_progress = FALSE;
