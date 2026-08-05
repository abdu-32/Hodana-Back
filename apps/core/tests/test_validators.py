import pytest
from rest_framework.exceptions import ValidationError

from apps.core.validators import validate_public_https_url


class TestValidatePublicHttpsUrl:
    @pytest.mark.parametrize("value", [None, ""])
    def test_blank_or_none_is_left_alone(self, value):
        """Blank-handling is the caller's job (allow_blank / required) --
        this validator only judges non-empty values."""
        assert validate_public_https_url(value) == value

    @pytest.mark.parametrize("value", [
        "https://storage.example.com/docs/file.pdf",
        "https://bucket.s3.amazonaws.com/avatars/abc.png",
    ])
    def test_valid_https_url_passes(self, value):
        assert validate_public_https_url(value) == value

    @pytest.mark.parametrize("value", [
        "http://storage.example.com/docs/file.pdf",  # not https
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "file:///etc/passwd",
        "ftp://storage.example.com/file.pdf",
    ])
    def test_non_https_scheme_is_rejected(self, value):
        with pytest.raises(ValidationError):
            validate_public_https_url(value)

    @pytest.mark.parametrize("value", [
        "https://localhost/file.pdf",
        "https://127.0.0.1/file.pdf",
        "https://0.0.0.0/file.pdf",
        "https://169.254.169.254/latest/meta-data/",  # cloud metadata endpoint
        "https://10.0.0.5/internal",
        "https://192.168.1.1/internal",
        "https://[::1]/file.pdf",  # IPv6 loopback
    ])
    def test_internal_or_loopback_host_is_rejected(self, value):
        with pytest.raises(ValidationError):
            validate_public_https_url(value)

    def test_normal_dns_hostname_is_not_treated_as_blocked(self):
        """A hostname that merely *resolves* to an internal address isn't
        (and can't be, without a DNS lookup this validator deliberately
        doesn't do -- see its module docstring) caught here."""
        assert validate_public_https_url("https://example.com/file.pdf") == "https://example.com/file.pdf"
