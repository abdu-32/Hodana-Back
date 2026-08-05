import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def _clear_cache_between_tests():
    """DRF's ScopedRateThrottle (login/signup/oauth_login/
    password_reset_request throttles) stores its request counters in the
    Django cache. Django's test runner isolates the database per test
    (transaction rollback) but does nothing for the cache -- without this,
    a test file with several HTTP-level POSTs to e.g. /auth/signup (10/hour)
    could tip a later, unrelated test over the limit purely because of
    test execution order, producing a flaky 429 instead of the response
    the test actually expects. Clearing before AND after covers both
    "this test's own throttle state shouldn't affect the next test" and
    "a previous test's leftover state shouldn't affect this one" for
    whatever order pytest happens to run tests in.
    """
    cache.clear()
    yield
    cache.clear()
