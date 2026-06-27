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

CREATE INDEX IF NOT EXISTS idx_customer_messages_from_address
    ON customer_messages (from_address);

CREATE INDEX IF NOT EXISTS idx_customer_messages_to_address
    ON customer_messages (to_address);

COMMENT ON TABLE customer_messages IS
    'Log of SMS/email sent to customers and replies received from them';
