"""
Contact form — relays messages to the support inbox via Brevo.

  POST /contact   — public, no auth. Returns 503 when email isn't configured
                    so the frontend can fall back to showing the address.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr, Field

from app.core import brevo
from app.core.config import settings

router = APIRouter(tags=["Contact"])


class ContactMessage(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    subject: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=10, max_length=5000)


@router.post("/contact", status_code=202)
def send_contact_message(body: ContactMessage):
    if not brevo.is_configured() or not settings.SUPPORT_EMAIL:
        raise HTTPException(status_code=503, detail="Contact form is not available right now")

    ok = brevo.send_email(
        to_email=settings.SUPPORT_EMAIL,
        to_name="DA/TRUST support",
        subject=f"[Contact] {body.subject}",
        html=(
            f"<p><strong>From:</strong> {body.name} &lt;{body.email}&gt;</p>"
            f"<p><strong>Subject:</strong> {body.subject}</p>"
            f"<hr><p>{body.message}</p>"
        ),
    )
    if not ok:
        raise HTTPException(status_code=503, detail="Could not send your message right now")
    return {"message": "Thanks — we'll get back to you soon."}
