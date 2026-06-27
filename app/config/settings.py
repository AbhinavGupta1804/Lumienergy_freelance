"""
Application configuration loaded from environment variables.

All secrets (Twilio, ElevenLabs, Google) belong in a `.env` file at the project root.
Never commit `.env` to version control.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central settings for the outbound calling workflow."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App ---
    app_name: str = "Lumi Outbound AI Caller"
    debug: bool = False
    log_level: str = "INFO"
    # Comma-separated origins for Next.js admin (dev + Vercel)
    cors_origins: str = "http://localhost:3000"

    # --- Server (used in README for ngrok URL examples) ---
    host: str = "0.0.0.0"
    port: int = 8000
    public_base_url: str = ""  # e.g. https://abc123.ngrok-free.app — set after starting ngrok

    # --- Google Sheets ---
    google_sheets_spreadsheet_id: str = ""
    google_sheets_worksheet_name: str = "Sheet1"
    google_service_account_json: str = ""  # Path to service account JSON file
    # Shared secret for Google Apps Script → POST /webhooks/sheets/new-lead
    sheets_webhook_secret: str = ""
    # Column headers in row 1 (Landing page forms layout)
    sheets_col_first_name: str = "First Name"
    sheets_col_last_name: str = "Last Name"
    sheets_col_address: str = "Address"
    sheets_col_phone: str = "Phone"
    sheets_col_email: str = "Email"

    # --- Testing overrides ---
    # When true, ignore phone_no column and always dial TEST_CALL_NUMBER
    test_mode: bool = True
    test_call_number: str = "+919752713547"

    # --- ElevenLabs Conversational AI (handles Twilio outbound via their API) ---
    elevenlabs_api_key: str = ""
    elevenlabs_agent_id: str = ""
    # From ElevenLabs dashboard: Agent → Phone Numbers → linked Twilio number ID
    elevenlabs_agent_phone_number_id: str = ""
    # Secret from ElevenLabs → Settings → Webhooks (HMAC). Optional locally.
    elevenlabs_webhook_secret: str = ""

    # --- Twilio (credentials used by ElevenLabs; webhooks optional for status) ---
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""  # Your purchased E.164 number (voice + SMS From)
    # A2P 10DLC: send SMS via Messaging Service (required for US delivery after 10DLC)
    twilio_messaging_service_sid: str = ""  # e.g. MGxxxxxxxx — preferred over From number

    # --- Post-call notifications (bill upload link) ---
    # Channel: sms (Twilio) or email (SMTP). Same channel used for confirmation after upload.
    notification_channel: str = "sms"  # sms | email
    sms_enabled: bool = True
    # Base URL of the Vercel bill-upload app (no trailing slash).
    # Individual links are built as: {sms_bill_upload_base_url}/?token=<uuid>
    sms_bill_upload_base_url: str = "https://lumi-bill-upload.vercel.app"
    # Deprecated: kept for backward-compat if SMS_MESSAGE_BODY uses {link}.
    sms_bill_upload_link: str = ""
    # Optional full SMS text; placeholders: {link}, {first_name}, {support_phone}
    sms_message_body: str = ""
    sms_support_phone: str = "+1 (480) 252-6872"

    # --- Email (SMTP) — used when NOTIFICATION_CHANNEL=email ---
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_from_name: str = "Lumi Energy"
    smtp_use_tls: bool = True
    # Optional templates — {link}, {first_name}, {appointment}
    email_bill_upload_subject: str = ""
    email_bill_upload_body: str = ""
    email_confirmation_subject: str = ""
    email_confirmation_body: str = ""

    # --- Post-upload consultation confirmation ---
    confirmation_sms_enabled: bool = True
    # Use {appointment}, {appointment_date}, {appointment_time}
    confirmation_sms_body: str = ""
    # Shared secret — bill_upload Vercel app sends X-Bill-Upload-Webhook-Secret header
    bill_upload_webhook_secret: str = ""
    # Validate X-Twilio-Signature on status callbacks (recommended in production)
    twilio_validate_webhook_signatures: bool = True

    # --- Cal.com scheduling (proxy used by ElevenLabs get_available_slots tool) ---
    cal_api_key: str = ""  # Cal.com API key (Bearer token)
    cal_event_type_id: str = ""  # Event type to check / book
    business_timezone: str = "America/Phoenix"  # Arizona — no DST
    # How far ahead to allow date parsing (e.g. "next Tuesday" capped to 60 days)
    scheduling_max_days_ahead: int = 60
    # Tool API key — set in BOTH .env and the ElevenLabs tool header to gate access
    scheduling_tool_api_key: str = ""

    # --- Database: sqlite (local) or supabase (cloud Postgres) ---
    database_backend: str = "sqlite"  # sqlite | supabase
    dedup_db_path: str = "data/processed_leads.db"
    supabase_url: str = ""  # https://xxxx.supabase.co
    # Service role key — server only; never expose to browser or commit to git
    supabase_service_role_key: str = ""
    bill_upload_bucket: str = "bill_upload"

    # --- Discord post-call notifications (Incoming Webhook URL) ---
    discord_notifications_enabled: bool = True
    # Channel webhook: Server Settings → Integrations → Webhooks → New Webhook → Copy URL
    discord_webhook_url: str = ""

    # --- Callback retry scheduler ---
    callback_enabled: bool = True
    callback_max_days: int = 7
    callback_scheduler_interval_seconds: int = 60
    callback_morning_hour: int = 9
    callback_evening_hour: int = 19
    callback_evening_cutoff_hour: int = 20
    callback_stale_in_progress_minutes: int = 45
    # Reconcile via Twilio when EL post-call webhook never arrives
    callback_reconcile_after_minutes: int = 3

    # --- Retry (ElevenLabs API) ---
    max_call_retries: int = 3
    retry_base_delay_seconds: float = 2.0


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
