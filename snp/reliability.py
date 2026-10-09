import socket
import time

from .protocol import (
    MAX_PACKET,
    TYPE_ACK,
    TYPE_MESSAGE,
    TYPE_RESPONSE,
    RequestTracker,
    decode_packet,
    encode_packet,
)

RELIABLE_TIMEOUT = 1.0
RELIABLE_MAX_RETRIES = 3
RELIABLE_BACKOFF = 0.25


def send_reliable_message(
    host: str,
    port: int,
    message: str,
    *,
    timeout: float = RELIABLE_TIMEOUT,
    max_retries: int = RELIABLE_MAX_RETRIES,
    backoff: float = RELIABLE_BACKOFF,
    socket_factory=socket.socket,
) -> str:
    """Send a request with bounded retries and duplicate suppression for UDP datagrams."""
    payload = message.encode("utf-8")
    tracker = RequestTracker()
    sequence = tracker.allocate()

    for attempt in range(max_retries):
        with socket_factory(socket.AF_INET, socket.SOCK_DGRAM) as client:
            client.settimeout(timeout)
            client.sendto(encode_packet(TYPE_MESSAGE, sequence, payload), (host, port))

            while True:
                try:
                    response, address = client.recvfrom(MAX_PACKET + 1)
                except socket.timeout:
                    if attempt + 1 >= max_retries:
                        raise TimeoutError("Reliable SNP request timed out")
                    time.sleep(backoff * (2**attempt))
                    break

                message_type, response_sequence, response_payload = decode_packet(response)

                if message_type == TYPE_ACK:
                    if response_sequence != sequence:
                        continue
                    continue

                if message_type != TYPE_RESPONSE:
                    raise ValueError("Expected an SNP response")

                if response_sequence != sequence:
                    continue

                if address[0] != host:
                    raise ValueError("Response came from an unexpected host")

                tracker.complete(sequence)
                return response_payload.decode("utf-8", errors="replace")

    raise TimeoutError("Reliable SNP request timed out")
