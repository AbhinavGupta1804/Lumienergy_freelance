-- SMS nurture sequence (Zoho-triggered Stage 1 / Stage 2)
ALTER TABLE processed_leads
  ADD COLUMN IF NOT EXISTS nurture_sms_status TEXT NOT NULL DEFAULT 'none';

ALTER TABLE processed_leads
  ADD COLUMN IF NOT EXISTS nurture_sms_attempt INTEGER NOT NULL DEFAULT 0;

ALTER TABLE processed_leads
  ADD COLUMN IF NOT EXISTS next_nurture_sms_at TIMESTAMPTZ;

ALTER TABLE processed_leads
  ADD COLUMN IF NOT EXISTS sms_opt_out BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_processed_leads_nurture_sms_due
  ON processed_leads (next_nurture_sms_at)
  WHERE nurture_sms_status = 'active';
