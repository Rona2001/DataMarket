"""
Stripe client — all Stripe API calls go through here.

Escrow model on DataMarket:
  1. Buyer pays → PaymentIntent captured (funds held by Stripe)
  2. Dataset verified + delivered → Transfer to seller's Stripe account
  3. Platform keeps 10% commission automatically via application_fee_amount
  4. Dispute? → Refund the PaymentIntent, cancel the transfer

Requires Stripe Connect (Express accounts) so sellers can receive payouts.
"""
import stripe
from app.core.config import settings

stripe.api_key = settings.STRIPE_SECRET_KEY

PLATFORM_FEE_RATE = 0.10   # 10% commission


# ── Payment Intent (buyer pays) ───────────────────────────────────────────────

def create_payment_intent(
    amount_eur: float,
    buyer_email: str,
    dataset_id: str,
    dataset_title: str,
    seller_stripe_account_id: str,
) -> dict:
    """
    Create a PaymentIntent with:
    - application_fee_amount = 10% kept by platform
    - transfer_data → remaining 90% goes to seller's Stripe account
    - capture_method = automatic (funds held until confirmed)

    Returns the client_secret needed by the frontend to complete payment.
    """
    amount_cents = int(round(amount_eur * 100))
    fee_cents = int(round(amount_cents * PLATFORM_FEE_RATE))

    intent = stripe.PaymentIntent.create(
        amount=amount_cents,
        currency="eur",
        application_fee_amount=fee_cents,
        transfer_data={"destination": seller_stripe_account_id},
        receipt_email=buyer_email,
        metadata={
            "dataset_id": dataset_id,
            "dataset_title": dataset_title,
        },
        description=f"DataMarket — {dataset_title}",
    )

    return {
        "payment_intent_id": intent.id,
        "client_secret": intent.client_secret,
        "amount_eur": amount_eur,
        "fee_eur": round(fee_cents / 100, 2),
        "seller_payout_eur": round((amount_cents - fee_cents) / 100, 2),
        "status": intent.status,
    }


def get_payment_intent(payment_intent_id: str) -> stripe.PaymentIntent:
    return stripe.PaymentIntent.retrieve(payment_intent_id)


# ── Refunds (dispute resolution) ─────────────────────────────────────────────

def refund_payment(payment_intent_id: str, reason: str = "requested_by_customer") -> dict:
    """
    Refund a payment. Used when:
    - Dataset fails post-purchase verification
    - Buyer wins a dispute
    - Seller deletes a purchased dataset
    """
    refund = stripe.Refund.create(
        payment_intent=payment_intent_id,
        reason=reason,
    )
    return {
        "refund_id": refund.id,
        "status": refund.status,
        "amount_refunded_eur": round(refund.amount / 100, 2),
    }


# ── Stripe Connect (seller onboarding) ───────────────────────────────────────

def create_seller_account(email: str) -> str:
    """
    Create a Stripe Express account for a new seller.
    Returns the Stripe account ID to store in the User record.
    """
    account = stripe.Account.create(
        type="express",
        country="FR",
        email=email,
        capabilities={
            "transfers": {"requested": True},
            "card_payments": {"requested": True},
        },
        business_type="individual",
        settings={"payouts": {"schedule": {"interval": "weekly"}}},
    )
    return account.id


def create_seller_onboarding_link(stripe_account_id: str, return_url: str, refresh_url: str) -> str:
    """
    Generate a Stripe-hosted onboarding URL.
    Seller completes KYC/bank details on Stripe's side (we never touch that data).
    """
    link = stripe.AccountLink.create(
        account=stripe_account_id,
        refresh_url=refresh_url,
        return_url=return_url,
        type="account_onboarding",
    )
    return link.url


def get_seller_account(stripe_account_id: str) -> dict:
    """Check if a seller has completed Stripe onboarding."""
    account = stripe.Account.retrieve(stripe_account_id)
    return {
        "id": account.id,
        "charges_enabled": account.charges_enabled,
        "payouts_enabled": account.payouts_enabled,
        "details_submitted": account.details_submitted,
    }


# ── Webhooks ──────────────────────────────────────────────────────────────────

def construct_webhook_event(payload: bytes, sig_header: str) -> stripe.Event:
    """Verify and parse an incoming Stripe webhook."""
    return stripe.Webhook.construct_event(
        payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
    )
