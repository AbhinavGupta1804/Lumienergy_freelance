"""
Admin dashboard data — Supabase calls + bill uploads.

Requires DATABASE_BACKEND=supabase and Supabase credentials in .env.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings
from app.services.post_call_report import REPORT_ELIGIBLE_OFFERS
from app.utils.phone import normalize_e164

logger = logging.getLogger(__name__)

_CALL_COLUMNS_BASE = (
    "row_key, row_number, name, address, email, phone_no, dial_to, "
    "call_sid, conversation_id, status, processed_at, "
    "sms_eligible, sms_sent, upload_token_used, confirmation_sms_sent, "
    "call_duration_secs, call_successful, transcript_summary, "
    "termination_reason, call_ended_at, "
    "appointment_start, appointment_label, "
    "cal_booking_uid, google_event_uid, "
    "first_call_at, callback_attempt, next_retry_at, callback_status, "
    "call_in_progress, last_twilio_status, "
    "offer_page, monthly_bill, report_sent, report_email_type, self_booked, "
    "followup_email_status, followup_email_attempt, next_followup_email_at, "
    "zoho_lead_id, business_unit"
)
_CALL_COLUMNS = (
    _CALL_COLUMNS_BASE
    + ", streetview_storage_path, streetview_fetched_at"
    + ", streetview_render_path, streetview_render_fetched_at"
)

_BILL_COLUMNS = (
    "id, lead_row_key, upload_token, storage_path, original_name, "
    "content_type, size_bytes, status, uploaded_at"
)

_MESSAGE_COLUMNS = (
    "id, direction, channel, message_type, body, from_address, to_address, "
    "lead_row_key, lead_name, call_sid, conversation_id, provider_id, status, created_at"
)

def lead_is_lights(row: dict[str, Any]) -> bool:
    """Lights when Business unit says so, otherwise when the row key is lights_."""
    unit = (row.get("business_unit") or "").strip().lower().replace("-", " ").replace("_", " ")
    if "light" in unit:
        return True
    if "energy" in unit or "solar" in unit:
        return False
    return str(row.get("row_key") or "").startswith("lights_")


PIPELINE_STAGES = (
    "new",
    "trying",
    "reached",
    "booked",
    "self_booked",
    "report_sent",
    "bill_uploaded",
    "confirmed",
    "exhausted",
    "failed",
)


class AdminServiceError(Exception):
    """Admin API configuration or query failure."""


class AdminService:
    def __init__(self) -> None:
        settings = get_settings()
        if (settings.database_backend or "sqlite").lower() != "supabase":
            raise AdminServiceError(
                "Admin dashboard requires DATABASE_BACKEND=supabase"
            )
        if not settings.supabase_url or not settings.supabase_service_role_key:
            raise AdminServiceError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required"
            )

        from supabase import create_client

        self._client = create_client(
            settings.supabase_url,
            settings.supabase_service_role_key,
        )
        self._bucket = settings.bill_upload_bucket
        self._streetview_columns = True

    def _lead_query(self, build):
        """Run a processed_leads select. Falls back if the Street View columns are not migrated yet."""
        columns = _CALL_COLUMNS if self._streetview_columns else _CALL_COLUMNS_BASE
        try:
            return build(self._client.table("processed_leads").select(columns)).execute()
        except Exception as exc:
            if self._streetview_columns and "streetview" in str(exc).lower():
                logger.warning(
                    "Street View columns missing on processed_leads. "
                    "Run supabase/migrations/009_streetview.sql"
                )
                self._streetview_columns = False
                return build(
                    self._client.table("processed_leads").select(_CALL_COLUMNS_BASE)
                ).execute()
            raise

    def list_calls(
        self,
        *,
        q: str = "",
        filter_by: str = "all",
        limit: int = 500,
        company: str = "",
    ) -> list[dict[str, Any]]:
        resp = self._lead_query(
            lambda query: query.order("processed_at", desc=True).limit(limit)
        )
        calls = resp.data or []

        bills_resp = (
            self._client.table("bill_uploads")
            .select(_BILL_COLUMNS)
            .order("uploaded_at", desc=True)
            .execute()
        )
        bills_by_lead: dict[str, list[dict]] = {}
        for bill in bills_resp.data or []:
            key = bill.get("lead_row_key") or ""
            bills_by_lead.setdefault(key, []).append(bill)

        rows: list[dict[str, Any]] = []
        query = q.strip().lower()

        for call in calls:
            row_key = call.get("row_key") or ""
            bills = bills_by_lead.get(row_key, [])
            enriched = self._enrich_lead(
                {**call, "bills": bills, "bill_count": len(bills)}
            )

            if query and not self._matches_query(enriched, query):
                continue
            if not self._matches_filter(enriched, filter_by):
                continue
            is_lights = lead_is_lights(enriched)
            if company == "lights" and not is_lights:
                continue
            if company == "energy" and is_lights:
                continue

            rows.append(enriched)

        return rows

    def stage_counts(self, *, limit: int = 2000) -> dict[str, int]:
        """Count leads by pipeline_stage (and a few useful extras)."""
        rows = self.list_calls(filter_by="all", limit=limit)
        counts: dict[str, int] = {s: 0 for s in PIPELINE_STAGES}
        counts["all"] = len(rows)
        counts["report_pending"] = 0
        counts["callback_active"] = 0
        counts["followup_emails"] = 0
        for row in rows:
            stage = row.get("pipeline_stage") or "new"
            if stage in counts:
                counts[stage] += 1
            offer = (row.get("offer_page") or "").lower()
            if offer in REPORT_ELIGIBLE_OFFERS and not row.get("report_sent"):
                counts["report_pending"] += 1
            if row.get("callback_status") == "active":
                counts["callback_active"] += 1
            if (row.get("followup_email_status") or "").lower() == "active":
                counts["followup_emails"] += 1
        return counts

    def list_messages(
        self,
        *,
        q: str = "",
        direction: str = "all",
        channel: str = "all",
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        query = (
            self._client.table("customer_messages")
            .select(_MESSAGE_COLUMNS)
            .order("created_at", desc=True)
            .limit(limit)
        )
        if direction != "all":
            query = query.eq("direction", direction)
        if channel != "all":
            query = query.eq("channel", channel)
        resp = query.execute()
        items = resp.data or []
        if q.strip():
            needle = q.strip().lower()
            items = [
                m
                for m in items
                if needle
                in " ".join(
                    str(m.get(k) or "")
                    for k in (
                        "body",
                        "from_address",
                        "to_address",
                        "lead_name",
                        "lead_row_key",
                        "message_type",
                    )
                ).lower()
            ]
        return items

    @staticmethod
    def customer_phone_for_message(message: dict[str, Any]) -> str:
        direction = (message.get("direction") or "").lower()
        if direction == "inbound":
            return normalize_e164(message.get("from_address") or "") or (
                message.get("from_address") or ""
            ).strip()
        return normalize_e164(message.get("to_address") or "") or (
            message.get("to_address") or ""
        ).strip()

    def _lights_phone_keys(self) -> set[str]:
        resp = (
            self._client.table("processed_leads")
            .select("phone_no,dial_to")
            .like("row_key", "lights_%")
            .limit(5000)
            .execute()
        )
        keys: set[str] = set()
        for row in resp.data or []:
            for raw in (row.get("phone_no"), row.get("dial_to")):
                text = (raw or "").strip()
                if not text:
                    continue
                norm = normalize_e164(text) or text
                keys.add(norm)
                digits = "".join(c for c in text if c.isdigit())
                if len(digits) >= 10:
                    keys.add(digits[-10:])
        return keys

    def list_conversations(
        self,
        *,
        q: str = "",
        limit: int = 200,
        last_read_by_phone: dict[str, str] | None = None,
        company: str = "",
    ) -> list[dict[str, Any]]:
        """SMS threads grouped by customer phone (sidebar).

        unread_count:
        - If last_read_by_phone[phone] is set: inbound messages after that timestamp
        - Else: consecutive inbound messages since the latest outbound (newest-first trail)
        """
        messages = self.list_messages(channel="sms", limit=5000)
        by_phone: dict[str, dict[str, Any]] = {}
        reads = last_read_by_phone or {}
        lights_phones = self._lights_phone_keys() if company in {"lights", "energy"} else set()

        # messages are newest-first from list_messages
        for msg in messages:
            phone = self.customer_phone_for_message(msg)
            if not phone:
                continue
            created = msg.get("created_at") or ""
            direction = (msg.get("direction") or "").lower()
            existing = by_phone.get(phone)

            if not existing:
                by_phone[phone] = {
                    "phone": phone,
                    "lead_name": (msg.get("lead_name") or "").strip(),
                    "last_message": (msg.get("body") or "")[:120],
                    "last_message_at": created,
                    "last_direction": direction,
                    "unread_count": 0,
                    "_trail_unread": True,
                    "has_lights": False,
                    "has_energy": False,
                }
                existing = by_phone[phone]
            else:
                if created > (existing.get("last_message_at") or ""):
                    existing["last_message"] = (msg.get("body") or "")[:120]
                    existing["last_message_at"] = created
                    existing["last_direction"] = direction
                name = (msg.get("lead_name") or "").strip()
                if name and not existing.get("lead_name"):
                    existing["lead_name"] = name

            row_key = (msg.get("lead_row_key") or "").strip()
            if row_key.startswith("lights_"):
                existing["has_lights"] = True
            elif row_key:
                existing["has_energy"] = True

            last_read = (reads.get(phone) or "").strip()
            if last_read:
                if direction == "inbound" and created > last_read:
                    existing["unread_count"] = int(existing.get("unread_count") or 0) + 1
            elif existing.get("_trail_unread"):
                if direction == "inbound":
                    existing["unread_count"] = int(existing.get("unread_count") or 0) + 1
                else:
                    existing["_trail_unread"] = False

        rows = sorted(
            by_phone.values(),
            key=lambda r: r.get("last_message_at") or "",
            reverse=True,
        )
        for row in rows:
            row.pop("_trail_unread", None)
            row["unread_count"] = int(row.get("unread_count") or 0)
            phone = row.get("phone") or ""
            digits = "".join(c for c in phone if c.isdigit())
            last10 = digits[-10:] if len(digits) >= 10 else ""
            if phone in lights_phones or (last10 and last10 in lights_phones):
                row["has_lights"] = True
            has_lights = bool(row.pop("has_lights", False))
            has_energy = bool(row.pop("has_energy", False))
            if not has_lights and not has_energy:
                has_energy = True
            row["_keep_lights"] = has_lights
            row["_keep_energy"] = has_energy or not has_lights
        if company == "lights":
            rows = [r for r in rows if r.get("_keep_lights")]
        elif company == "energy":
            rows = [r for r in rows if r.get("_keep_energy")]
        for row in rows:
            row.pop("_keep_lights", None)
            row.pop("_keep_energy", None)
        if q.strip():
            needle = q.strip().lower()
            rows = [
                r
                for r in rows
                if needle
                in f"{r.get('lead_name', '')} {r.get('phone', '')} {r.get('last_message', '')}".lower()
            ]
        return rows[:limit]

    def get_conversation_messages(
        self,
        phone: str,
        *,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """All SMS for one customer phone, oldest first (chat thread)."""
        normalized = normalize_e164(phone) or phone.strip()
        if not normalized:
            return []

        q = normalized.replace('"', '\\"')
        phone_filter = f'from_address.eq."{q}",to_address.eq."{q}"'

        resp = (
            self._client.table("customer_messages")
            .select(_MESSAGE_COLUMNS)
            .eq("channel", "sms")
            .or_(phone_filter)
            .order("created_at", desc=False)
            .limit(limit)
            .execute()
        )
        return resp.data or []

    def get_call(self, row_key: str) -> dict[str, Any] | None:
        resp = self._lead_query(
            lambda query: query.eq("row_key", row_key).maybe_single()
        )
        if not resp.data:
            return None

        bills_resp = (
            self._client.table("bill_uploads")
            .select(_BILL_COLUMNS)
            .eq("lead_row_key", row_key)
            .order("uploaded_at", desc=True)
            .execute()
        )
        bills = bills_resp.data or []
        return self._enrich_lead(
            {**resp.data, "bills": bills, "bill_count": len(bills)}
        )

    def list_sales_leads(
        self,
        *,
        q: str = "",
        limit: int = 500,
        zoho_only: bool = False,
        company: str = "",
    ) -> list[dict[str, Any]]:
        """Compact lead list for the Sales close form.

        company=lights keeps Lumi Lights rows. company=energy keeps the rest.
        """
        rows = self.list_calls(q=q, filter_by="all", limit=limit)
        company_filter = (company or "").strip().lower()
        out: list[dict[str, Any]] = []
        for row in rows:
            zid = (row.get("zoho_lead_id") or "").strip()
            if zoho_only and not zid:
                continue
            is_lights = lead_is_lights(row)
            if company_filter == "lights" and not is_lights:
                continue
            if company_filter == "energy" and is_lights:
                continue
            out.append(
                {
                    "row_key": row.get("row_key"),
                    "name": row.get("name") or "",
                    "email": row.get("email") or "",
                    "phone_no": row.get("phone_no") or "",
                    "dial_to": row.get("dial_to") or "",
                    "offer_page": row.get("offer_page") or "",
                    "zoho_lead_id": zid,
                    "has_zoho": bool(zid),
                    "pipeline_label": row.get("pipeline_label") or "",
                    "processed_at": row.get("processed_at"),
                    "business_unit": row.get("business_unit") or "",
                }
            )
        return out

    def get_lead_timeline(self, row_key: str) -> list[dict[str, Any]]:
        """Merged activity timeline for one lead."""
        lead = self.get_call(row_key)
        if not lead:
            return []

        events: list[dict[str, Any]] = []

        if lead.get("processed_at") or lead.get("first_call_at"):
            bill_part = (
                f" · Bill ${lead.get('monthly_bill')}"
                if lead.get("monthly_bill")
                else ""
            )
            events.append({
                "at": lead.get("first_call_at") or lead.get("processed_at"),
                "type": "lead_created",
                "title": "Lead received & dial queued",
                "detail": f"Offer: {lead.get('offer_page') or '—'}{bill_part}",
            })

        if lead.get("call_ended_at") or lead.get("call_duration_secs") is not None:
            twilio = lead.get("last_twilio_status") or ""
            duration = lead.get("call_duration_secs")
            attempt = lead.get("callback_attempt") or 1
            events.append({
                "at": lead.get("call_ended_at") or lead.get("processed_at"),
                "type": "call",
                "title": f"Call attempt #{attempt}",
                "detail": " · ".join(
                    p
                    for p in [
                        f"{duration}s" if duration is not None else None,
                        twilio or None,
                        lead.get("termination_reason") or None,
                        (
                            f"callback={lead.get('callback_status')}"
                            if lead.get("callback_status")
                            else None
                        ),
                    ]
                    if p
                ),
            })

        if lead.get("cal_booking_uid"):
            events.append({
                "at": lead.get("appointment_start")
                or lead.get("call_ended_at")
                or lead.get("processed_at"),
                "type": "booking",
                "title": "Appointment booked (agent)",
                "detail": lead.get("appointment_label") or lead.get("cal_booking_uid"),
            })

        if lead.get("self_booked"):
            events.append({
                "at": lead.get("call_ended_at") or lead.get("processed_at"),
                "type": "self_booked",
                "title": "Customer self-booked via calendar link",
                "detail": "",
            })

        if lead.get("report_sent"):
            email_type = (lead.get("report_email_type") or "").replace("_", " ")
            events.append({
                "at": lead.get("call_ended_at") or lead.get("processed_at"),
                "type": "report_email",
                "title": "Preliminary report emailed",
                "detail": email_type or "sent",
            })

        fu_status = (lead.get("followup_email_status") or "").lower()
        fu_attempt = int(lead.get("followup_email_attempt") or 0)
        fu_next = lead.get("next_followup_email_at")
        if fu_status and fu_status != "none":
            detail_parts = [f"status={fu_status}", f"sent={fu_attempt}/4"]
            if fu_next and fu_status == "active":
                detail_parts.append(f"next={fu_next}")
            events.append({
                "at": fu_next if fu_status == "active" and fu_next else (
                    lead.get("call_ended_at") or lead.get("processed_at")
                ),
                "type": "followup_email",
                "title": (
                    "Next follow-up email scheduled"
                    if fu_status == "active" and fu_next
                    else f"Follow-up emails ({fu_status})"
                ),
                "detail": " · ".join(detail_parts),
            })

        for bill in lead.get("bills") or []:
            events.append({
                "at": bill.get("uploaded_at"),
                "type": "bill_upload",
                "title": "Bill uploaded",
                "detail": bill.get("original_name") or "",
            })

        if lead.get("sms_sent"):
            events.append({
                "at": lead.get("call_ended_at") or lead.get("processed_at"),
                "type": "sms",
                "title": "Bill-upload SMS sent",
                "detail": "",
            })

        if lead.get("confirmation_sms_sent"):
            events.append({
                "at": lead.get("call_ended_at") or lead.get("processed_at"),
                "type": "confirmation",
                "title": "Consultation confirmation sent",
                "detail": lead.get("appointment_label") or "",
            })

        msg_resp = (
            self._client.table("customer_messages")
            .select(_MESSAGE_COLUMNS)
            .eq("lead_row_key", row_key)
            .order("created_at", desc=False)
            .limit(100)
            .execute()
        )
        for msg in msg_resp.data or []:
            mtype = msg.get("message_type") or "message"
            channel = msg.get("channel") or ""
            direction = msg.get("direction") or ""
            if mtype == "report_email":
                events.append({
                    "at": msg.get("created_at"),
                    "type": "report_email",
                    "title": "Report email delivery",
                    "detail": msg.get("status") or "",
                })
                continue
            if mtype in ("bill_upload", "confirmation") and direction == "outbound":
                continue
            body = (msg.get("body") or "")[:120]
            events.append({
                "at": msg.get("created_at"),
                "type": f"{channel}_{direction}",
                "title": f"{channel.upper()} {direction}: {mtype}",
                "detail": body,
            })

        events.sort(key=lambda e: e.get("at") or "", reverse=True)
        return events

    def get_bill_signed_url(
        self,
        bill_id: int,
        *,
        download: bool = False,
        expires_in: int = 3600,
    ) -> dict[str, str]:
        resp = (
            self._client.table("bill_uploads")
            .select("id, storage_path, original_name, content_type")
            .eq("id", bill_id)
            .maybe_single()
            .execute()
        )
        if not resp.data:
            raise AdminServiceError("Bill not found")

        path = resp.data.get("storage_path") or ""
        if not path:
            raise AdminServiceError("Bill has no storage path")

        options: dict | None = None
        if download:
            name = resp.data.get("original_name") or "bill"
            options = {"download": name}

        signed = self._client.storage.from_(self._bucket).create_signed_url(
            path,
            expires_in,
            options,
        )

        url = signed.get("signedURL") or signed.get("signedUrl") or ""
        if not url:
            raise AdminServiceError("Could not create signed URL")

        return {
            "url": url,
            "content_type": resp.data.get("content_type") or "application/octet-stream",
            "original_name": resp.data.get("original_name") or "",
        }

    @classmethod
    def _enrich_lead(cls, row: dict[str, Any]) -> dict[str, Any]:
        stage = cls.compute_pipeline_stage(row)
        return {
            **row,
            "pipeline_stage": stage,
            "pipeline_label": cls.stage_label(stage),
            "next_action": cls.compute_next_action(row),
            "has_streetview": bool((row.get("streetview_storage_path") or "").strip()),
            "has_lighting_preview": bool((row.get("streetview_render_path") or "").strip()),
        }

    @staticmethod
    def stage_label(stage: str) -> str:
        labels = {
            "new": "New",
            "trying": "Trying",
            "reached": "Reached",
            "booked": "Booked",
            "self_booked": "Self-booked",
            "report_sent": "Report sent",
            "bill_uploaded": "Bill uploaded",
            "confirmed": "Confirmed",
            "exhausted": "Exhausted",
            "failed": "Failed",
        }
        return labels.get(stage, stage.replace("_", " ").title())

    @staticmethod
    def compute_pipeline_stage(row: dict) -> str:
        """Most-progressed CRM stage for this lead."""
        if row.get("confirmation_sms_sent"):
            return "confirmed"
        if (row.get("bill_count") or 0) > 0:
            return "bill_uploaded"
        if row.get("self_booked"):
            return "self_booked"
        if row.get("cal_booking_uid"):
            return "booked"

        cb = (row.get("callback_status") or "").lower()
        if cb == "answered":
            if row.get("report_sent") and not row.get("cal_booking_uid"):
                return "report_sent"
            return "reached"
        if cb == "active":
            return "trying"
        if cb == "exhausted":
            return "exhausted"
        if cb == "self_booked":
            return "self_booked"
        if (row.get("status") or "").lower() == "failed":
            return "failed"
        if row.get("report_sent"):
            return "report_sent"
        return "new"

    @staticmethod
    def compute_next_action(row: dict) -> str:
        """One-line operator guidance."""
        if row.get("confirmation_sms_sent"):
            return "Done — consultation confirmed"
        if (row.get("bill_count") or 0) > 0 and not row.get("confirmation_sms_sent"):
            if row.get("appointment_label"):
                return "Bill in — confirm appointment"
            return "Bill uploaded — no appointment on file"
        if row.get("self_booked") or row.get("cal_booking_uid"):
            if not row.get("sms_sent") and (row.get("bill_count") or 0) == 0:
                return "Booked — send bill-upload link if needed"
            if not row.get("upload_token_used") and (row.get("bill_count") or 0) == 0:
                label = row.get("appointment_label") or "see calendar"
                return f"Booked · waiting for bill ({label})"
            return f"Booked · {row.get('appointment_label') or 'see calendar'}"

        fu_status = (row.get("followup_email_status") or "").lower()
        fu_attempt = int(row.get("followup_email_attempt") or 0)
        fu_next = row.get("next_followup_email_at")
        if fu_status == "active":
            short = ""
            if fu_next:
                try:
                    from datetime import datetime
                    from zoneinfo import ZoneInfo

                    raw = str(fu_next).replace("Z", "+00:00")
                    dt = datetime.fromisoformat(raw)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
                    az = dt.astimezone(ZoneInfo("America/Phoenix"))
                    short = f" · next {az.strftime('%b %d %H:%M')} AZ"
                except Exception:
                    short = f" · next {str(fu_next)[:16].replace('T', ' ')} UTC"
            return (
                f"Follow-up email active "
                f"({fu_attempt}/4 sent){short}"
            )
        if fu_status == "exhausted":
            return "Follow-up emails exhausted — manual outreach"
        if fu_status == "cancelled":
            return "Follow-up emails cancelled"

        cb = (row.get("callback_status") or "").lower()
        attempt = int(row.get("callback_attempt") or 0)
        if cb == "active":
            next_at = row.get("next_retry_at")
            if next_at:
                short = str(next_at)[:16].replace("T", " ")
                return f"Retry scheduled (attempt {attempt}) · {short} UTC"
            if row.get("call_in_progress"):
                return "Call in progress…"
            return f"Callback active (attempt {attempt})"
        if cb == "answered" and not row.get("cal_booking_uid"):
            if row.get("report_sent"):
                email_type = row.get("report_email_type") or ""
                if "with_calendar" in email_type:
                    return "Reached · report + calendar — waiting to book"
                return "Reached · report sent — follow up to book"
            return "Reached — book appointment or send report"
        if cb == "exhausted":
            if row.get("report_sent"):
                return "Retries exhausted · report sent — manual follow-up"
            return "Retries exhausted — manual follow-up"
        if (row.get("status") or "").lower() == "failed":
            return "Dial failed — check phone number"
        offer = (row.get("offer_page") or "").lower()
        if offer in REPORT_ELIGIBLE_OFFERS and not row.get("report_sent"):
            return "Awaiting call end → report email"
        return "New lead — awaiting first outcome"

    @staticmethod
    def _matches_query(row: dict, query: str) -> bool:
        haystack = " ".join(
            str(row.get(k) or "")
            for k in (
                "name",
                "phone_no",
                "dial_to",
                "address",
                "row_key",
                "email",
                "offer_page",
                "pipeline_stage",
            )
        ).lower()
        return query in haystack

    @staticmethod
    def _matches_filter(row: dict, filter_by: str) -> bool:
        if filter_by == "all":
            return True
        if filter_by == "bill_uploaded":
            return row.get("bill_count", 0) > 0
        if filter_by == "no_bill":
            return row.get("bill_count", 0) == 0
        if filter_by == "sms_sent":
            return bool(row.get("sms_sent"))
        if filter_by == "call_failed":
            return not AdminService._is_call_successful(row)
        if filter_by == "callback_active":
            return row.get("callback_status") == "active"
        if filter_by == "report_sent":
            return bool(row.get("report_sent"))
        if filter_by == "report_pending":
            offer = (row.get("offer_page") or "").lower()
            return offer in REPORT_ELIGIBLE_OFFERS and not row.get("report_sent")
        if filter_by == "self_booked":
            return bool(row.get("self_booked"))
        if filter_by == "followup_emails":
            return (row.get("followup_email_status") or "").lower() == "active"
        if filter_by in PIPELINE_STAGES:
            return row.get("pipeline_stage") == filter_by
        return True

    @staticmethod
    def _is_call_successful(row: dict) -> bool:
        val = str(row.get("call_successful") or "").lower()
        if val in ("true", "success", "yes", "1"):
            return True
        if val in ("false", "failure", "failed", "no", "0"):
            return False
        return bool(val)


def get_admin_service() -> AdminService:
    return AdminService()
