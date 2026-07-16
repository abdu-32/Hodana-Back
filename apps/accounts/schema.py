from drf_spectacular.extensions import OpenApiAuthenticationExtension


class TokenVersionJWTAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "apps.accounts.authentication.TokenVersionJWTAuthentication"
    name = "jwtAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }