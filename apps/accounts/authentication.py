"""
accounts -- authentication

Checks the token_version claim on every request against the current DB
value (Design Spec Sec 4.3) so a password reset / logout-all / suspension
invalidates outstanding access tokens immediately, not just at natural
expiry. Tokens are issued with this claim already embedded --
see services._issue_tokens.
"""

from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed


class TokenVersionJWTAuthentication(JWTAuthentication):
    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        token_version = validated_token.get("token_version")
        if token_version is None or token_version != user.token_version:
            raise AuthenticationFailed("Token is no longer valid.", code="token_not_valid")
        return user