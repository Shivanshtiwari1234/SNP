import json
import socket

from .protocol import (
    TYPE_DISCOVERY_REQUEST,
    TYPE_DISCOVERY_RESPONSE,
    VERSION,
    MAX_PACKET,
    decode_packet,
    encode_packet,
)


def discover_peers(host: str = "127.0.0.1", port: int = 9000, *, timeout: float = 0.5, max_responses: int = 16) -> list[dict[str, object]]:
    """Send a discovery request and parse the peer metadata replies."""
    peers: list[dict[str, object]] = []
    request = encode_packet(TYPE_DISCOVERY_REQUEST, 0, b"discover")

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        client.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        client.settimeout(timeout)
        client.sendto(request, (host, port))

        while len(peers) < max_responses:
            try:
                response, address = client.recvfrom(MAX_PACKET + 1)
            except socket.timeout:
                break

            try:
                message_type, _, payload = decode_packet(response)
                if message_type != TYPE_DISCOVERY_RESPONSE:
                    continue
                metadata = json.loads(payload.decode("utf-8"))
            except Exception:
                continue

            peers.append({
                "host": address[0],
                "port": metadata.get("port", port),
                "service": metadata.get("service", "snp"),
                "version": metadata.get("version", VERSION),
            })

    return peers
