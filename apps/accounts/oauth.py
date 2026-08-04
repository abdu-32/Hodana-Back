"""
accounts -- OAuth provider adapters (FR-AUTH-005: sign in with GitHub or
Google).

Per Design Spec Sec 3.1, this stays a thin adapter layer: each function
takes an authorization `code` + the `redirect_uri` the frontend used to
obtain it, exchanges it server-side for the provider's own access token
(the client secret never leaves the backend/never touches the frontend),
and returns a normalized profile dict:

    {"subject", "email", "email_verified", "full_name", "avatar_url"}

`email_verified` matters downstream: services.oauth_login only
auto-links/creates an account off an OAuth email when the provider itself
vouches the address is verified. An unverified provider-reported email is
not proof of ownership -- trusting it would let someone take over (or
silently register against) another person's inbox just by typing it into
their GitHub/Google profile settings.
"""

import requests
from django.conf import settings
from rest_framework.exceptions import ValidationError

OAUTH_HTTP_TIMEOUT = 10  # seconds -- never block a request thread indefinitely on a third party


class OAuthProviderError(ValidationError):
    """Wraps any failure talking to the provider (bad/expired code, network
    error, provider outage, malformed response) as a single user-facing
    validation error -- callers don't need to distinguish those cases at
    the HTTP layer, and none of the underlying detail is safe to relay
    verbatim to the client."""

    def __init__(self, detail="Could not complete sign-in with this provider. Please try again."):
        super().__init__({"code": detail})


def _provider_config(provider):
    config = settings.OAUTH_PROVIDERS.get(provider)
    if not config or not config.get("client_id") or not config.get("client_secret"):
        raise OAuthProviderError(f"{provider} sign-in is not configured on this server.")
    return config


def _exchange_github_code(*, code, redirect_uri):
    config = _provider_config("github")
    try:
        token_response = requests.post(
            config["token_url"],
            data={
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
                "code": code,
                "redirect_uri": redirect_uri,
            },
            headers={"Accept": "application/json"},
            timeout=OAUTH_HTTP_TIMEOUT,
        )
        token_response.raise_for_status()
        access_token = token_response.json().get("access_token")
        if not access_token:
            raise OAuthProviderError()

        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
        user_response = requests.get(config["user_url"], headers=headers, timeout=OAUTH_HTTP_TIMEOUT)
        user_response.raise_for_status()
        user = user_response.json()

        # GitHub's /user endpoint often omits `email` (private-by-default
        # setting) -- /user/emails is the reliable source for the verified
        # primary address.
        emails_response = requests.get(config["emails_url"], headers=headers, timeout=OAUTH_HTTP_TIMEOUT)
        emails_response.raise_for_status()
        emails = emails_response.json()
    except (requests.RequestException, ValueError):
        raise OAuthProviderError()

    primary_email = next((e for e in emails if e.get("primary")), None) or (emails[0] if emails else None)
    if not primary_email or not primary_email.get("email"):
        raise OAuthProviderError("Your GitHub account has no accessible email address.")

    return {
        "subject": str(user.get("id")),
        "email": primary_email["email"],
        "email_verified": bool(primary_email.get("verified")),
        "full_name": user.get("name") or user.get("login") or "",
        "avatar_url": user.get("avatar_url") or "",
    }


def _exchange_google_code(*, code, redirect_uri):
    config = _provider_config("google")
    try:
        token_response = requests.post(
            config["token_url"],
            data={
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=OAUTH_HTTP_TIMEOUT,
        )
        token_response.raise_for_status()
        access_token = token_response.json().get("access_token")
        if not access_token:
            raise OAuthProviderError()

        user_response = requests.get(
            config["user_url"],
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=OAUTH_HTTP_TIMEOUT,
        )
        user_response.raise_for_status()
        user = user_response.json()
    except (requests.RequestException, ValueError):
        raise OAuthProviderError()

    if not user.get("email"):
        raise OAuthProviderError("Your Google account has no accessible email address.")

    return {
        "subject": str(user.get("sub")),
        "email": user["email"],
        "email_verified": bool(user.get("email_verified")),
        "full_name": user.get("name") or "",
        "avatar_url": user.get("picture") or "",
    }


EXCHANGERS = {"github": _exchange_github_code, "google": _exchange_google_code}


def exchange_code_for_profile(*, provider, code, redirect_uri):
    exchanger = EXCHANGERS.get(provider)
    if exchanger is None:
        raise OAuthProviderError(f"Unsupported OAuth provider: {provider}")
    return exchanger(code=code, redirect_uri=redirect_uri)
