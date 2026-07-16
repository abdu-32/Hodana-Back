"""
Unit tests against accounts/services.py directly (Design Spec Sec 3.1),
per the 80% coverage target in NFR-MAINT-001. Prefer these over
HTTP-level tests for business-rule coverage.

Test IDs in each docstring/comment match Document 07 Sec 6's named cases
(TC-AUTH-*, TC-PROFILE-*) where one exists; additional cases beyond that
representative list are included for branch coverage of services.py.
"""

import re
import uuid

import pytest
from freezegun import freeze_time
from django.core import mail
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed, NotFound, ValidationError

from apps.accounts import services
from apps.core.models import AuditLogEntry

TOKEN_RE = re.compile(r"token=([^\s]+)")


def _extract_token(email_body):
    match = TOKEN_RE.search(email_body)
    assert match, f"no token= param found in email body: {email_body!r}"
    return match.group(1)


# ---------------------------------------------------------------------------
# FR-AUTH-001: registration
# ---------------------------------------------------------------------------


class TestRegisterAccount:
    def test_creates_unverified_account_and_sends_verification_email(self, mailoutbox):
        account = services.register_account(
            email="New.User@Example.com", password="correct-horse-99", full_name="New User"
        )

        assert account.verification_status == "unverified"
        assert account.email == "new.user@example.com"  # normalized/lowercased
        assert len(mailoutbox) == 1
        assert "verify" in mailoutbox[0].subject.lower()
        assert AuditLogEntry.objects.filter(
            action="account.registered", target_id=str(account.id)
        ).exists()

    @pytest.mark.parametrize(
        "password",
        [
            "short1a",  # custom: fewer than 10 characters
            "noDigitsHereAtAll",  # custom: no digit
            "1234567890",  # custom: no letter; also numeric-only
            "password123",  # Django: common password
        ],
    )
    def test_TC_AUTH_001a_rejects_weak_password(self, password):
        with pytest.raises(ValidationError):
            services.register_account(
                email="weak@example.com",
                password=password,
                full_name="Weak",
            )

    def test_duplicate_email_returns_conflict_without_revealing_existing_account(self, verified_account):
        with pytest.raises(services.ConflictError) as exc_info:
            services.register_account(
                email=verified_account.email.upper(),  # case-insensitive duplicate
                password="correct-horse-99",
                full_name="Someone Else",
            )
        # BR-012: message must not confirm *why* it failed.
        assert "already" not in str(exc_info.value.detail).lower()
        assert "exist" not in str(exc_info.value.detail).lower()


# ---------------------------------------------------------------------------
# FR-AUTH-003: email verification
# ---------------------------------------------------------------------------


class TestEmailVerification:
    def test_valid_token_transitions_account_to_verified(self, unverified_account, mailoutbox):
        token = services.send_verification_email(unverified_account)
        mailoutbox.clear()

        account = services.verify_email(token=token)

        assert account.verification_status == "verified"
        assert account.email_verified_at is not None

    def test_verifying_an_already_verified_account_is_a_no_op(self, verified_account):
        token = services.send_verification_email(verified_account)
        account = services.verify_email(token=token)
        assert account.verification_status == "verified"

    def test_TC_AUTH_003a_expired_link_is_rejected(self, unverified_account):
        with freeze_time("2026-01-01 00:00:00"):
            token = services.send_verification_email(unverified_account)

        with freeze_time("2026-01-02 00:00:01"):  # 24h + 1s later
            with pytest.raises(ValidationError):
                services.verify_email(token=token)

    def test_link_just_under_24h_still_valid(self, unverified_account):
        with freeze_time("2026-01-01 00:00:00"):
            token = services.send_verification_email(unverified_account)

        with freeze_time("2026-01-01 23:59:00"):
            account = services.verify_email(token=token)
        assert account.verification_status == "verified"

    def test_tampered_token_is_rejected(self, unverified_account):
        token = services.send_verification_email(unverified_account)
        with pytest.raises(ValidationError):
            services.verify_email(token=token + "tampered")

    def test_resend_sends_new_email_for_unverified_account(self, unverified_account, mailoutbox):
        services.resend_verification_email(email=unverified_account.email)
        assert len(mailoutbox) == 1

    def test_resend_is_silent_no_op_for_unknown_email(self, mailoutbox):
        services.resend_verification_email(email="nobody@example.com")
        assert len(mailoutbox) == 0

    def test_resend_is_silent_no_op_for_already_verified_account(self, verified_account, mailoutbox):
        services.resend_verification_email(email=verified_account.email)
        assert len(mailoutbox) == 0


# ---------------------------------------------------------------------------
# FR-AUTH-002: login
# ---------------------------------------------------------------------------


