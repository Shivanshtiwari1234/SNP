from .protocol import RELIABLE_TIMEOUT, RELIABLE_MAX_RETRIES, RELIABLE_BACKOFF
from .reliability import send_reliable_message


class SNPClient:
    """Simplified public client API for synchronous SNP request/response calls."""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        timeout: float = RELIABLE_TIMEOUT,
        max_retries: int = RELIABLE_MAX_RETRIES,
        backoff: float = RELIABLE_BACKOFF,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff

    def request(self, message: str) -> str:
        return send_reliable_message(
            self.host,
            self.port,
            message,
            timeout=self.timeout,
            max_retries=self.max_retries,
            backoff=self.backoff,
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False
