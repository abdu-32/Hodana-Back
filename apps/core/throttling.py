"""
Custom throttle classes — Design Spec Sec 6.7.

DRF's stock ScopedRateThrottle only understands rate strings like
"5/min" or "10/day" (a bare unit word, no multiplier). It can't express
"1 request per 5 minutes" directly, so FR-AUTH-003's cadence needs an
explicit duration instead of a parsed rate string.
"""

from rest_framework.throttling import ScopedRateThrottle


class FiveMinuteScopedRateThrottle(ScopedRateThrottle):
    """1 request per 5 minutes, per Design Spec Sec 6.7."""

    def parse_rate(self, rate):
        num_requests, _ = rate.split("/")
        return int(num_requests), 300  # 5 minutes in seconds