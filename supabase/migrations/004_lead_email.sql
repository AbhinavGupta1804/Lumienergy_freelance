-- Migration 004: lead email for email notifications
ALTER TABLE processed_leads
  ADD COLUMN IF NOT EXISTS email TEXT;
