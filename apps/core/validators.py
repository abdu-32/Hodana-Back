"""
core -- shared serializer-level validators.

IMPORTANT CONTEXT for validate_public_https_url below: nothing in this
backend currently receives raw file bytes. Org verification documents
(organizations.SubmitVerificationDocumentsSerializer) and profile
avatar/portfolio links (accounts.UserUpdateSerializer) are all stored as
plain URL strings pointing at files the client is assumed to have
already put somewhere else -- the documented intent (see
organizations/serializers.py) is "direct-to-storage" uploads (client
uploads straight to object storage, backend just records the resulting
URL), but there is no presigned-upload-URL endpoint implemented anywhere
in this codebase yet, and object storage itself is disabled in settings
in favor of local disk (config/settings/base.py). So today these are
effectively "paste any link" fields.

That means classic file-upload hardening -- size limits, MIME-type
allowlists, malware/AV scanning -- doesn't apply here: there are no bytes
on this server to size-check, type-sniff, or scan. What DOES apply, and
is what this validator does, is treating the URL *string* itself as
untrusted input:

  - reject anything that isn't a well-formed https:// URL (no
    javascript:, data:, file:, plain http, etc.)
  - reject literal loopback/private/link-local/reserved IP hosts, so a
    URL can't point at this server's own network or an internal service
    (SSRF-adjacent hardening -- precautionary, since nothing here
    fetches these URLs server-side today, but a future feature easily
    could, e.g. generating a thumbnail or a link preview)

This is a real fix for the actual attack surface (arbitrary/malicious
link injection into data a Platform Admin reviews as verification
evidence, or that renders as a clickable/embedded link elsewhere), but it
is NOT a substitute for real upload hardening once actual file bytes
flow through this backend or a presigned-upload flow. That's flagged
separately, not silently patched over here.
"""

import ipaddress
from urllib.parse import urlparse

from rest_framework.exceptions import ValidationError

_BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain", "metadata.google.internal"}

# 169.254.169.254 is the cloud-provider instance-metadata endpoint (AWS,
# GCP, Azure alike) -- the single highest-value SSRF target, called out
# explicitly in addition to the general link-local range check below.
_BLOCKED_LITERAL_IPS = {"169.254.169.254"}


def _is_blocked_host(hostname):
    if not hostname:
        return True
    hostname = hostname.lower()
    if hostname in _BLOCKED_HOSTNAMES or hostname in _BLOCKED_LITERAL_IPS:
        return True
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        # A normal DNS hostname, not a literal IP -- can't be checked any
        # further without an actual DNS lookup at request time, which
        # nothing here does (and a lookup now wouldn't protect against
        # DNS rebinding at fetch time anyway). This is a first line of
        # defense against the obvious/lazy cases, not a complete SSRF
        # mitigation -- see the module docstring.
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast


def validate_public_https_url(value):
    """Field-level validator for URL-pointer fields. Blank/empty values
    are left alone here -- callers that need to reject a missing value
    do that separately (required=True or a min_length on the containing
    list), so this can be reused on both required and optional fields
    without fighting `allow_blank`."""
    if not value:
        return value

    parsed = urlparse(value)
    if parsed.scheme != "https":
        raise ValidationError("Must be an https:// URL.")
    if _is_blocked_host(parsed.hostname):
        raise ValidationError("This URL points to a host that isn't allowed.")
    return value
