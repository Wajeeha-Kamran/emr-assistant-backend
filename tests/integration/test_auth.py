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
        json={"email": "dup@example.com", "full_name": "Dup Doctor", "password": "testpassword"}
    )
    assert response.status_code == 201
    
    # Try again
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "dup@example.com", "full_name": "Dup Doctor", "password": "testpassword"}
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
        json={"email": "badpwd@example.com", "full_name": "Bad Pwd", "password": "goodpassword"}
    )
    
    response = client.post(
        "/api/v1/auth/login",
        data={"username": "badpwd@example.com", "password": "wrong"}
    )
    assert response.status_code == 401

def test_read_users_me(client):
    client.post(
        "/api/v1/auth/register",
        json={"email": "me@example.com", "full_name": "Me Doctor", "password": "mepassword"}
    )
    login_resp = client.post(
        "/api/v1/auth/login",
        data={"username": "me@example.com", "password": "mepassword"}
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


# ---------------------------------------------------------------------------
# Registration input validation
#
# Added 16 Aug 2026. Before this the endpoint accepted any string as an email
# and any string as a password, including a single character, while the mobile
# registration screen told the user it required eight. The rule now lives on
# the server, which is the only place it can actually be enforced.
# ---------------------------------------------------------------------------

def test_register_rejects_a_short_password(client):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "short@example.com", "full_name": "Short Pwd", "password": "abc123"}
    )
    assert response.status_code == 422

    # And no account was created, so the email is still free.
    retry = client.post(
        "/api/v1/auth/register",
        json={"email": "short@example.com", "full_name": "Short Pwd", "password": "longenough1"}
    )
    assert retry.status_code == 201


@pytest.mark.parametrize("bad_email", ["notanemail", "no@domain", "@example.com", "spaces in@example.com", ""])
def test_register_rejects_a_malformed_email(client, bad_email):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": bad_email, "full_name": "Bad Email", "password": "longenough1"}
    )
    assert response.status_code == 422


def test_register_rejects_a_blank_name(client):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "noname@example.com", "full_name": "   ", "password": "longenough1"}
    )
    assert response.status_code == 422


def test_register_trims_surrounding_whitespace(client):
    """
    A pasted address with a trailing space would otherwise be stored verbatim,
    and the account could never be logged into: the login lookup is an exact
    match on the email column.
    """
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "  trimmed@example.com  ", "full_name": "  Trimmed Doctor  ", "password": "longenough1"}
    )
    assert response.status_code == 201
    assert response.json()["email"] == "trimmed@example.com"
    assert response.json()["full_name"] == "Trimmed Doctor"

    login = client.post(
        "/api/v1/auth/login",
        data={"username": "trimmed@example.com", "password": "longenough1"}
    )
    assert login.status_code == 200


def test_login_does_not_apply_the_registration_password_rule(client):
    """
    The length rule governs new accounts, not sign-in.

    Applying it at login would lock out every account created before the rule
    existed, and would tell an attacker the password policy from the error code
    alone. A short password at login is simply wrong, not malformed: 401, not
    422.
    """
    response = client.post(
        "/api/v1/auth/login",
        data={"username": "nobody@example.com", "password": "abc"}
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Email is an identifier, not a delivery route
#
# Added 16 Aug 2026. The unique index on doctors.email is case-sensitive, as
# PostgreSQL indexes are, and the duplicate check was an exact match. One
# person could therefore hold two accounts differing only by capitalisation,
# with the consultations recorded under each invisible from the other.
# ---------------------------------------------------------------------------

def test_register_normalises_email_case(client):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "MixedCase@Example.COM", "full_name": "Mixed Case", "password": "longenough1"}
    )
    assert response.status_code == 201
    assert response.json()["email"] == "mixedcase@example.com"


def test_register_rejects_an_email_differing_only_by_case(client):
    first = client.post(
        "/api/v1/auth/register",
        json={"email": "duplicate@example.com", "full_name": "First", "password": "longenough1"}
    )
    assert first.status_code == 201

    second = client.post(
        "/api/v1/auth/register",
        json={"email": "Duplicate@Example.com", "full_name": "Second", "password": "longenough1"}
    )
    assert second.status_code == 400


def test_login_ignores_email_case_and_whitespace(client):
    client.post(
        "/api/v1/auth/register",
        json={"email": "casey@example.com", "full_name": "Casey Doctor", "password": "longenough1"}
    )

    response = client.post(
        "/api/v1/auth/login",
        data={"username": "  CASEY@Example.Com  ", "password": "longenough1"}
    )
    assert response.status_code == 200
    assert "access_token" in response.json()


def test_token_from_a_differently_cased_login_identifies_the_same_doctor(client):
    """
    The token's subject is the email as typed. If /me resolved it with an exact
    match, signing in with different capitalisation would produce a token that
    authenticates and then fails on every protected route.
    """
    client.post(
        "/api/v1/auth/register",
        json={"email": "samedoctor@example.com", "full_name": "Same Doctor", "password": "longenough1"}
    )

    login = client.post(
        "/api/v1/auth/login",
        data={"username": "SameDoctor@Example.com", "password": "longenough1"}
    )
    token = login.json()["access_token"]

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "samedoctor@example.com"


def test_database_refuses_two_accounts_differing_only_by_case():
    """
    The constraint, not the check in front of it.

    Every other test here goes through /register, which compares
    case-insensitively before inserting. This one inserts directly, so it
    asserts that the database itself would refuse the duplicate.

    Worth testing separately because the application check and the constraint
    can drift apart. Add a second path that creates a doctor — a seeding
    script, an admin tool, a fixture — and forget the lowercase comparison, and
    every other test in this file still passes. This one does not.
    """
    from sqlalchemy.exc import IntegrityError

    from app.db.session import SessionLocal
    from app.models.doctor import Doctor

    db = SessionLocal()
    try:
        db.add(Doctor(
            email="constraint@example.com",
            hashed_password="not-a-real-hash",
            full_name="First Account",
        ))
        db.commit()

        db.add(Doctor(
            email="Constraint@Example.com",
            hashed_password="not-a-real-hash",
            full_name="Second Account",
        ))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    finally:
        db.close()
