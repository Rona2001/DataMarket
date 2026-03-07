"""Tests for dataset upload, listing and management."""
import pytest
import json


METADATA = json.dumps({
    "title": "French Housing Prices 2024",
    "description": "A dataset of housing prices across major French cities.",
    "price": 29.99,
    "category": "real_estate",
    "tags": ["housing", "france", "prices"],
    "gdpr_compliant": True,
    "contains_pii": False,
    "license_type": "CC BY 4.0",
})

FREE_METADATA = json.dumps({
    "title": "Free Sample Dataset",
    "description": "A free dataset for testing.",
    "price": 0,
    "gdpr_compliant": True,
    "contains_pii": False,
})


class TestDatasetUpload:
    def test_upload_csv_success(self, client, auth_seller, sample_csv_bytes, mock_storage):
        res = client.post(
            "/api/v1/datasets",
            headers=auth_seller,
            files={"file": ("housing.csv", sample_csv_bytes, "text/csv")},
            data={"metadata": METADATA},
        )
        assert res.status_code == 201
        data = res.json()
        assert data["title"] == "French Housing Prices 2024"
        assert data["status"] == "draft"
        assert data["price"] == 29.99
        assert data["num_rows"] == 3
        assert data["num_columns"] == 5
        assert data["checksum"] is not None

    def test_upload_requires_seller_role(self, client, auth_buyer, sample_csv_bytes, mock_storage):
        res = client.post(
            "/api/v1/datasets",
            headers=auth_buyer,
            files={"file": ("data.csv", sample_csv_bytes, "text/csv")},
            data={"metadata": METADATA},
        )
        assert res.status_code == 403

    def test_upload_requires_auth(self, client, sample_csv_bytes):
        res = client.post(
            "/api/v1/datasets",
            files={"file": ("data.csv", sample_csv_bytes, "text/csv")},
            data={"metadata": METADATA},
        )
        assert res.status_code == 401

    def test_upload_duplicate_rejected(self, client, auth_seller, sample_csv_bytes, mock_storage):
        client.post(
            "/api/v1/datasets",
            headers=auth_seller,
            files={"file": ("data.csv", sample_csv_bytes, "text/csv")},
            data={"metadata": METADATA},
        )
        res = client.post(
            "/api/v1/datasets",
            headers=auth_seller,
            files={"file": ("data.csv", sample_csv_bytes, "text/csv")},
            data={"metadata": METADATA},
        )
        assert res.status_code == 409

    def test_upload_invalid_extension(self, client, auth_seller, mock_storage):
        res = client.post(
            "/api/v1/datasets",
            headers=auth_seller,
            files={"file": ("script.exe", b"malicious", "application/octet-stream")},
            data={"metadata": METADATA},
        )
        assert res.status_code == 422

    def test_upload_invalid_metadata(self, client, auth_seller, sample_csv_bytes, mock_storage):
        res = client.post(
            "/api/v1/datasets",
            headers=auth_seller,
            files={"file": ("data.csv", sample_csv_bytes, "text/csv")},
            data={"metadata": '{"price": -5}'},  # missing required fields + negative price
        )
        assert res.status_code in (400, 422)


class TestDatasetPublish:
    def _upload(self, client, auth_seller, sample_csv_bytes, mock_storage, meta=None):
        res = client.post(
            "/api/v1/datasets",
            headers=auth_seller,
            files={"file": ("data.csv", sample_csv_bytes, "text/csv")},
            data={"metadata": meta or METADATA},
        )
        assert res.status_code == 201
        return res.json()["id"]

    def test_publish_success(self, client, auth_seller, sample_csv_bytes, mock_storage):
        dataset_id = self._upload(client, auth_seller, sample_csv_bytes, mock_storage)
        res = client.post(f"/api/v1/datasets/{dataset_id}/publish", headers=auth_seller)
        assert res.status_code == 200
        assert res.json()["status"] == "published"

    def test_publish_wrong_owner(self, client, auth_seller, auth_buyer, sample_csv_bytes, mock_storage):
        dataset_id = self._upload(client, auth_seller, sample_csv_bytes, mock_storage)
        res = client.post(f"/api/v1/datasets/{dataset_id}/publish", headers=auth_buyer)
        assert res.status_code == 403

    def test_unpublish(self, client, auth_seller, sample_csv_bytes, mock_storage):
        dataset_id = self._upload(client, auth_seller, sample_csv_bytes, mock_storage)
        client.post(f"/api/v1/datasets/{dataset_id}/publish", headers=auth_seller)
        res = client.post(f"/api/v1/datasets/{dataset_id}/unpublish", headers=auth_seller)
        assert res.status_code == 200
        assert res.json()["status"] == "draft"


class TestDatasetBrowse:
    def test_browse_returns_only_published(self, client, auth_seller, sample_csv_bytes, mock_storage):
        # Upload but don't publish
        client.post(
            "/api/v1/datasets",
            headers=auth_seller,
            files={"file": ("data.csv", sample_csv_bytes, "text/csv")},
            data={"metadata": METADATA},
        )
        res = client.get("/api/v1/datasets")
        assert res.status_code == 200
        assert res.json()["total"] == 0

    def test_browse_shows_published(self, client, auth_seller, sample_csv_bytes, mock_storage):
        upload_res = client.post(
            "/api/v1/datasets",
            headers=auth_seller,
            files={"file": ("data.csv", sample_csv_bytes, "text/csv")},
            data={"metadata": METADATA},
        )
        dataset_id = upload_res.json()["id"]
        client.post(f"/api/v1/datasets/{dataset_id}/publish", headers=auth_seller)

        res = client.get("/api/v1/datasets")
        assert res.status_code == 200
        assert res.json()["total"] == 1

    def test_browse_search_filter(self, client, auth_seller, sample_csv_bytes, mock_storage):
        upload_res = client.post(
            "/api/v1/datasets",
            headers=auth_seller,
            files={"file": ("data.csv", sample_csv_bytes, "text/csv")},
            data={"metadata": METADATA},
        )
        dataset_id = upload_res.json()["id"]
        client.post(f"/api/v1/datasets/{dataset_id}/publish", headers=auth_seller)

        res = client.get("/api/v1/datasets?search=Housing")
        assert res.json()["total"] == 1

        res = client.get("/api/v1/datasets?search=unrelated_xyz")
        assert res.json()["total"] == 0

    def test_my_datasets(self, client, auth_seller, sample_csv_bytes, mock_storage):
        client.post(
            "/api/v1/datasets",
            headers=auth_seller,
            files={"file": ("data.csv", sample_csv_bytes, "text/csv")},
            data={"metadata": METADATA},
        )
        res = client.get("/api/v1/datasets/mine/list", headers=auth_seller)
        assert res.status_code == 200
        assert len(res.json()) == 1
