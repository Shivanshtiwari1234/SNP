
#!/usr/bin/env python3
"""Shivi Network Protocol (SNP) — initial implementation."""

import argparse
import json
import socket
import struct
import sys
import threading
import time

# SNP wire format
MAGIC = b"SNPK"
VERSION = 1

TYPE_MESSAGE = 1
TYPE_RESPONSE = 2
TYPE_ACK = 3
TYPE_FRAGMENT = 4
TYPE_DISCOVERY_REQUEST = 5
TYPE_DISCOVERY_RESPONSE = 6

# magic, version, type, sequence number, payload length
HEADER = struct.Struct("!4sBBIH")
HEADER_SIZE = HEADER.size

MAX_PAYLOAD = 1200
MAX_PACKET = HEADER_SIZE + MAX_PAYLOAD
MAX_SEQUENCE = 0xFFFFFFFF
FRAGMENT_HEADER = struct.Struct("!HH")
RELIABLE_TIMEOUT = 1.0
RELIABLE_MAX_RETRIES = 3
RELIABLE_BACKOFF = 0.25


class SNPError(Exception):
    """An SNP protocol error."""


def next_sequence(current: int) -> int:
    """Return the next sequence number, wrapping to zero at the 32-bit boundary."""
    if not isinstance(current, int):
        raise SNPError("Sequence value must be an integer")

    if not 0 <= current <= MAX_SEQUENCE:
        raise SNPError("Sequence number out of range")

    return (current + 1) % (MAX_SEQUENCE + 1)


class RequestTracker:
    """Track outstanding SNP requests using the 32-bit sequence field as the ID."""

    def __init__(self) -> None:
        self._next_sequence = 0
        self._pending: set[int] = set()

    def allocate(self) -> int:
        sequence = self._next_sequence
        self._pending.add(sequence)
        self._next_sequence = next_sequence(sequence)
        return sequence

    def accepts_response(self, sequence: int) -> bool:
        if not 0 <= sequence <= MAX_SEQUENCE:
            return False
        return sequence in self._pending

    def complete(self, sequence: int) -> None:
        self._pending.discard(sequence)


class ResponseCache:
    """Cache server responses so duplicate requests can be answered without re-running the operation."""

    def __init__(self, capacity: int = 128, ttl_seconds: int = 30) -> None:
        self.capacity = max(1, capacity)
        self.ttl_seconds = max(1, ttl_seconds)
        self._entries: dict[tuple[str, int, int], tuple[float, bytes]] = {}

    def _purge_expired(self) -> None:
        cutoff = time.monotonic() - self.ttl_seconds
        for key, (timestamp, _) in list(self._entries.items()):
            if timestamp <= cutoff:
                del self._entries[key]

    def store(self, key: tuple[str, int, int], value: bytes) -> None:
        self._purge_expired()
        if len(self._entries) >= self.capacity:
            oldest_key = next(iter(self._entries))
            del self._entries[oldest_key]
        self._entries[key] = (time.monotonic(), value)

    def lookup(self, key: tuple[str, int, int]) -> bytes | None:
        self._purge_expired()
        entry = self._entries.get(key)
        if entry is None:
            return None
        return entry[1]


class FragmentAssembler:
    """Reassemble fragmented SNP payloads ordered by fragment index."""

    def __init__(self, max_pending: int = 64, ttl_seconds: int = 30) -> None:
        self.max_pending = max(1, max_pending)
        self.ttl_seconds = max(1, ttl_seconds)
        self._states: dict[int, dict[str, object]] = {}

    def _purge_expired(self) -> None:
        cutoff = time.monotonic() - self.ttl_seconds
        for sequence, state in list(self._states.items()):
            if state["created"] <= cutoff:
                del self._states[sequence]

    def add_packet(self, packet: bytes) -> bytes | None:
        message_type, sequence, payload = decode_packet(packet)

        if message_type != TYPE_FRAGMENT:
            raise SNPError("Packet is not an SNP fragment")

        if len(payload) < FRAGMENT_HEADER.size:
            raise SNPError("Fragment payload is too short")

        fragment_index, fragment_total = FRAGMENT_HEADER.unpack_from(payload[: FRAGMENT_HEADER.size])
        fragment_data = payload[FRAGMENT_HEADER.size :]

        if fragment_total <= 0 or fragment_index >= fragment_total:
            raise SNPError("Fragment metadata is invalid")

        self._purge_expired()
        if len(self._states) >= self.max_pending:
            oldest_sequence = next(iter(self._states))
            del self._states[oldest_sequence]

        state = self._states.setdefault(sequence, {"created": time.monotonic(), "parts": {}, "total": fragment_total})
        if state["total"] != fragment_total:
            raise SNPError("Fragment count mismatch")

        parts = state["parts"]
        if fragment_index in parts:
            return None

        parts[fragment_index] = fragment_data
        if len(parts) == fragment_total:
            assembled = b"".join(parts[index] for index in range(fragment_total))
            del self._states[sequence]
            return assembled
        return None