class TestAuthenticateAndIssueTokens:
    def test_successful_login_returns_tokens_and_updates_last_login(self, verified_account, raw_password):
        account, tokens = services.authenticate_and_issue_tokens(
            email=verified_account.email, password=raw_password
        )
        assert set(tokens) == {"access", "refresh"}
        assert account.last_login_at is not None
        assert account.failed_login_count == 0

    def test_unknown_email_and_wrong_password_return_identical_generic_error(
        self, verified_account, raw_password
    ):
        with pytest.raises(AuthenticationFailed) as unknown_exc:
            services.authenticate_and_issue_tokens(email="nobody@example.com", password="whatever123")

        with pytest.raises(AuthenticationFailed) as wrong_pw_exc:
            services.authenticate_and_issue_tokens(email=verified_account.email, password="wrongpass1")

        assert str(unknown_exc.value.detail) == str(wrong_pw_exc.value.detail) == services.GENERIC_AUTH_ERROR

    def test_unverified_account_cannot_log_in(self, unverified_account, raw_password):
        with pytest.raises(AuthenticationFailed):
            services.authenticate_and_issue_tokens(email=unverified_account.email, password=raw_password)

    def test_suspended_account_cannot_log_in(self, verified_account, raw_password):
        verified_account.is_suspended = True
        verified_account.save(update_fields=["is_suspended"])
        with pytest.raises(AuthenticationFailed):
            services.authenticate_and_issue_tokens(email=verified_account.email, password=raw_password)

    def test_TC_AUTH_002a_locks_account_after_five_failed_attempts(
        self, verified_account, raw_password, mailoutbox
    ):
        for _ in range(services.LOCKOUT_THRESHOLD):
            with pytest.raises(AuthenticationFailed):
                services.authenticate_and_issue_tokens(email=verified_account.email, password="wrongpass1")

        # Even the *correct* password is now rejected while locked.
        with pytest.raises(AuthenticationFailed) as exc_info:
            services.authenticate_and_issue_tokens(email=verified_account.email, password=raw_password)
        assert "locked" in str(exc_info.value.detail).lower()

        assert any("locked" in m.subject.lower() for m in mailoutbox)

    def test_failed_attempt_count_resets_after_lockout_window_passes(self, verified_account):
        with freeze_time("2026-01-01 00:00:00"):
            for _ in range(services.LOCKOUT_THRESHOLD - 1):
                with pytest.raises(AuthenticationFailed):
                    services.authenticate_and_issue_tokens(
                        email=verified_account.email, password="wrongpass1"
                    )

        # Well outside the 15-minute window -- count should reset rather
        # than accumulate into a lockout on this next single failure.
        with freeze_time("2026-01-01 01:00:00"):
            with pytest.raises(AuthenticationFailed) as exc_info:
                services.authenticate_and_issue_tokens(email=verified_account.email, password="wrongpass1")
            assert "locked" not in str(exc_info.value.detail).lower()


# ---------------------------------------------------------------------------
# FR-AUTH-002 (continued): refresh
# ---------------------------------------------------------------------------


class TestRefreshAccessToken:
    def test_valid_refresh_token_returns_new_token_pair(self, verified_account, raw_password):
        _, tokens = services.authenticate_and_issue_tokens(
            email=verified_account.email, password=raw_password
        )
        account, new_tokens = services.refresh_access_token(refresh_token=tokens["refresh"])
        assert account.id == verified_account.id
        assert set(new_tokens) == {"access", "refresh"}

    def test_garbage_token_is_rejected(self):
        with pytest.raises(AuthenticationFailed):
            services.refresh_access_token(refresh_token="not-a-real-token")

    def test_refresh_token_from_before_a_password_reset_is_rejected(self, verified_account, raw_password):
        """NFR-SEC-005: token_version bump must invalidate outstanding
        refresh tokens, not just newly-issued access tokens."""
        _, tokens = services.authenticate_and_issue_tokens(
            email=verified_account.email, password=raw_password
        )
        verified_account.token_version += 1
        verified_account.save(update_fields=["token_version"])

        with pytest.raises(AuthenticationFailed):
            services.refresh_access_token(refresh_token=tokens["refresh"])


# ---------------------------------------------------------------------------
# FR-AUTH-004: password reset
# ---------------------------------------------------------------------------


