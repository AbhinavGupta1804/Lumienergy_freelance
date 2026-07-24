"""Send a test email via Resend (domain must be verified)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.integrations.smtp_email import send_email  # noqa: E402


async def main() -> None:
    to = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    if not to or "@" not in to:
        print("Usage: python scripts/test_resend_email.py you@example.com")
        sys.exit(1)

    result = await send_email(
        to_email=to,
        subject="Lumi Energy — Resend test",
        body_text=(
            "Hi,\n\n"
            "This is a test email from Lumi Energy via Resend "
            "(from support@lumienergy.us).\n\n"
            "— Lumi Energy"
        ),
    )
    if result.success:
        print(f"SUCCESS to={result.to_email} id={result.provider_id}")
    else:
        print(f"FAIL to={result.to_email} error={result.error}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
