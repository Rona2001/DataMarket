"""
Embeddable Verification Badge (spec §15).

Public, no-auth SVG badge a seller can embed on HAL / Zenodo / GitHub. Every
badge is a backlink to datrust. The badge reflects LIVE state: a dataset that
is not published+verified renders a neutral 'unverified' badge, so the badge
can never make a stale trust claim.

  GET /badge/{dataset_id}.svg
"""
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.dataset import Dataset, DatasetStatus

router = APIRouter(tags=["Badge"])

# Brand palette
NAVY = "#0A0E1A"
BLUE = "#4F6EF7"
VIOLET = "#7C3AED"
GREEN = "#10B981"
GREY = "#64748B"

_CHAR_W = 6.4          # approx width per char at font-size 11
_PAD = 10


def _text_width(text: str) -> int:
    return int(len(text) * _CHAR_W) + _PAD * 2


def _render_badge(left: str, right: str, right_bg: str) -> str:
    lw = _text_width(left)
    rw = _text_width(right)
    w = lw + rw
    h = 22
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" role="img" aria-label="{left}: {right}">
  <defs>
    <linearGradient id="l" x2="0" y2="100%">
      <stop offset="0" stop-color="#fff" stop-opacity=".08"/>
      <stop offset="1" stop-opacity=".08"/>
    </linearGradient>
    <linearGradient id="brand" x1="0" x2="1">
      <stop offset="0" stop-color="{BLUE}"/>
      <stop offset="1" stop-color="{VIOLET}"/>
    </linearGradient>
  </defs>
  <rect rx="4" width="{w}" height="{h}" fill="{NAVY}"/>
  <rect rx="4" x="{lw}" width="{rw}" height="{h}" fill="{right_bg}"/>
  <rect rx="4" width="{w}" height="{h}" fill="url(#l)"/>
  <g fill="#fff" text-anchor="middle" font-family="Verdana,DejaVu Sans,Geneva,sans-serif" font-size="11">
    <text x="{lw/2:.0f}" y="15">{left}</text>
    <text x="{lw + rw/2:.0f}" y="15">{right}</text>
  </g>
</svg>"""


def _badge_for(dataset: Dataset) -> str:
    verified = (
        dataset.status in (DatasetStatus.VERIFIED, DatasetStatus.PUBLISHED)
        and dataset.quality_score is not None
    )
    if not verified:
        return _render_badge("datrust", "unverified", GREY)

    score = int(round(dataset.quality_score))
    rgpd_clean = dataset.pii_risk_level == "none"
    right = f"verified {score}/100" + (" · RGPD" if rgpd_clean else "")
    return _render_badge("datrust", right, GREEN)


@router.get("/badge/{dataset_id}.svg")
def dataset_badge(dataset_id: str, db: Session = Depends(get_db)):
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    svg = _render_badge("datrust", "unverified", GREY) if dataset is None else _badge_for(dataset)
    return Response(
        content=svg,
        media_type="image/svg+xml",
        # Short cache so revocation (unpublish) reflects quickly (spec §15).
        headers={"Cache-Control": "public, max-age=300"},
    )
