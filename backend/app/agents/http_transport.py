"""Shared immutable TLS configuration for internal Agent HTTP clients."""
from functools import lru_cache
import ssl

import certifi


@lru_cache(maxsize=1)
def agent_ssl_context() -> ssl.SSLContext:
    """Preserve HTTPX trust_env=False verification without reloading CA files per request.

    Do not mutate the returned context. Clients/connections retain their own
    lifetime, credentials and event loop; only trusted CA configuration is shared.
    """
    return ssl.create_default_context(cafile=certifi.where())
