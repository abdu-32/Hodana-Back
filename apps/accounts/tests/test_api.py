"""
API / contract-level tests against apps/accounts/urls.py + views.py.

Level, per Document 07 Sec 2's test pyramid: "API / contract -- views.py
and serializers.py via the DRF test client against Document 04's
contract. Verifies HTTP status codes, the shared error envelope (Document
03 Sec 6.5), and authorization behavior (Sec 8) at the boundary a real
client hits." That's the job of this file -- NOT re-proving every
business rule already covered in test_services.py. One happy path + the
contract-relevant error paths per endpoint is the target; exhaustive rule
branches (lockout windows, token math, etc.) stay in test_services.py.

Endpoint <-> contract mapping (Document 04, `Auth`/`Users` tags):
    POST /auth/signup                  -> FR-AUTH-001
    POST /auth/login                   -> FR-AUTH-002
    POST /auth/refresh                 -> FR-AUTH-002 (cont.)
    POST /auth/verify-email            -> FR-AUTH-003
    POST /auth/verify-email/resend     -> FR-AUTH-003
    POST /auth/password-reset          -> FR-AUTH-004
    POST /auth/password-reset/confirm  -> FR-AUTH-004
    GET/PUT /users/me                  -> FR-PROFILE-001
    GET /users/{id}                    -> FR-PROFILE-002

Test IDs in docstrings match Document 07 Sec 6 (TC-AUTH-*, TC-PROFILE-*)
and Sec 7.2 (TC-NFR-SEC-*) where a matching case exists.
"""

import re

import pytest
from rest_framework import status

from apps.accounts import services

pytestmark = pytest.mark.django_db

TOKEN_RE = re.compile(r"token=([^\s]+)")


def _extract_token(email_body):
    match = TOKEN_RE.search(email_body)
    assert match, f"no token= param found in email body: {email_body!r}"
    return match.group(1)


# ---------------------------------------------------------------------------
# POST /auth/signup -- FR-AUTH-001
# ---------------------------------------------------------------------------


class TestSignupEndpoint:
    url = "/api/v1/auth/signup"

    def test_returns_201_with_user_profile_body(self, api_client):
        response = api_client.post(
            self.url,
            {"email": "new.user@example.com", "password": "correct-horse-99", "fullName": "New User"},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        # Contract shape (Document 04 UserProfile) is camelCase, not a raw
        # model dump -- and must never echo the password back.
        assert body["email"] == "new.user@example.com"
        assert body["fullName"] == "New User"
        assert body["verificationStatus"] == "unverified"
        assert "password" not in body
        # Deliberately no accessToken/refreshToken here -- FR-AUTH-001:
        # the account can't log in until FR-AUTH-003 (verify) completes,
        # so signup must not hand back a usable session.
        assert "accessToken" not in body

    def test_TC_AUTH_001a_weak_password_returns_400_validation_envelope(self, api_client):
        response = api_client.post(
            self.url,
            {"email": "weak@example.com", "password": "short1", "fullName": "Weak"},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        # Uniform error envelope, Document 03 Sec 6.5.
        error = response.json()["error"]
        assert error["code"] == "VALIDATION_ERROR"
        assert "password" in error["details"]

    def test_duplicate_email_returns_409_without_revealing_why(self, api_client, verified_account):
        response = api_client.post(
            self.url,
            {"email": verified_account.email.upper(), "password": "correct-horse-99", "fullName": "Someone Else"},
            format="json",
        )

        assert response.status_code == status.HTTP_409_CONFLICT
        message = response.json()["error"]["message"].lower()
        # BR-012: message must not confirm *why* it failed.
        assert "already" not in message
        assert "exist" not in message


# ---------------------------------------------------------------------------
# POST /auth/login -- FR-AUTH-002
# ---------------------------------------------------------------------------


class TestLoginEndpoint:
    url = "/api/v1/auth/login"

    def test_returns_200_with_tokens_and_user(self, api_client, verified_account, raw_password):
        response = api_client.post(
            self.url, {"email": verified_account.email, "password": raw_password}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["accessToken"]
        assert body["refreshToken"]
        assert body["user"]["email"] == verified_account.email

    def test_wrong_password_returns_401_with_generic_message(self, api_client, verified_account):
        response = api_client.post(
            self.url, {"email": verified_account.email, "password": "totally-wrong-99"}, format="json"
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json()["error"]["message"] == services.GENERIC_AUTH_ERROR

    def test_unverified_account_returns_401(self, api_client, unverified_account, raw_password):
        response = api_client.post(
            self.url, {"email": unverified_account.email, "password": raw_password}, format="json"
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_TC_AUTH_002a_account_locks_after_five_failed_attempts(self, api_client, verified_account, raw_password):
        for _ in range(services.LOCKOUT_THRESHOLD):
            response = api_client.post(
                self.url, {"email": verified_account.email, "password": "wrongpass1"}, format="json"
            )
            assert response.status_code == status.HTTP_401_UNAUTHORIZED

        # Even the *correct* password is rejected once locked (contract-
        # level check; the window/reset math itself is test_services.py's job).
        response = api_client.post(
            self.url, {"email": verified_account.email, "password": raw_password}, format="json"
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert "locked" in response.json()["error"]["message"].lower()


# ---------------------------------------------------------------------------
# POST /auth/refresh -- FR-AUTH-002 (cont.)
# ---------------------------------------------------------------------------


class TestRefreshEndpoint:
    url = "/api/v1/auth/refresh"

    def test_valid_refresh_token_returns_new_token_pair(self, api_client, verified_account, raw_password):
        login = api_client.post(
            "/api/v1/auth/login", {"email": verified_account.email, "password": raw_password}, format="json"
        )
        refresh_token = login.json()["refreshToken"]

        response = api_client.post(self.url, {"refreshToken": refresh_token}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["accessToken"]

    def test_garbage_token_returns_401(self, api_client):
        response = api_client.post(self.url, {"refreshToken": "not-a-real-token"}, format="json")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_TC_NFR_SEC_005_refresh_token_from_before_password_reset_is_rejected(
        self, api_client, verified_account, raw_password
    ):
        """NFR-SEC-005: a token_version bump (password reset) must
        invalidate outstanding refresh tokens, verified here at the HTTP
        boundary, not just directly against services.py."""
        login = api_client.post(
            "/api/v1/auth/login", {"email": verified_account.email, "password": raw_password}, format="json"
        )
        old_refresh_token = login.json()["refreshToken"]

        verified_account.token_version += 1
        verified_account.save(update_fields=["token_version"])

        response = api_client.post(self.url, {"refreshToken": old_refresh_token}, format="json")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


# ---------------------------------------------------------------------------
# POST /auth/verify-email, /auth/verify-email/resend -- FR-AUTH-003
# ---------------------------------------------------------------------------


class TestVerifyEmailEndpoint:
    def test_valid_token_verifies_account(self, api_client, mailoutbox):
        api_client.post(
            "/api/v1/auth/signup",
            {"email": "verify.me@example.com", "password": "correct-horse-99", "fullName": "Verify Me"},
            format="json",
        )
        token = _extract_token(mailoutbox[0].body)

        response = api_client.post("/api/v1/auth/verify-email", {"token": token}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["verificationStatus"] == "verified"

    def test_TC_AUTH_003a_invalid_token_returns_400(self, api_client):
        response = api_client.post("/api/v1/auth/verify-email", {"token": "garbage"}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_resend_always_returns_202_regardless_of_email_existing(self, api_client):
        """BR-012-style non-enumeration: same response whether or not the
        email exists (services.py covers the silent-no-op branch)."""
        response = api_client.post(
            "/api/v1/auth/verify-email/resend", {"email": "nobody@example.com"}, format="json"
        )
        assert response.status_code == status.HTTP_202_ACCEPTED


# ---------------------------------------------------------------------------
# POST /auth/password-reset, /auth/password-reset/confirm -- FR-AUTH-004
# ---------------------------------------------------------------------------


class TestPasswordResetEndpoints:
    def test_request_returns_200_with_identical_message_for_known_and_unknown_email(
        self, api_client, verified_account
    ):
        known = api_client.post("/api/v1/auth/password-reset", {"email": verified_account.email}, format="json")
        unknown = api_client.post(
            "/api/v1/auth/password-reset", {"email": "nobody@example.com"}, format="json"
        )

        assert known.status_code == unknown.status_code == status.HTTP_200_OK
        assert known.json()["message"] == unknown.json()["message"] == services.GENERIC_RESET_MESSAGE

    def test_confirm_with_valid_token_changes_password(self, api_client, verified_account, mailoutbox):
        api_client.post("/api/v1/auth/password-reset", {"email": verified_account.email}, format="json")
        token = _extract_token(mailoutbox[0].body)

        response = api_client.post(
            "/api/v1/auth/password-reset/confirm",
            {"token": token, "newPassword": "new-password-9"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK

        # New password actually works end-to-end through the login endpoint.
        login = api_client.post(
            "/api/v1/auth/login",
            {"email": verified_account.email, "password": "new-password-9"},
            format="json",
        )
        assert login.status_code == status.HTTP_200_OK

    def test_confirm_is_single_use(self, api_client, verified_account, mailoutbox):
        api_client.post("/api/v1/auth/password-reset", {"email": verified_account.email}, format="json")
        token = _extract_token(mailoutbox[0].body)

        api_client.post(
            "/api/v1/auth/password-reset/confirm",
            {"token": token, "newPassword": "new-password-9"},
            format="json",
        )
        replay = api_client.post(
            "/api/v1/auth/password-reset/confirm",
            {"token": token, "newPassword": "another-password-9"},
            format="json",
        )
        assert replay.status_code == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# GET/PUT /users/me -- FR-PROFILE-001
# ---------------------------------------------------------------------------


class TestCurrentUserEndpoint:
    url = "/api/v1/users/me"

    def test_requires_authentication(self, api_client):
        response = api_client.get(self.url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_authenticated_get_returns_own_profile(self, api_client, verified_account, auth_headers):
        response = api_client.get(self.url, **auth_headers(verified_account))
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["email"] == verified_account.email

    def test_put_updates_profile_fields(self, api_client, verified_account, auth_headers):
        response = api_client.put(
            self.url,
            {"bio": "Building things for Ethiopian hackathons."},
            format="json",
            **auth_headers(verified_account),
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["bio"] == "Building things for Ethiopian hackathons."

    def test_TC_PROFILE_001a_bio_over_500_chars_returns_400(self, api_client, verified_account, auth_headers):
        response = api_client.put(
            self.url, {"bio": "x" * 501}, format="json", **auth_headers(verified_account)
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_TC_NFR_SEC_005_revoked_session_rejected_even_with_unexpired_access_token(
        self, api_client, verified_account, auth_headers
    ):
        headers = auth_headers(verified_account)  # signs a token at the *current* token_version

        verified_account.token_version += 1
        verified_account.save(update_fields=["token_version"])

        response = api_client.get(self.url, **headers)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


# ---------------------------------------------------------------------------
# GET /users/{id} -- FR-PROFILE-002
# ---------------------------------------------------------------------------


class TestPublicProfileEndpoint:
    def test_reachable_without_auth(self, api_client, verified_account):
        response = api_client.get(f"/api/v1/users/{verified_account.id}")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["id"] == str(verified_account.id)
        assert "email" not in body  # never rendered publicly

    def test_TC_PROFILE_002a_private_profile_returns_404_not_403(self, api_client, private_account):
        """BR-012 enumeration prevention: a private profile must look
        identical (404) to one that doesn't exist at all."""
        response = api_client.get(f"/api/v1/users/{private_account.id}")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_nonexistent_id_returns_404(self, api_client):
        response = api_client.get("/api/v1/users/00000000-0000-0000-0000-000000000000")
        assert response.status_code == status.HTTP_404_NOT_FOUND
