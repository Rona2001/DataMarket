# DataMarket — Backend API

Secure, GDPR-compliant dataset marketplace. Built with FastAPI + PostgreSQL + Supabase Storage + Stripe.

---

## Stack

| Layer | Technology |
|-------|-----------|
| API | FastAPI (Python 3.11) |
| Database | PostgreSQL 16 |
| ORM | SQLAlchemy + Alembic |
| Auth | JWT (access + refresh tokens) |
| Storage | Supabase Storage (private + public buckets) |
| Payments | Stripe Connect (escrow + payouts) |
| Tests | pytest + TestClient |
| Deploy | Docker + Render / Railway |

---

## Project Structure

```
datamarket/
├── main.py                        # App entry point
├── requirements.txt
├── Dockerfile
├── docker-compose.yml             # Local dev with Postgres + Stripe CLI
├── .env.example
├── alembic/env.py                 # Migration config
├── scripts/seed.py                # Create admin + test users
├── tests/
│   ├── conftest.py                # Fixtures + mocks
│   ├── test_auth.py
│   ├── test_datasets.py
│   ├── test_verification.py
│   └── test_purchases.py
└── app/
    ├── api/routes/                # HTTP endpoints
    ├── core/                      # Config, security, storage, stripe
    ├── db/                        # DB session
    ├── models/                    # SQLAlchemy models
    ├── schemas/                   # Pydantic schemas
    ├── services/                  # Business logic
    ├── utils/                     # File processing
    └── verification/              # PII detection + quality scoring
```

---

## Quick Start

### With Docker (recommended)
```bash
cp .env.example .env        # fill in your keys
docker-compose up --build
# API  → http://localhost:8000
# Docs → http://localhost:8000/docs
```

### Manually
```bash
pip install -r requirements.txt
python -m spacy download fr_core_news_sm
cp .env.example .env
alembic upgrade head
python scripts/seed.py --with-test-data
uvicorn main:app --reload
```

---

## Supabase Setup
1. Create project at supabase.com
2. Storage → create `datasets` bucket (**Private**) and `samples` bucket (**Public**)
3. Copy Project URL + service_role key → `.env`

---

## Stripe Setup
1. Enable Connect at stripe.com
2. Add keys to `.env`
3. Webhook endpoint: `https://yourdomain.com/api/v1/webhooks/stripe`
4. Events: `payment_intent.succeeded`, `payment_intent.payment_failed`, `account.updated`

---

## Running Tests
```bash
pytest tests/ -v
```

---

## Full API Reference

### Auth
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | /api/v1/auth/register | — | Register |
| POST | /api/v1/auth/login | — | Login → JWT tokens |
| POST | /api/v1/auth/refresh | — | Refresh access token |
| GET | /api/v1/auth/me | ✅ | My profile |

### Datasets
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | /api/v1/datasets | — | Browse marketplace |
| GET | /api/v1/datasets/{id} | — | Dataset detail |
| POST | /api/v1/datasets | ✅ Seller | Upload (multipart) |
| GET | /api/v1/datasets/mine/list | ✅ Seller | My datasets |
| PATCH | /api/v1/datasets/{id} | ✅ Seller | Update metadata |
| POST | /api/v1/datasets/{id}/publish | ✅ Seller | Publish |
| POST | /api/v1/datasets/{id}/unpublish | ✅ Seller | Unpublish |
| DELETE | /api/v1/datasets/{id} | ✅ Seller | Delete |

### Verification
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | /api/v1/datasets/{id}/verify | ✅ Seller | Submit for verification |
| GET | /api/v1/datasets/{id}/verification | ✅ Seller | Get report |
| POST | /api/v1/admin/datasets/{id}/verify | ✅ Admin | Force verify |
| GET | /api/v1/admin/datasets/pending | ✅ Admin | Pending queue |
| GET | /api/v1/admin/datasets/rejected | ✅ Admin | Rejected datasets |

### Purchases & Payments
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | /api/v1/purchases | ✅ | Buy dataset |
| GET | /api/v1/purchases | ✅ | My purchases |
| GET | /api/v1/purchases/{id}/download | ✅ | Get signed URL |
| POST | /api/v1/purchases/{id}/dispute | ✅ | Open dispute (48h window) |
| POST | /api/v1/purchases/{id}/review | ✅ | Leave rating + review |
| GET | /api/v1/seller/onboarding | ✅ Seller | Stripe onboarding URL |
| GET | /api/v1/seller/payout-status | ✅ Seller | Payout readiness |
| POST | /api/v1/admin/purchases/{id}/resolve | ✅ Admin | Resolve dispute |
| POST | /api/v1/webhooks/stripe | — | Stripe events |

---

## Deploy to Render
1. Push to GitHub → connect repo on render.com
2. Build: `pip install -r requirements.txt && alembic upgrade head`
3. Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Add env vars + attach a managed PostgreSQL database
