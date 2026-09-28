"""Billing integration.

The provider issues a short-lived token. When it expires, the API returns HTTP 401 and no
amount of application-code change can fix that — the credential has to be rotated by the
team that owns it. This module exists to exercise that case honestly in the agent's demo:
classify, explain, escalate.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

# Issued by the billing provider when the service is provisioned. Must be rotated before
# it expires; the value is managed by the platform team, not by application code.
BILLING_TOKEN_EXPIRES_AT = os.environ.get("BILLING_TOKEN_EXPIRES_AT", "2027-06-30T00:00:00Z")
BILLING_API_BASE_URL = os.environ.get("BILLING_API_BASE_URL", "https://billing.internal.example")


class BillingAuthError(RuntimeError):
    """The billing API rejected our credential."""


class BillingServiceError(RuntimeError):
    """The billing API is unavailable (5xx, DNS, connectivity)."""


def _parse(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))


def token_is_expired(*, now: datetime | None = None, expires_at: str | None = None) -> bool:
    moment = now or datetime.now(timezone.utc)
    return moment >= _parse(expires_at or BILLING_TOKEN_EXPIRES_AT)


def fetch_invoice(invoice_id: str, *, now: datetime | None = None) -> dict:
    """Fetch one invoice. Raises BillingAuthError when the token has expired."""
    if token_is_expired(now=now):
        raise BillingAuthError(
            f"AuthenticationError: billing API rejected the request for invoice "
            f"{invoice_id} - token expired at {BILLING_TOKEN_EXPIRES_AT} "
            f"(HTTP 401 Unauthorized) from {BILLING_API_BASE_URL}"
        )
    return {
        "invoice_id": invoice_id,
        "amount_inr": 48250.0,
        "currency": "INR",
        "status": "paid",
        "issued_at": "2026-08-01",
    }
