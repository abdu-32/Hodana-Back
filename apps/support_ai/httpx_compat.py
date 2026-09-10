"""Minimal fallback for installations where the optional ``httpx`` package is absent.

The public application still uses httpx whenever it is installed.  The
fallback exposes the small synchronous API used by this app and is backed by
the project's existing ``requests`` dependency.
"""

from __future__ import annotations

import importlib
import sys
import types


def install_httpx_fallback() -> None:
    """Make a compatible ``httpx`` module available only when needed."""
    try:
        importlib.import_module("httpx")
        return
    except ImportError:
        pass

    import requests

    module = types.ModuleType("httpx")

    class TimeoutException(Exception):
        """Compatibility equivalent of httpx.TimeoutException."""

    class HTTPStatusError(Exception):
        """Compatibility equivalent of httpx.HTTPStatusError."""
        def __init__(self, message="", *, request=None, response=None):
            super().__init__(message)
            self.request = request
            self.response = response

    class RequestError(Exception):
        """Compatibility equivalent of httpx.RequestError."""

    class Limits:
        """Compatibility equivalent of httpx.Limits."""
        def __init__(self, *, max_connections=None, max_keepalive_connections=None, **_kwargs):
            self.max_connections = max_connections
            self.max_keepalive_connections = max_keepalive_connections

    class Client:
        def __init__(self, *, timeout=None, limits=None, **_kwargs):
            self.timeout = timeout
            self.limits = limits
            self._session = requests.Session()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()
            return False

        def close(self):
            self._session.close()

        def post(self, url, *, headers=None, json=None, **kwargs):
            try:
                resp = self._session.post(
                    url,
                    headers=headers,
                    json=json,
                    timeout=kwargs.pop("timeout", self.timeout),
                    **kwargs,
                )
                orig_raise = resp.raise_for_status
                def _raise_for_status():
                    try:
                        orig_raise()
                    except requests.HTTPError as err:
                        raise HTTPStatusError(str(err), response=resp) from err
                resp.raise_for_status = _raise_for_status
                return resp
            except requests.Timeout as exc:
                raise TimeoutException(str(exc)) from exc
            except requests.RequestException as exc:
                raise RequestError(str(exc)) from exc

    module.Client = Client
    module.Limits = Limits
    module.TimeoutException = TimeoutException
    module.HTTPStatusError = HTTPStatusError
    module.RequestError = RequestError
    sys.modules["httpx"] = module
