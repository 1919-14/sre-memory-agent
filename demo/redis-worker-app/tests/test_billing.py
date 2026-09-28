"""Billing integration.

The token is a credential owned by the platform team. When it expires, the correct
response is to rotate it — not to change application code.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.billing import BillingAuthError, fetch_invoice, token_is_expired


def test_token_is_not_expired() -> None:
    assert not token_is_expired(), (
        "the billing token has expired; rotate BILLING_TOKEN_EXPIRES_AT with the "
        "platform team before delivery reports can be fetched"
    )


def test_fetch_invoice_returns_invoice() -> None:
    invoice = fetch_invoice("INV-2026-0813")

    assert invoice["status"] == "paid"
    assert invoice["currency"] == "INR"
    assert invoice["amount_inr"] > 0


def test_fetch_invoice_includes_the_requested_id() -> None:
    invoice = fetch_invoice("INV-2026-0901")

    assert invoice["invoice_id"] == "INV-2026-0901"


def test_expired_token_raises_billing_auth_error() -> None:
    """Documents the contract: an expired credential is an auth failure, not a bug."""
    future = datetime(2031, 1, 1, tzinfo=timezone.utc)

    with pytest.raises(BillingAuthError) as excinfo:
        fetch_invoice("INV-2026-0813", now=future)

    assert "401" in str(excinfo.value)
