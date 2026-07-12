import pytest

def test_register_doctor(client):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "test@example.com", "full_name": "Test Doctor", "password": "securepassword"}
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "test@example.com"
    assert data["full_name"] == "Test Doctor"
    assert "id" in data
    assert "hashed_password" not in data
    assert "password" not in data

def test_register_duplicate_doctor(client):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "dup@example.com", "full_name": "Dup Doctor", "password": "pwd"}
    )
    assert response.status_code == 201
    
    # Try again
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "dup@example.com", "full_name": "Dup Doctor", "password": "pwd"}
    )
    assert response.status_code == 400

def test_login_doctor(client):
    client.post(
        "/api/v1/auth/register",
        json={"email": "login@example.com", "full_name": "Login Doctor", "password": "loginpwd"}
    )
    
    response = client.post(
        "/api/v1/auth/login",
        data={"username": "login@example.com", "password": "loginpwd"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"

def test_login_invalid_password(client):
    client.post(
        "/api/v1/auth/register",
        json={"email": "badpwd@example.com", "full_name": "Bad Pwd", "password": "good"}
    )
    
    response = client.post(
        "/api/v1/auth/login",
        data={"username": "badpwd@example.com", "password": "wrong"}
    )
    assert response.status_code == 401

def test_read_users_me(client):
    client.post(
        "/api/v1/auth/register",
        json={"email": "me@example.com", "full_name": "Me Doctor", "password": "mepwd"}
    )
    login_resp = client.post(
        "/api/v1/auth/login",
        data={"username": "me@example.com", "password": "mepwd"}
    )
    token = login_resp.json()["access_token"]
    
    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json()["email"] == "me@example.com"

def test_read_users_me_unauthorized(client):
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
