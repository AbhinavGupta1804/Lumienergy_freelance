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
    sheets_col_sms_consent: str = "Transactional SMS Consent"
    sheets_col_offer_page: str = "Offer Page"
    sheets_col_monthly_bill: str = "Monthly Bill"

    # --- Google Maps (roof satellite snapshot for reports) ---
    google_api_key: str = ""  # Maps Static API (and optional Geocoding)

    # --- Testing overrides ---
    # When true, ignore phone_no column and always dial TEST_CALL_NUMBER
    test_mode: bool = True
    test_call_number: str = "+919752713547"

    # --- Outbound voice agent (ElevenLabs) ---
    # When false, leads are still accepted and stored but no AI calls are placed.
    voice_agent_enabled: bool = True

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

    # --- Instant welcome SMS (Stage 0 — on form submit) ---
    welcome_sms_enabled: bool = True
    welcome_sms_body: str = (
        "Thanks for requesting info on solar with Lumi Energy! 🌞 "
        "Someone from our team will be reaching out shortly to answer your questions. "
        "Talk soon!"
    )

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

    # --- Email — used when NOTIFICATION_CHANNEL=email ---
    # Master kill switch for ALL outbound email (Resend, SMTP, reports, follow-ups).
    email_enabled: bool = True
    # Prefer Resend when RESEND_API_KEY is set; otherwise SMTP.
    # When false, no emails are sent via Resend (report, follow-ups, bill/confirm).
    resend_enabled: bool = True
    resend_api_key: str = ""
    resend_from_email: str = "support@lumienergy.us"
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
    # Off by default: Cloud Run URL/proxy mismatches often 403 real Twilio
    # inbound SMS (Error 11200) and replies never reach the CRM.
    twilio_validate_webhook_signatures: bool = False

    # --- Cal.com scheduling (proxy used by ElevenLabs get_available_slots tool) ---
    cal_api_key: str = ""  # Cal.com API key (Bearer token)
    cal_event_type_id: str = ""  # Event type to check / book
    cal_booking_page_url: str = ""  # Public Cal.com booking page for self-scheduling
    calcom_webhook_secret: str = ""  # Verify Cal.com webhook signatures (optional)
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

    # --- Callback retries (scheduled via Cloud Tasks) ---
    callback_enabled: bool = True
    callback_max_days: int = 7
    callback_morning_hour: int = 9
    callback_evening_hour: int = 19
    callback_evening_cutoff_hour: int = 20
    callback_stale_in_progress_minutes: int = 45
    # Reconcile via Twilio when EL post-call webhook never arrives (manual/admin use)
    callback_reconcile_after_minutes: int = 3

    # --- Report follow-up emails (unbooked leads) ---
    followup_email_enabled: bool = False
    followup_email_max_attempts: int = 4
    followup_email_interval_days: int = 2
    followup_email_send_hour: int = 8  # 08:30 business timezone
    followup_email_send_minute: int = 30

    # --- Zoho CRM webhooks (custom buttons → FastAPI) ---
    zoho_webhook_secret: str = ""
    # Outbound Zoho CRM (Attachments API) — same OAuth app as Apps Script new.gs
    zoho_client_id: str = ""
    zoho_client_secret: str = ""
    zoho_refresh_token: str = ""
    zoho_accounts_url: str = "https://accounts.zoho.com"
    zoho_api_domain: str = "https://www.zohoapis.com"

    # --- SMS nurture sequence (Stage 1 booked + Stage 2 no-answer) ---
    nurture_sms_enabled: bool = True
    nurture_sms_quiet_start_hour: int = 9  # America/Phoenix
    nurture_sms_quiet_end_hour: int = 20
    # Deprecated: Stage 2 touch 1 sends immediately on Zoho activate webhook.
    # Kept for env compat; not used for scheduling.
    nurture_sms_first_touch_delay_hours: float = 0.0
    nurture_rep_name: str = "Alex"
    nurture_company_phone: str = "+1 (480) 252-6872"
    nurture_google_reviews_url: str = ""
    nurture_founder_video_url: str = ""
    nurture_website_url: str = "https://lumienergy.us"
    nurture_bill_upload_base_url: str = ""  # falls back to sms_bill_upload_base_url

    # --- Cloud Tasks job backend ---
    # auto = use Cloud Tasks when project/queue/secret/public URL are set
    job_scheduler_backend: str = "auto"  # auto | cloud_tasks | off
    gcp_project_id: str = ""
    gcp_location: str = "us-west4"
    cloud_tasks_queue: str = "lumi-jobs"
    # Shared secret Cloud Tasks sends as X-Internal-Jobs-Secret
    internal_jobs_secret: str = ""
    # Optional: OIDC service account email for Cloud Tasks → Cloud Run auth
    cloud_tasks_invoker_sa: str = ""
    # Optional JSON key for Cloud Tasks only. Prefer ADC on Cloud Run (no key).
    cloud_tasks_service_account_json: str = ""

    # --- Retry (ElevenLabs API) ---
    max_call_retries: int = 3
    retry_base_delay_seconds: float = 2.0


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
