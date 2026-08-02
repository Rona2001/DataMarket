"""
Platform transactional emails (spec §18).

Event-driven, founder-voice, plain-format notifications for the core lifecycle:
upload received, verification result, purchase confirmation + delivery, and
dispute updates. Everything goes through Brevo (app/core/brevo.py) and is
strictly best-effort — an email failure must never break the transaction.

Copy is currently English. FR variants are a copy task (deferred), not code —
the plumbing already accepts any language.
"""
import logging

from sqlalchemy.orm import Session

from app.core import brevo
from app.core.config import settings

logger = logging.getLogger(__name__)

_SIGNOFF = "<p style=\"color:#666;font-size:13px\">— Rona &amp; Maria, datrust</p>"


def _send(to_email: str, subject: str, body_html: str, to_name: str | None = None) -> None:
    """Best-effort send with one retry. Never raises."""
    html = f"{body_html}{_SIGNOFF}"
    for attempt in (1, 2):
        try:
            if brevo.send_email(to_email, subject, html, to_name):
                return
        except Exception as e:  # brevo.send_email already swallows, this is belt-and-braces
            logger.warning("notification send error (attempt %s): %s", attempt, e)
    logger.info("notification not delivered to %s (subject: %s)", to_email, subject)


# ── Welcome (new account) ───────────────────────────────────────────────────────

def welcome(email: str, name: str | None, role: str) -> None:
    """
    Greet a freshly-registered user. Role-aware CTA: buyers get 'browse',
    sellers get 'list your data', 'both' get both. Best-effort — never blocks
    or breaks signup.
    """
    base = settings.FRONTEND_URL.rstrip("/")
    is_seller = role in ("seller", "both")
    is_buyer = role in ("buyer", "both")

    ctas = []
    if is_buyer:
        ctas.append(
            f'<p><a href="{base}/dashboard/buyer">Browse the marketplace</a> — '
            f"every dataset is quality-scored and screened for PII/RGPD compliance before it's listed.</p>"
        )
    if is_seller:
        ctas.append(
            f'<p><a href="{base}/dashboard/seller">List your first dataset</a> — '
            f"upload it and our verification pipeline scores it automatically, so buyers can trust it.</p>"
        )

    _send(
        email,
        "Welcome to datrust",
        f"<p>Hi {name or 'there'},</p>"
        f"<p>Welcome aboard — your datrust account is ready. datrust is the marketplace for "
        f"verified, compliance-checked datasets, and you're all set to get started.</p>"
        + "".join(ctas)
        + "<p>Questions or feedback? Just reply to this email — we read every one.</p>",
        name,
    )


# ── Upload received (seller) ────────────────────────────────────────────────────

def upload_received(email: str, name: str | None, dataset_title: str) -> None:
    _send(
        email,
        "We've got your dataset — verification is running",
        f"<p>Hi {name or 'there'},</p>"
        f"<p>Thanks for uploading <strong>{dataset_title}</strong>. Our verification pipeline "
        f"is already scanning it for quality and PII/RGPD compliance — you'll get the results "
        f"shortly, and you can follow along from your seller dashboard.</p>",
        name,
    )


# ── Verification result (seller) ────────────────────────────────────────────────

def verification_done(db: Session, dataset_id: str) -> None:
    from app.models.dataset import Dataset, DatasetStatus

    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset or not dataset.seller or not dataset.seller.email:
        return

    link = f"{settings.FRONTEND_URL.rstrip('/')}/dashboard/seller"
    name = dataset.seller.full_name

    if dataset.status == DatasetStatus.VERIFIED:
        _send(
            dataset.seller.email,
            f"Verified — {dataset.title} scored {int(dataset.quality_score or 0)}/100",
            f"<p>Hi {name or 'there'},</p>"
            f"<p><strong>{dataset.title}</strong> passed verification with a quality score of "
            f"<strong>{int(dataset.quality_score or 0)}/100</strong>. You can publish it to the "
            f"marketplace whenever you're ready.</p>"
            f"<p><a href=\"{link}\">Open your dashboard</a>.</p>",
            name,
        )
    elif dataset.status == DatasetStatus.REJECTED:
        report = dataset.verification_report if isinstance(dataset.verification_report, dict) else {}
        reason = report.get("rejection_reason", "See the full report in your dashboard.")
        _send(
            dataset.seller.email,
            f"Verification needs attention — {dataset.title}",
            f"<p>Hi {name or 'there'},</p>"
            f"<p>We couldn't verify <strong>{dataset.title}</strong> yet. Here's why:</p>"
            f"<p style=\"color:#b45309\">{reason}</p>"
            f"<p>Fix it and resubmit from your <a href=\"{link}\">dashboard</a> — happy to help if you're stuck.</p>",
            name,
        )


# ── Purchase confirmation + delivery (buyer) ─────────────────────────────────────

def purchase_completed(db: Session, purchase_id: str) -> None:
    from app.models.purchase import Purchase
    from app.models.dataset import Dataset
    from app.models.user import User

    purchase = db.query(Purchase).filter(Purchase.id == purchase_id).first()
    if not purchase:
        return
    buyer = db.query(User).filter(User.id == purchase.buyer_id).first()
    dataset = db.query(Dataset).filter(Dataset.id == purchase.dataset_id).first()
    if not buyer or not buyer.email or not dataset:
        return

    link = f"{settings.FRONTEND_URL.rstrip('/')}/dashboard/buyer"
    checksum = f"<p style=\"font-size:12px;color:#666\">Integrity (SHA-256): <code>{dataset.checksum}</code></p>" if dataset.checksum else ""
    _send(
        buyer.email,
        f"Your datrust dataset is ready — {dataset.title}",
        f"<p>Hi {buyer.full_name or 'there'},</p>"
        f"<p>Your {'download' if dataset.is_free else 'purchase'} of <strong>{dataset.title}</strong> is confirmed. "
        f"Download it from your <a href=\"{link}\">dashboard</a> — the secure link is generated fresh each time and "
        f"you can re-download whenever you need.</p>"
        f"{checksum}",
        buyer.full_name,
    )


# ── Dispute updates ─────────────────────────────────────────────────────────────

def dispute_opened(db: Session, purchase_id: str) -> None:
    from app.models.purchase import Purchase
    from app.models.dataset import Dataset
    from app.models.user import User

    purchase = db.query(Purchase).filter(Purchase.id == purchase_id).first()
    if not purchase:
        return
    buyer = db.query(User).filter(User.id == purchase.buyer_id).first()
    dataset = db.query(Dataset).filter(Dataset.id == purchase.dataset_id).first()
    title = dataset.title if dataset else "a dataset"

    # Confirm to the buyer.
    if buyer and buyer.email:
        _send(
            buyer.email,
            f"We've received your dispute — {title}",
            f"<p>Hi {buyer.full_name or 'there'},</p>"
            f"<p>Your dispute for <strong>{title}</strong> is in. The funds stay in escrow while we "
            f"review it — we'll get back to you as soon as we can.</p>",
            buyer.full_name,
        )
    # Alert support/ops.
    _send(
        settings.SUPPORT_EMAIL,
        f"[Dispute] {title} — purchase {str(purchase.id)[:8]}",
        f"<p>A buyer opened a dispute.</p>"
        f"<p>Dataset: {title}<br>Purchase: {purchase.id}<br>Reason: {purchase.dispute_reason or '—'}</p>",
    )


def dispute_resolved(db: Session, purchase_id: str, favour_buyer: bool) -> None:
    from app.models.purchase import Purchase
    from app.models.dataset import Dataset
    from app.models.user import User

    purchase = db.query(Purchase).filter(Purchase.id == purchase_id).first()
    if not purchase:
        return
    buyer = db.query(User).filter(User.id == purchase.buyer_id).first()
    dataset = db.query(Dataset).filter(Dataset.id == purchase.dataset_id).first()
    if not buyer or not buyer.email:
        return
    title = dataset.title if dataset else "your dataset"

    outcome = (
        "we've refunded your purchase in full. The funds should land back on your card shortly."
        if favour_buyer
        else "after review, the dataset matched its description, so the purchase stands and your download remains available."
    )
    _send(
        buyer.email,
        f"Your dispute has been resolved — {title}",
        f"<p>Hi {buyer.full_name or 'there'},</p>"
        f"<p>We've resolved your dispute for <strong>{title}</strong>: {outcome}</p>"
        f"<p>Thanks for your patience.</p>",
        buyer.full_name,
    )
