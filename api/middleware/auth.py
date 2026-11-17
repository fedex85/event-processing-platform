"""API-key authentication."""

import hashlib
import hmac
import logging
from collections.abc import Iterable

from api.errors.exceptions import UnauthorizedError

logger = logging.getLogger(__name__)

API_KEY_HEADER = "X-API-Key"


class ApiKeyAuthenticator:
    def __init__(self, api_keys: Iterable[str]) -> None:
        self._keys = [key.encode("utf-8") for key in api_keys]

    def authenticate(self, presented: str | None) -> str:
        """Return a stable, non-reversible client id, or raise ``UnauthorizedError``.

        Every configured key is compared, with no early exit, so response time
        does not reveal how much of a key was correct.
        """
        if presented:
            candidate = presented.encode("utf-8")
            matched = False
            for key in self._keys:
                if hmac.compare_digest(candidate, key):
                    matched = True
            if matched:
                return hashlib.sha256(candidate).hexdigest()[:12]
        logger.warning("authentication_failed")
        raise UnauthorizedError()
