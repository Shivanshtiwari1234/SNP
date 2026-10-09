
#!/usr/bin/env python3
"""Shivi Network Protocol (SNP) — initial implementation."""

import argparse
import socket
import struct
import sys

# SNP wire format
MAGIC = b"SNPK"
VERSION = 1

TYPE_MESSAGE = 1
TYPE_RESPONSE = 2

# magic, version, type, sequence number, payload length
HEADER = struct.Struct("!4sBBIH")
HEADER_SIZE = HEADER.size

MAX_PAYLOAD = 1200
MAX_PACKET = HEADER_SIZE + MAX_PAYLOAD
MAX_SEQUENCE = 0xFFFFFFFF


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


def encode_packet(message_type: int, sequence: int, payload: bytes) -> bytes:
    """Serialize an SNP packet into bytes."""
    if message_type not in (TYPE_MESSAGE, TYPE_RESPONSE):
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

    if message_type not in (TYPE_MESSAGE, TYPE_RESPONSE):
        raise SNPError(f"Unknown message type: {message_type}")

    payload = packet[HEADER_SIZE:]

    if len(payload) != length:
        raise SNPError("Payload length does not match the header")

    return message_type, sequence, payload


def run_server(host: str, port: int) -> None:
    """Listen for SNP messages and respond to clients over UDP."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
        server.bind((host, port))
        print(f"SNP server listening on {host}:{port} (UDP)")

        while True:
            packet, address = server.recvfrom(MAX_PACKET + 1)

            try:
                message_type, sequence, payload = decode_packet(packet)

                if message_type != TYPE_MESSAGE:
                    print(f"Ignored non-message packet from {address}")
                    continue

                message = payload.decode("utf-8", errors="replace")
                print(f"[{address[0]}:{address[1]}] {message}")

                response = encode_packet(
                    TYPE_RESPONSE,
                    sequence,
                    b"Received: " + payload,
                )
                server.sendto(response, address)

            except SNPError as exc:
                print(f"Rejected packet from {address}: {exc}")


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