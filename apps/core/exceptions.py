"""
Uniform API error contract — Design Spec Sec 6.5.

Every error response follows the same envelope so frontend error handling
is generic instead of per-endpoint:

{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Human readable summary",
    "details": {"field": ["reason"]}
  }
}
"""

from rest_framework.views import exception_handler


def api_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return None

    response.data = {
        "error": {
            "code": getattr(exc, "default_code", "error").upper(),
            "message": str(exc),
            "details": response.data,
        }
    }
    return response
