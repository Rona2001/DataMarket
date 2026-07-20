"""
Brevo (ex-Sendinblue) client — transactional email + contact capture.

Every function degrades gracefully: if BREVO_API_KEY is unset (local/dev),
calls become no-ops rather than raising. This keeps the free quality report
(spec §4) working with zero email config during development.
"""
import logging
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_BASE = "https://api.brevo.com/v3"


def _headers() -> dict:
    return {
        "api-key": settings.BREVO_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def is_configured() -> bool:
    return bool(settings.BREVO_API_KEY)


def add_contact(email: str, attributes: dict | None = None, list_id: int | None = None) -> bool:
    """
    Create/update a contact and optionally add it to a list.
    Returns True on success, False if skipped or failed (never raises).
    """
    if not is_configured():
        logger.info("Brevo not configured — skipping add_contact for %s", email)
        return False

    payload: dict = {"email": email, "updateEnabled": True}
    if attributes:
        payload["attributes"] = attributes
    target_list = list_id if list_id is not None else settings.BREVO_QUALITY_REPORT_LIST_ID
    if target_list:
        payload["listIds"] = [target_list]

    try:
        resp = httpx.post(f"{_BASE}/contacts", json=payload, headers=_headers(), timeout=15)
        # 201 created, 204 updated — both fine.
        if resp.status_code in (200, 201, 204):
            return True
        logger.warning("Brevo add_contact failed: %s %s", resp.status_code, resp.text)
        return False
    except Exception as e:  # network errors must never break the request flow
        logger.warning("Brevo add_contact error: %s", e)
        return False


def send_email(to_email: str, subject: str, html: str, to_name: str | None = None) -> bool:
    """
    Send a plain transactional email. Best-effort: no-op if Brevo is unconfigured,
    never raises. Used for request-board notification hooks (spec §10).
    """
    if not is_configured():
        logger.info("Brevo not configured — skipping send_email to %s", to_email)
        return False

    payload = {
        "sender": {"name": settings.BREVO_SENDER_NAME, "email": settings.BREVO_SENDER_EMAIL},
        "to": [{"email": to_email, **({"name": to_name} if to_name else {})}],
        "subject": subject,
        "htmlContent": html,
    }
    try:
        resp = httpx.post(f"{_BASE}/smtp/email", json=payload, headers=_headers(), timeout=15)
        if resp.status_code in (200, 201):
            return True
        logger.warning("Brevo send_email failed: %s %s", resp.status_code, resp.text)
        return False
    except Exception as e:
        logger.warning("Brevo send_email error: %s", e)
        return False
