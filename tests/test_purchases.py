"""Tests for purchase, escrow and download flow."""
import pytest
import json


FREE_METADATA = json.dumps({
    "title": "Free Open Dataset",
    "description": "Completely free dataset for public use.",
    "price": 0,
    "gdpr_compliant": True,
    "contains_pii": False,
})

PAID_METADATA = json.dumps({
    "title": "Premium Analytics Dataset",
    "description": "High quality analytics data.",
    "price": 49.99,
    "gdpr_compliant": True,
    "contains_pii": False,
})


def upload_and_publish(client, auth_seller, sample_csv_bytes, mock_storage, meta=None):
    """Helper: upload + publish a dataset, return its ID."""
    upload_res = client.post(
        "/api/v1/datasets",
        headers=auth_seller,
        files={"file": ("data.csv", sample_csv_bytes, "text/csv")},
        data={"metadata": meta or FREE_METADATA},
    )
    assert upload_res.status_code == 201
    dataset_id = upload_res.json()["id"]
    publish_res = client.post(
        f"/api/v1/datasets/{dataset_id}/publish",
        headers=auth_seller,
    )
    assert publish_res.status_code == 200
    return dataset_id


class TestFreePurchase:
    def test_free_dataset_instant_download(
        self, client, auth_buyer, auth_seller, sample_csv_bytes, mock_storage
    ):
        dataset_id = upload_and_publish(client, auth_seller, sample_csv_bytes, mock_storage)

        res = client.post("/api/v1/purchases", json={"dataset_id": dataset_id}, headers=auth_buyer)
        assert res.status_code == 201
        data = res.json()
        assert data["is_free"] is True
        assert "signed_url" in data

    def test_cannot_purchase_own_dataset(
        self, client, auth_seller, sample_csv_bytes, mock_storage
    ):
        dataset_id = upload_and_publish(client, auth_seller, sample_csv_bytes, mock_storage)
        res = client.post(
            "/api/v1/purchases",
            json={"dataset_id": dataset_id},
            headers=auth_seller,
        )
        assert res.status_code == 400

    def test_cannot_buy_same_dataset_twice(
        self, client, auth_buyer, auth_seller, sample_csv_bytes, mock_storage
    ):
        dataset_id = upload_and_publish(client, auth_seller, sample_csv_bytes, mock_storage)
        client.post("/api/v1/purchases", json={"dataset_id": dataset_id}, headers=auth_buyer)
        res = client.post(
            "/api/v1/purchases", json={"dataset_id": dataset_id}, headers=auth_buyer
        )
        assert res.status_code == 409

    def test_cannot_buy_unpublished_dataset(
        self, client, auth_buyer, auth_seller, sample_csv_bytes, mock_storage
    ):
        upload_res = client.post(
            "/api/v1/datasets",
            headers=auth_seller,
            files={"file": ("data.csv", sample_csv_bytes, "text/csv")},
            data={"metadata": FREE_METADATA},
        )
        dataset_id = upload_res.json()["id"]
        res = client.post(
            "/api/v1/purchases", json={"dataset_id": dataset_id}, headers=auth_buyer
        )
        assert res.status_code == 400


class TestPurchaseHistory:
    def test_my_purchases_empty(self, client, auth_buyer):
        res = client.get("/api/v1/purchases", headers=auth_buyer)
        assert res.status_code == 200
        assert res.json() == []

    def test_my_purchases_after_buy(
        self, client, auth_buyer, auth_seller, sample_csv_bytes, mock_storage
    ):
        dataset_id = upload_and_publish(client, auth_seller, sample_csv_bytes, mock_storage)
        client.post("/api/v1/purchases", json={"dataset_id": dataset_id}, headers=auth_buyer)
        res = client.get("/api/v1/purchases", headers=auth_buyer)
        assert res.status_code == 200
        assert len(res.json()) == 1
        assert res.json()[0]["status"] == "completed"


class TestDownload:
    def test_download_after_free_purchase(
        self, client, auth_buyer, auth_seller, sample_csv_bytes, mock_storage
    ):
        dataset_id = upload_and_publish(client, auth_seller, sample_csv_bytes, mock_storage)
        purchase_res = client.post(
            "/api/v1/purchases", json={"dataset_id": dataset_id}, headers=auth_buyer
        )
        purchase_id = purchase_res.json()["purchase_id"]

        res = client.get(f"/api/v1/purchases/{purchase_id}/download", headers=auth_buyer)
        assert res.status_code == 200
        data = res.json()
        assert "signed_url" in data
        assert data["expires_in_seconds"] > 0

    def test_download_requires_auth(self, client):
        res = client.get("/api/v1/purchases/fake-id/download")
        assert res.status_code == 401

    def test_download_wrong_user(
        self, client, auth_buyer, auth_seller, sample_csv_bytes, mock_storage, client_b=None
    ):
        dataset_id = upload_and_publish(client, auth_seller, sample_csv_bytes, mock_storage)
        purchase_res = client.post(
            "/api/v1/purchases", json={"dataset_id": dataset_id}, headers=auth_buyer
        )
        purchase_id = purchase_res.json()["purchase_id"]

        # Seller tries to access buyer's purchase
        res = client.get(
            f"/api/v1/purchases/{purchase_id}/download", headers=auth_seller
        )
        assert res.status_code == 403


class TestReview:
    def test_leave_review(
        self, client, auth_buyer, auth_seller, sample_csv_bytes, mock_storage
    ):
        dataset_id = upload_and_publish(client, auth_seller, sample_csv_bytes, mock_storage)
        purchase_res = client.post(
            "/api/v1/purchases", json={"dataset_id": dataset_id}, headers=auth_buyer
        )
        purchase_id = purchase_res.json()["purchase_id"]

        res = client.post(
            f"/api/v1/purchases/{purchase_id}/review",
            json={"rating": 4.5, "review": "Very useful dataset!"},
            headers=auth_buyer,
        )
        assert res.status_code == 200
        assert res.json()["rating"] == 4.5

    def test_cannot_review_twice(
        self, client, auth_buyer, auth_seller, sample_csv_bytes, mock_storage
    ):
        dataset_id = upload_and_publish(client, auth_seller, sample_csv_bytes, mock_storage)
        purchase_res = client.post(
            "/api/v1/purchases", json={"dataset_id": dataset_id}, headers=auth_buyer
        )
        purchase_id = purchase_res.json()["purchase_id"]

        client.post(
            f"/api/v1/purchases/{purchase_id}/review",
            json={"rating": 5.0},
            headers=auth_buyer,
        )
        res = client.post(
            f"/api/v1/purchases/{purchase_id}/review",
            json={"rating": 1.0},
            headers=auth_buyer,
        )
        assert res.status_code == 400