def fragment_message(sequence: int, payload: bytes) -> list[bytes]:
    """Split a logical payload into consecutive SNP fragment datagrams."""
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise SNPError("Payload must be bytes-like data")

    payload = bytes(payload)
    if len(payload) <= MAX_PAYLOAD:
        return [encode_packet(TYPE_MESSAGE, sequence, payload)]

    fragment_size = MAX_PAYLOAD - FRAGMENT_HEADER.size
    total_fragments = (len(payload) + fragment_size - 1) // fragment_size

    if total_fragments > 0xFFFF:
        raise SNPError("Message exceeds the supported fragment count")

    fragments: list[bytes] = []
    for index in range(total_fragments):
        start = index * fragment_size
        end = min(start + fragment_size, len(payload))
        fragment_payload = FRAGMENT_HEADER.pack(index, total_fragments) + payload[start:end]
        fragments.append(encode_packet(TYPE_FRAGMENT, sequence, fragment_payload))
    return fragments


def encode_packet(message_type: int, sequence: int, payload: bytes) -> bytes:
    """Serialize an SNP packet into bytes."""
    if message_type not in (TYPE_MESSAGE, TYPE_RESPONSE, TYPE_ACK, TYPE_FRAGMENT, TYPE_DISCOVERY_REQUEST, TYPE_DISCOVERY_RESPONSE):
        raise SNPError("Unsupported message type")

    if not 0 <= sequence <= 0xFFFFFFFF:
        raise SNPError("Sequence number out of range")

    if isinstance(payload, memoryview):
        payload = payload.tobytes()
    elif isinstance(payload, bytearray):
        payload = bytes(payload)
    elif not isinstance(payload, (bytes, bytearray, memoryview)):
        raise SNPError("Payload must be bytes-like data")

    if len(payload) > MAX_PAYLOAD:
        raise SNPError(f"Payload exceeds {MAX_PAYLOAD} bytes")

    header = HEADER.pack(
        MAGIC,
        VERSION,
        message_type,
        sequence,
        len(payload),
    )
    return header + payload


def decode_packet(packet: bytes) -> tuple[int, int, bytes]:
    """Validate and deserialize an SNP packet."""
    if isinstance(packet, memoryview):
        packet = packet.tobytes()
    elif isinstance(packet, bytearray):
        packet = bytes(packet)
    elif not isinstance(packet, (bytes, bytearray, memoryview)):
        raise SNPError("Packet must be bytes-like data")

    if len(packet) < HEADER_SIZE:
        raise SNPError("Packet is shorter than the SNP header")

    if len(packet) > MAX_PACKET:
        raise SNPError("Packet exceeds the maximum SNP packet size")

    magic, version, message_type, sequence, length = HEADER.unpack_from(packet)

    if magic != MAGIC:
        raise SNPError("Invalid SNP signature")

    if version != VERSION:
        raise SNPError(f"Unsupported SNP version: {version}")

    if message_type not in (TYPE_MESSAGE, TYPE_RESPONSE, TYPE_ACK, TYPE_FRAGMENT, TYPE_DISCOVERY_REQUEST, TYPE_DISCOVERY_RESPONSE):
        raise SNPError(f"Unknown message type: {message_type}")

    payload = packet[HEADER_SIZE:]

    if len(payload) != length:
        raise SNPError("Payload length does not match the header")

    return message_type, sequence, payload


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

    def __enter__(self) -> "SNPClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class SNPServer:
    """Small UDP server wrapper for local SNP request/response handling."""

    def __init__(self, host: str = "127.0.0.1", port: int = 9000) -> None:
        self.host = host
        self.port = port
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._cache = ResponseCache()
        self._fragment_assembler = FragmentAssembler()
        self._ready = threading.Event()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return

        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.bind((self.host, self.port))
        self.port = self._socket.getsockname()[1]
        self._stop_event.clear()
        self._ready.clear()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=2.0)

    def _serve(self) -> None:
        if self._socket is None:
            return

        self._socket.settimeout(0.2)
        self._ready.set()

        while not self._stop_event.is_set():
            try:
                packet, address = self._socket.recvfrom(MAX_PACKET + 1)
            except socket.timeout:
                continue
            except OSError:
                if self._stop_event.is_set():
                    break
                raise

            try:
                message_type, sequence, payload = decode_packet(packet)

                if message_type == TYPE_DISCOVERY_REQUEST:
                    response = encode_packet(
                        TYPE_DISCOVERY_RESPONSE,
                        sequence,
                        json.dumps({"service": "snp", "version": VERSION, "port": self.port}).encode("utf-8"),
                    )
                    self._socket.sendto(response, address)
                    continue

                if message_type == TYPE_FRAGMENT:
                    assembled = self._fragment_assembler.add_packet(packet)
                    if assembled is None:
                        continue
                    payload = assembled
                    message_type = TYPE_MESSAGE

                if message_type != TYPE_MESSAGE:
                    print(f"Ignored non-message packet from {address}")
                    continue

                request_key = (address[0], address[1], sequence)
                cached_response = self._cache.lookup(request_key)
                if cached_response is not None:
                    self._socket.sendto(cached_response, address)
                    continue

                message = payload.decode("utf-8", errors="replace")
                print(f"[{address[0]}:{address[1]}] {message}")

                response_payload = b"Received: " + payload
                response = encode_packet(TYPE_RESPONSE, sequence, response_payload)
                ack = encode_packet(TYPE_ACK, sequence, b"")
                self._cache.store(request_key, response)
                self._socket.sendto(ack, address)
                self._socket.sendto(response, address)
            except SNPError as exc:
                print(f"Rejected packet from {address}: {exc}")

    def stop(self) -> None:
        self._stop_event.set()
        if self._socket is not None:
            self._socket.close()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._socket = None


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
            except (SNPError, UnicodeDecodeError, json.JSONDecodeError):
                continue

            peers.append({"host": address[0], "port": metadata.get("port", port), "service": metadata.get("service", "snp"), "version": metadata.get("version", VERSION)})

    return peers


