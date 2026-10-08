"""
Premium subscription tests — Stripe is fully mocked.
"""
import time
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from app.core import stripe_client
from app.core.config import settings
from app.core.security import hash_password
from app.models.subscription import Subscription
from app.models.user import User
from app.services import billing_service


def sub(status="active", sub_id="sub_1", cancel=False, days=30):
    return {"id": sub_id, "customer": "cus_1", "status": status, "cancel_at_period_end": cancel,
            "current_period_end": int(time.time()) + days * 86400, "metadata": {}}


@pytest.fixture
def user(db):
    u = User(email="buyer@x.com", hashed_password=hash_password("Passw0rd!"), full_name="Buyer")
    db.add(u)
    db.commit()
    return u


@pytest.fixture(autouse=True)
def stripe_key():
    with patch.object(settings, "STRIPE_SECRET_KEY", "sk_test_x"):
        yield


class TestCheckout:
    def test_creates_customer_once_and_returns_url(self, db, user):
        with patch.object(stripe_client, "create_customer", return_value="cus_1") as customer, \
             patch.object(stripe_client, "create_premium_checkout", return_value="https://stripe/checkout") as checkout:
            assert billing_service.start_checkout(db, user, None) == {"checkout_url": "https://stripe/checkout"}
            billing_service.start_checkout(db, user, None)
        assert customer.call_count == 1
        kwargs = checkout.call_args.kwargs
        assert kwargs["customer_id"] == "cus_1" and kwargs["user_id"] == str(user.id)
        assert kwargs["success_url"].startswith(settings.FRONTEND_URL.rstrip("/") + "/profile?premium=success")

    def test_untrusted_origin_is_ignored(self, db, user):
        with patch.object(stripe_client, "create_customer", return_value="cus_1"), \
             patch.object(stripe_client, "create_premium_checkout", return_value="u") as checkout:
            billing_service.start_checkout(db, user, "https://evil.example")
        assert "evil.example" not in checkout.call_args.kwargs["success_url"]

    def test_without_stripe_key_is_503(self, db, user):
        with patch.object(settings, "STRIPE_SECRET_KEY", ""), pytest.raises(Exception) as err:
            billing_service.start_checkout(db, user, None)
        assert err.value.status_code == 503


class TestLifecycle:
    def test_sync_after_checkout_activates_premium(self, db, user):
        session = {"client_reference_id": str(user.id), "subscription": "sub_1"}
        with patch.object(stripe_client, "get_checkout_session", return_value=session), \
             patch.object(stripe_client, "get_subscription", return_value=sub()):
            status = billing_service.sync(db, user, "cs_1")
        assert status["is_premium"] is True and status["status"] == "active"
        assert db.query(User).one().is_premium is True

    def test_sync_rejects_someone_elses_session(self, db, user):
        session = {"client_reference_id": "another-user", "subscription": "sub_1"}
        with patch.object(stripe_client, "get_checkout_session", return_value=session), pytest.raises(Exception) as err:
            billing_service.sync(db, user, "cs_1")
        assert err.value.status_code == 403 and not user.is_premium

    def _activate(self, db, user):
        with patch.object(stripe_client, "get_subscription", return_value=sub()):
            db.add(Subscription(user_id=user.id, stripe_customer_id="cus_1", stripe_subscription_id="sub_1"))
            db.commit()
            billing_service.handle_subscription_event(db, "sub_1")

    def test_webhook_activates_then_cancels(self, db, user):
        self._activate(db, user)
        assert user.is_premium is True
        with patch.object(stripe_client, "get_subscription", return_value=sub(status="canceled")):
            billing_service.handle_subscription_event(db, "sub_1")
        db.refresh(user)
        assert user.is_premium is False

    def test_cancel_keeps_premium_until_period_end_and_resume_undoes_it(self, db, user):
        self._activate(db, user)
        with patch.object(stripe_client, "set_subscription_cancel", return_value=sub(cancel=True)) as modify:
            status = billing_service.set_cancel(db, user, True)
        assert modify.call_args.args == ("sub_1", True)
        assert status["is_premium"] is True and status["cancel_at_period_end"] is True
        with patch.object(stripe_client, "set_subscription_cancel", return_value=sub(cancel=False)):
            assert billing_service.set_cancel(db, user, False)["cancel_at_period_end"] is False

    def test_status_rechecks_stripe_when_period_lapsed(self, db, user):
        self._activate(db, user)
        record = db.query(Subscription).one()
        record.current_period_end = datetime.utcnow() - timedelta(days=1)
        db.commit()
        with patch.object(stripe_client, "get_subscription", return_value=sub(status="canceled")):
            assert billing_service.get_status(db, user)["is_premium"] is False

    def test_old_cancelled_subscription_does_not_downgrade_a_new_one(self, db, user):
        self._activate(db, user)
        with patch.object(stripe_client, "get_subscription", return_value=sub(status="canceled", sub_id="sub_old")):
            billing_service.handle_subscription_event(db, "sub_old", str(user.id))
        db.refresh(user)
        assert user.is_premium is True

    def test_account_deletion_cancels_billing(self, db, user):
        self._activate(db, user)
        with patch.object(stripe_client, "cancel_subscription", return_value=sub(status="canceled")) as cancel:
            billing_service.cancel_now_for_deleted_user(db, user)
        assert cancel.call_args.args == ("sub_1",) and user.is_premium is False
