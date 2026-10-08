"""
Enforce the "no personal data on the marketplace" policy across the existing catalogue.

The publish gate (dataset_service.pii_block_reason) only applies to future publishes.
Anything already PUBLISHED predates it, so this script re-applies the same rule to
what is live now and pulls non-compliant listings back to DRAFT.

It flags two kinds of listing:
  1. Personal data detected by the scanner.
  2. Never scanned at all, so we cannot claim it is clean.

Dry run by default. Nothing is written unless you pass --apply.

    python -m scripts.enforce_pii_policy            # report only
    python -m scripts.enforce_pii_policy --apply    # actually unpublish

Run it from the backend root, on a host that can reach the database
(Render shell works; a local machine may be blocked from Postgres).
"""
import sys

from app.db.session import SessionLocal
from app.models.dataset import Dataset, DatasetStatus
from app.services.dataset_service import pii_block_reason


def main(apply: bool) -> int:
    db = SessionLocal()
    try:
        published = db.query(Dataset).filter(Dataset.status == DatasetStatus.PUBLISHED).all()
        print(f"{len(published)} published dataset(s) to check\n")

        offenders = []
        for ds in published:
            reason = pii_block_reason(ds)
            if reason:
                offenders.append((ds, reason))
                short = "PERSONAL DATA" if "Personal data was detected" in reason else "NEVER SCANNED"
                print(f"  [{short:13}] {ds.title[:48]!r}")
                print(f"                  id={ds.id}  risk={ds.pii_risk_level}  seller={ds.seller_id}")

        if not offenders:
            print("Catalogue is already compliant. Nothing to do.")
            return 0

        print(f"\n{len(offenders)} listing(s) violate the policy.")

        if not apply:
            print("Dry run. Re-run with --apply to unpublish them.")
            return 0

        for ds, _ in offenders:
            ds.status = DatasetStatus.DRAFT
            ds.published_at = None
        db.commit()
        print(f"Unpublished {len(offenders)} listing(s). Sellers can fix and resubmit them.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main(apply="--apply" in sys.argv))
