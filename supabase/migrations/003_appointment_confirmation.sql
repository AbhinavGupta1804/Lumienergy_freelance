-- Appointment time + post-upload confirmation SMS tracking

ALTER TABLE processed_leads
  ADD COLUMN IF NOT EXISTS appointment_start  TEXT,
  ADD COLUMN IF NOT EXISTS appointment_label  TEXT,
  ADD COLUMN IF NOT EXISTS confirmation_sms_sent BOOLEAN NOT NULL DEFAULT FALSE;
