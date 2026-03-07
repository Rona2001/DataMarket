"""
Test configuration — shared fixtures for all tests.

Uses a separate SQLite in-memory database so tests never touch production.
Mocks Supabase Storage and Stripe so tests run offline with no API keys.
"""
import pytest
import io
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base, get_db
from app.core.security import hash_password
from main import app

# ── In-memory test database ───────────────────────────────────────────────────

TEST_DB_URL = "sqlite:///./test.db"

engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def setup_database():
    """Fresh database for every test."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def buyer_data():
    return {
        "email": "buyer@test.com",
        "password": "Buyer1234",
        "full_name": "Test Buyer",
        "role": "buyer",
    }


@pytest.fixture
def seller_data():
    return {
        "email": "seller@test.com",
        "password": "Seller1234",
        "full_name": "Test Seller",
        "role": "seller",
    }


@pytest.fixture
def registered_buyer(client, buyer_data):
    res = client.post("/api/v1/auth/register", json=buyer_data)
    assert res.status_code == 201
    return res.json()


@pytest.fixture
def registered_seller(client, seller_data):
    res = client.post("/api/v1/auth/register", json=seller_data)
    assert res.status_code == 201
    return res.json()


@pytest.fixture
def buyer_token(client, registered_buyer, buyer_data):
    res = client.post("/api/v1/auth/login", data={
        "username": buyer_data["email"],
        "password": buyer_data["password"],
    })
    return res.json()["access_token"]


@pytest.fixture
def seller_token(client, registered_seller, seller_data):
    res = client.post("/api/v1/auth/login", data={
        "username": seller_data["email"],
        "password": seller_data["password"],
    })
    return res.json()["access_token"]


@pytest.fixture
def auth_buyer(buyer_token):
    return {"Authorization": f"Bearer {buyer_token}"}


@pytest.fixture
def auth_seller(seller_token):
    return {"Authorization": f"Bearer {seller_token}"}


@pytest.fixture
def sample_csv_bytes():
    """A small valid CSV file for upload tests."""
    content = (
        "id,name,age,city,salary\n"
        "1,Alice,30,Paris,55000\n"
        "2,Bob,25,Lyon,42000\n"
        "3,Charlie,35,Marseille,61000\n"
    )
    return content.encode("utf-8")


@pytest.fixture
def mock_storage():
    """Mock all Supabase storage calls."""
    with patch("app.core.storage.get_supabase") as mock:
        supabase = MagicMock()
        mock.return_value = supabase
        supabase.storage.from_().upload.return_value = {"Key": "test-key"}
        supabase.storage.from_().create_signed_url.return_value = {
            "signedURL": "https://supabase.example.com/signed/test-dataset.csv?token=abc123"
        }
        supabase.storage.from_().get_public_url.return_value = (
            "https://supabase.example.com/public/test-sample.csv"
        )
        supabase.storage.from_().remove.return_value = {}
        yield supabase


@pytest.fixture
def mock_stripe():
    """Mock Stripe API calls."""
    with patch("app.core.stripe_client.stripe") as mock:
        intent = MagicMock()
        intent.id = "pi_test_123"
        intent.client_secret = "pi_test_123_secret_abc"
        intent.status = "requires_payment_method"
        mock.PaymentIntent.create.return_value = intent
        mock.PaymentIntent.retrieve.return_value = intent

        refund = MagicMock()
        refund.id = "re_test_123"
        refund.status = "succeeded"
        refund.amount = 1000
        mock.Refund.create.return_value = refund

        account = MagicMock()
        account.id = "acct_test_123"
        account.charges_enabled = True
        account.payouts_enabled = True
        account.details_submitted = True
        mock.Account.create.return_value = account
        mock.Account.retrieve.return_value = account

        link = MagicMock()
        link.url = "https://connect.stripe.com/onboarding/test"
        mock.AccountLink.create.return_value = link
        yield mock
