"""Tests for authentication endpoints."""
import pytest


class TestRegister:
    def test_register_buyer_success(self, client, buyer_data):
        res = client.post("/api/v1/auth/register", json=buyer_data)
        assert res.status_code == 201
        data = res.json()
        assert data["email"] == buyer_data["email"]
        assert data["role"] == "buyer"
        assert "hashed_password" not in data

    def test_register_seller_success(self, client, seller_data):
        res = client.post("/api/v1/auth/register", json=seller_data)
        assert res.status_code == 201
        assert res.json()["role"] == "seller"

    def test_register_duplicate_email(self, client, buyer_data):
        client.post("/api/v1/auth/register", json=buyer_data)
        res = client.post("/api/v1/auth/register", json=buyer_data)
        assert res.status_code == 409

    def test_register_weak_password(self, client):
        res = client.post("/api/v1/auth/register", json={
            "email": "user@test.com",
            "password": "weak",
            "full_name": "Test User",
        })
        assert res.status_code == 422

    def test_register_password_no_uppercase(self, client):
        res = client.post("/api/v1/auth/register", json={
            "email": "user@test.com",
            "password": "nouppercase1",
            "full_name": "Test User",
        })
        assert res.status_code == 422

    def test_register_invalid_email(self, client):
        res = client.post("/api/v1/auth/register", json={
            "email": "not-an-email",
            "password": "Valid1234",
            "full_name": "Test User",
        })
        assert res.status_code == 422


class TestLogin:
    def test_login_success(self, client, registered_buyer, buyer_data):
        res = client.post("/api/v1/auth/login", data={
            "username": buyer_data["email"],
            "password": buyer_data["password"],
        })
        assert res.status_code == 200
        data = res.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    def test_login_wrong_password(self, client, registered_buyer, buyer_data):
        res = client.post("/api/v1/auth/login", data={
            "username": buyer_data["email"],
            "password": "WrongPassword1",
        })
        assert res.status_code == 401

    def test_login_unknown_email(self, client):
        res = client.post("/api/v1/auth/login", data={
            "username": "ghost@test.com",
            "password": "Valid1234",
        })
        assert res.status_code == 401


class TestProtectedRoutes:
    def test_get_me_authenticated(self, client, auth_buyer, buyer_data):
        res = client.get("/api/v1/auth/me", headers=auth_buyer)
        assert res.status_code == 200
        assert res.json()["email"] == buyer_data["email"]

    def test_get_me_no_token(self, client):
        res = client.get("/api/v1/auth/me")
        assert res.status_code == 401

    def test_get_me_invalid_token(self, client):
        res = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer fake.token.here"})
        assert res.status_code == 401

    def test_refresh_token(self, client, buyer_data, registered_buyer):
        login_res = client.post("/api/v1/auth/login", data={
            "username": buyer_data["email"],
            "password": buyer_data["password"],
        })
        refresh_token = login_res.json()["refresh_token"]
        res = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
        assert res.status_code == 200
        assert "access_token" in res.json()
