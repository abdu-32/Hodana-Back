"""support_ai app."""

try:
    from .httpx_compat import install_httpx_fallback
    install_httpx_fallback()
except Exception:
    pass