class TestPasswordReset:
    def test_request_reset_returns_identical_message_for_known_and_unknown_email(self, verified_account):
        known_message = services.request_password_reset(email=verified_account.email)
        unknown_message = services.request_password_reset(email="nobody@example.com")
        assert known_message == unknown_message == services.GENERIC_RESET_MESSAGE

    def test_request_reset_only_emails_known_accounts(self, verified_account, mailoutbox):
        services.request_password_reset(email="nobody@example.com")
        assert len(mailoutbox) == 0

        services.request_password_reset(email=verified_account.email)
        assert len(mailoutbox) == 1

    def test_successful_reset_changes_password_and_new_password_logs_in(self, verified_account, mailoutbox):
        services.request_password_reset(email=verified_account.email)
        token = _extract_token(mailoutbox[0].body)

        services.reset_password(token=token, new_password="new-password-9")

        account, _ = services.authenticate_and_issue_tokens(
            email=verified_account.email, password="new-password-9"
        )
        assert account.id == verified_account.id

    def test_TC_AUTH_004a_reset_invalidates_all_existing_sessions(
        self, verified_account, raw_password, mailoutbox
    ):
        _, old_tokens = services.authenticate_and_issue_tokens(
            email=verified_account.email, password=raw_password
        )

        services.request_password_reset(email=verified_account.email)
        token = _extract_token(mailoutbox[0].body)
        services.reset_password(token=token, new_password="new-password-9")

        with pytest.raises(AuthenticationFailed):
            services.refresh_access_token(refresh_token=old_tokens["refresh"])

    def test_reset_link_expires_after_one_hour(self, verified_account):
        with freeze_time("2026-01-01 00:00:00"):
            services.request_password_reset(email=verified_account.email)
            token = _extract_token(mail.outbox[0].body)

        with freeze_time("2026-01-01 01:00:01"):
            with pytest.raises(ValidationError):
                services.reset_password(token=token, new_password="new-password-9")

    def test_reset_link_is_single_use(self, verified_account, mailoutbox):
        services.request_password_reset(email=verified_account.email)
        token = _extract_token(mailoutbox[0].body)

        services.reset_password(token=token, new_password="new-password-9")

        with pytest.raises(ValidationError):
            services.reset_password(token=token, new_password="another-password-9")

    def test_reset_rejects_weak_new_password(self, verified_account, mailoutbox):
        services.request_password_reset(email=verified_account.email)
        token = _extract_token(mailoutbox[0].body)

        with pytest.raises(ValidationError):
            services.reset_password(token=token, new_password="short1")

    def test_reset_clears_any_active_lockout(self, verified_account, mailoutbox):
        for _ in range(services.LOCKOUT_THRESHOLD):
            with pytest.raises(AuthenticationFailed):
                services.authenticate_and_issue_tokens(email=verified_account.email, password="wrongpass1")
        verified_account.refresh_from_db()
        assert verified_account.lock_until is not None

        services.request_password_reset(email=verified_account.email)
        token = _extract_token(mailoutbox[-1].body)
        services.reset_password(token=token, new_password="new-password-9")

        verified_account.refresh_from_db()
        assert verified_account.lock_until is None
        assert verified_account.failed_login_count == 0


# ---------------------------------------------------------------------------
# FR-PROFILE-001: update own profile
# ---------------------------------------------------------------------------


class TestUpdateProfile:
    def test_updates_only_provided_fields(self, verified_account):
        original_bio = verified_account.bio
        services.update_profile(account=verified_account, data={"full_name": "Updated Name"})

        verified_account.refresh_from_db()
        assert verified_account.full_name == "Updated Name"
        assert verified_account.bio == original_bio

    def test_ignores_fields_outside_the_allowed_set(self, verified_account):
        services.update_profile(account=verified_account, data={"is_platform_admin": True, "bio": "hi"})
        verified_account.refresh_from_db()
        assert verified_account.is_platform_admin is False

    def test_no_fields_provided_does_not_touch_the_row(self, verified_account):
        account = services.update_profile(account=verified_account, data={})
        assert account.id == verified_account.id


# ---------------------------------------------------------------------------
# FR-PROFILE-002: public profile
# ---------------------------------------------------------------------------


class TestGetPublicProfile:
    def test_returns_account_for_public_profile(self, verified_account):
        account = services.get_public_profile(account_id=verified_account.id)
        assert account.id == verified_account.id

    def test_TC_PROFILE_002a_private_profile_raises_not_found_not_forbidden(self, private_account):
        with pytest.raises(NotFound):
            services.get_public_profile(account_id=private_account.id)

    def test_nonexistent_id_raises_not_found(self):
        with pytest.raises(NotFound):
            services.get_public_profile(account_id=uuid.uuid4())

    def test_malformed_id_raises_not_found_not_a_500(self):
        with pytest.raises(NotFound):
            services.get_public_profile(account_id="not-a-uuid")

    def test_soft_deleted_account_raises_not_found(self, verified_account):
        verified_account.deleted_at = timezone.now()
        verified_account.save(update_fields=["deleted_at"])

        with pytest.raises(NotFound):
            services.get_public_profile(account_id=verified_account.id)