def run_server(host: str, port: int) -> None:
    """Listen for SNP messages and respond to clients over UDP."""
    cache = ResponseCache()

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
        server.bind((host, port))
        print(f"SNP server listening on {host}:{port} (UDP)")

        fragment_assembler = FragmentAssembler()
        while True:
            packet, address = server.recvfrom(MAX_PACKET + 1)

            try:
                message_type, sequence, payload = decode_packet(packet)

                if message_type == TYPE_DISCOVERY_REQUEST:
                    response = encode_packet(
                        TYPE_DISCOVERY_RESPONSE,
                        sequence,
                        json.dumps({"service": "snp", "version": VERSION, "port": port}).encode("utf-8"),
                    )
                    server.sendto(response, address)
                    continue

                if message_type == TYPE_FRAGMENT:
                    assembled = fragment_assembler.add_packet(packet)
                    if assembled is None:
                        continue
                    payload = assembled
                    message_type = TYPE_MESSAGE

                if message_type != TYPE_MESSAGE:
                    print(f"Ignored non-message packet from {address}")
                    continue

                request_key = (address[0], address[1], sequence)
                cached_response = cache.lookup(request_key)
                if cached_response is not None:
                    server.sendto(cached_response, address)
                    continue

                message = payload.decode("utf-8", errors="replace")
                print(f"[{address[0]}:{address[1]}] {message}")

                response_payload = b"Received: " + payload
                response = encode_packet(
                    TYPE_RESPONSE,
                    sequence,
                    response_payload,
                )
                ack = encode_packet(TYPE_ACK, sequence, b"")
                cache.store(request_key, response)
                server.sendto(ack, address)
                server.sendto(response, address)

            except SNPError as exc:
                print(f"Rejected packet from {address}: {exc}")


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
                    raise SNPError("Expected an SNP response")

                if response_sequence != sequence:
                    continue

                if address[0] != host:
                    raise SNPError("Response came from an unexpected host")

                tracker.complete(sequence)
                return response_payload.decode("utf-8", errors="replace")

    raise TimeoutError("Reliable SNP request timed out")


def run_client(host: str, port: int, message: str) -> None:
    """Send one SNP message and wait for a response."""
    payload = message.encode("utf-8")

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        client.settimeout(3.0)

        tracker = RequestTracker()
        sequence = tracker.allocate()
        packet = encode_packet(TYPE_MESSAGE, sequence, payload)
        client.sendto(packet, (host, port))

        try:
            response, address = client.recvfrom(MAX_PACKET + 1)
        except socket.timeout:
            print("No response received (timeout).")
            sys.exit(1)

        message_type, response_sequence, response_payload = decode_packet(response)

        if message_type != TYPE_RESPONSE:
            raise SNPError("Expected an SNP response")

        if not tracker.accepts_response(response_sequence):
            raise SNPError("Response sequence number does not match an active request")

        tracker.complete(response_sequence)

        if address[0] != host:
            raise SNPError("Response came from an unexpected host")

        print(response_payload.decode("utf-8", errors="replace"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Shivi Network Protocol (SNP)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    server_parser = subparsers.add_parser("server", help="Start an SNP server")
    server_parser.add_argument("--host", default="127.0.0.1")
    server_parser.add_argument("--port", type=int, default=9000)

    client_parser = subparsers.add_parser("send", help="Send an SNP message")
    client_parser.add_argument("message")
    client_parser.add_argument("--host", default="127.0.0.1")
    client_parser.add_argument("--port", type=int, default=9000)

    args = parser.parse_args()

    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535")

    try:
        if args.command == "server":
            run_server(args.host, args.port)
        else:
            run_client(args.host, args.port, args.message)
    except (SNPError, OSError) as exc:
        print(f"SNP error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()